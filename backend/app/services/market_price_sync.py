"""
Mark-to-market price persistence (SEC: no client-triggered writes).

The backend background market sync is the only writer of holding prices. It persists the
last REAL price downloaded from a provider (Yahoo Finance .BA / Google Finance :BCBA), never
the simulated 5s micro-tick shown in the live view and never a static calibrated seed.
"""

import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.asset import AssetModel
from app.models.holding import HoldingModel

logger = logging.getLogger("investai.market_price_sync")


class MarketPriceSync:
    """
    Writes the real price to every holding and asset of each ticker whose stored value
    differs. The comparison runs in SQL against the database itself, so holdings added later
    or overwritten by another process (e.g. a statement import) are corrected on the next
    cycle even when the market price did not move.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @staticmethod
    def _valid_price(entry: Mapping[str, Any]) -> float | None:
        try:
            price = float(entry.get("price") or 0.0)
        except (TypeError, ValueError):
            return None
        return price if price > 0 else None

    async def persist(self, real_prices: Mapping[str, Mapping[str, Any]]) -> int:
        """
        Persist real prices and return how many tickers had at least one stale row.
        All tickers share one transaction: on failure nothing is written and the whole
        set is retried on the next cycle.
        """
        valid = {
            ticker: (price, entry)
            for ticker, entry in real_prices.items()
            if (price := self._valid_price(entry)) is not None
        }
        if not valid:
            return 0

        written: set[str] = set()
        async with self._session_factory() as session:
            for ticker, (price, entry) in valid.items():
                result = await session.execute(
                    update(HoldingModel)
                    .where(HoldingModel.asset_ticker == ticker)
                    .where(HoldingModel.current_price != price)
                    .values(current_price=price)
                )
                if result.rowcount:
                    written.add(ticker)
                asset = (
                    await session.execute(select(AssetModel).where(AssetModel.ticker == ticker))
                ).scalar_one_or_none()
                if (
                    asset is not None
                    and (asset.metrics_payload or {}).get("current_price") != price
                ):
                    asset.metrics_payload = self._merged_payload(
                        asset.metrics_payload, price, entry
                    )
                    asset.metrics_updated_at = datetime.now(UTC)
                    written.add(ticker)
            await session.commit()

        if written:
            logger.info("market_prices_persisted tickers=%d", len(written))
        return len(written)

    @staticmethod
    def _merged_payload(
        current: dict[str, Any] | None, price: float, entry: Mapping[str, Any]
    ) -> dict[str, Any]:
        payload = dict(current or {})
        payload["reference_price"] = price
        payload["current_price"] = price
        previous_close = float(entry.get("previous_close") or 0.0)
        if previous_close > 0:
            change_nominal = round(price - previous_close, 2)
            payload["change_nominal"] = change_nominal
            payload["change_pct"] = round(change_nominal / previous_close * 100.0, 2)
        payload["updated_at"] = entry.get("observed_at") or datetime.now(UTC).isoformat()
        payload["data_source"] = entry.get("source") or "LIVE_PROVIDER"
        return payload
