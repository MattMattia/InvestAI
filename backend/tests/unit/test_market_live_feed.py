"""
Live market feed invariants: official BYMA schedule (10:30-18:00 ART), live price ratchet
(a real price is never replaced by a stale static seed), bounded micro-tick and real
intraday 1D bars with the after-hours marker restricted to closed sessions.
"""

import asyncio
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import httpx
import pytest
from app.domain.services import market_data_provider as mdp
from app.domain.services.market_data_provider import PublicMarket10YProvider as Provider
from app.infrastructure.market_data import ssrf_guard

pytestmark = pytest.mark.unit

ART = timezone(timedelta(hours=-3))
SESSION_DAY = datetime(2026, 11, 10, tzinfo=ART)  # Tuesday
NVDA_STALE_SEED = 14290.0
NVDA_REAL_PRICE = 12180.0
NVDA_REAL_OPEN = 12270.0
# Yahoo's chartPreviousClose for a 5d range is the close before the whole range
STALE_RANGE_PREVIOUS_CLOSE = 14400.0


def _freeze_time(monkeypatch: pytest.MonkeyPatch, moment: datetime) -> None:
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return moment.astimezone(tz) if tz is not None else moment.replace(tzinfo=None)

    monkeypatch.setattr(mdp, "datetime", FrozenDateTime)


class FakeResponse:
    def __init__(self, status_code: int, payload: Any = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self) -> Any:
        return self._payload


class FakeYahoo:
    """Routes outbound GETs by URL fragment; unknown URLs fail like a network timeout."""

    def __init__(self) -> None:
        self.routes: dict[str, FakeResponse] = {}
        self.requested: list[str] = []

    def client_factory(self, *_args: Any, **_kwargs: Any) -> "FakeYahoo":
        return self

    async def __aenter__(self) -> "FakeYahoo":
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        return None

    async def get(self, url: str, **_kwargs: Any) -> FakeResponse:
        self.requested.append(url)
        for fragment, response in self.routes.items():
            if fragment in url:
                return response
        raise httpx.ConnectTimeout("simulated timeout")


def _daily_quote_payload(price: float, day_open: float, previous_close: float) -> dict[str, Any]:
    base_ts = int(SESSION_DAY.replace(hour=10, minute=30).timestamp())
    return {
        "chart": {
            "result": [
                {
                    "meta": {
                        "regularMarketPrice": price,
                        "chartPreviousClose": STALE_RANGE_PREVIOUS_CLOSE,
                    },
                    "timestamp": [base_ts - 86400, base_ts],
                    "indicators": {
                        "quote": [
                            {
                                "open": [previous_close - 50.0, day_open],
                                "close": [previous_close, price],
                            }
                        ]
                    },
                }
            ]
        }
    }


def _intraday_payload(day_open: float, closes: list[float]) -> dict[str, Any]:
    first_ts = int(SESSION_DAY.replace(hour=10, minute=30).timestamp())
    timestamps = [first_ts + i * 300 for i in range(len(closes))]
    opens = [closes[0] + 15.0] + closes[:-1]
    return {
        "chart": {
            "result": [
                {
                    "meta": {"regularMarketOpen": day_open},
                    "timestamp": timestamps,
                    "indicators": {
                        "quote": [
                            {
                                "open": opens,
                                "high": [
                                    max(o, c) + 5.0 for o, c in zip(opens, closes, strict=True)
                                ],
                                "low": [
                                    min(o, c) - 5.0 for o, c in zip(opens, closes, strict=True)
                                ],
                                "close": closes,
                                "volume": [1000] * len(closes),
                            }
                        ]
                    },
                }
            ]
        }
    }


@pytest.fixture
def feed(monkeypatch: pytest.MonkeyPatch) -> FakeYahoo:
    """Isolated provider state with all outbound HTTP replaced by a routable fake."""
    fake = FakeYahoo()
    monkeypatch.setattr(mdp.httpx, "AsyncClient", fake.client_factory)
    monkeypatch.setattr(ssrf_guard, "validate_url_against_ssrf", lambda url, dns_resolver=None: url)
    monkeypatch.setattr(Provider, "_LIVE_STATE", {})
    monkeypatch.setattr(Provider, "_BARS_CACHE", {})
    monkeypatch.setattr(Provider, "_SESSION_OPEN", {})
    monkeypatch.setattr(Provider, "_LAST_EXTERNAL_SYNC", 0.0)
    # The class-level semaphore binds to the first event loop that contends on it.
    monkeypatch.setattr(Provider, "_semaphore", asyncio.Semaphore(8))
    monkeypatch.setattr(Provider, "_MARKET_OPEN_HM", (10, 30))
    monkeypatch.setattr(Provider, "_MARKET_CLOSE_HM", (18, 0))
    monkeypatch.setitem(mdp.BYMA_CURATED_UNIVERSE_MAP["NVDA"], "target_price", NVDA_STALE_SEED)
    return fake


@pytest.mark.parametrize(
    ("moment", "expected_open"),
    [
        (SESSION_DAY.replace(hour=10, minute=29), False),
        (SESSION_DAY.replace(hour=10, minute=30), True),
        (SESSION_DAY.replace(hour=17, minute=23), True),
        (SESSION_DAY.replace(hour=17, minute=59), True),
        (SESSION_DAY.replace(hour=18, minute=0), False),
        (SESSION_DAY.replace(hour=12) + timedelta(days=4), False),  # Saturday
    ],
)
def test_market_schedule_follows_official_byma_window(
    monkeypatch: pytest.MonkeyPatch, feed: FakeYahoo, moment: datetime, expected_open: bool
):
    _freeze_time(monkeypatch, moment)

    status = Provider.get_market_schedule_status()

    assert status["is_market_open"] is expected_open
    assert status["market_open_time"] == "10:30"
    assert status["market_close_time"] == "18:00"


def test_yahoo_trading_period_can_widen_but_never_shrink_the_window(feed: FakeYahoo):
    def period(start_hm: tuple[int, int], end_hm: tuple[int, int]) -> dict[str, Any]:
        return {
            "currentTradingPeriod": {
                "regular": {
                    "start": int(
                        SESSION_DAY.replace(hour=start_hm[0], minute=start_hm[1]).timestamp()
                    ),
                    "end": int(SESSION_DAY.replace(hour=end_hm[0], minute=end_hm[1]).timestamp()),
                }
            }
        }

    Provider._widen_schedule_from_yahoo(period((11, 0), (17, 0)))
    assert (Provider._MARKET_OPEN_HM, Provider._MARKET_CLOSE_HM) == ((10, 30), (18, 0))

    Provider._widen_schedule_from_yahoo(period((10, 0), (18, 30)))
    assert (Provider._MARKET_OPEN_HM, Provider._MARKET_CLOSE_HM) == ((10, 0), (18, 30))

    Provider._widen_schedule_from_yahoo(period((3, 0), (23, 0)))
    assert (Provider._MARKET_OPEN_HM, Provider._MARKET_CLOSE_HM) == ((10, 0), (18, 30))


async def test_live_quotes_payload_exposes_market_schedule(
    monkeypatch: pytest.MonkeyPatch, feed: FakeYahoo
):
    _freeze_time(monkeypatch, SESSION_DAY.replace(hour=17, minute=23))

    batch = await Provider.fetch_live_quotes_batch(force_refresh=True)

    assert batch["is_market_open"] is True
    assert batch["market_open_time"] == "10:30"
    assert batch["market_close_time"] == "18:00"


async def test_real_price_is_never_reverted_to_the_stale_seed(feed: FakeYahoo):
    feed.routes["NVDA.BA"] = FakeResponse(
        200, _daily_quote_payload(NVDA_REAL_PRICE, NVDA_REAL_OPEN, previous_close=12400.0)
    )
    await Provider.fetch_live_quotes_batch(force_refresh=True)

    quote = Provider._LIVE_STATE["NVDA"]
    assert quote["base_price"] == NVDA_REAL_PRICE
    assert quote["open_price"] == NVDA_REAL_OPEN
    assert quote["previous_close"] == 12400.0
    assert mdp.BYMA_CURATED_UNIVERSE_MAP["NVDA"]["target_price"] == NVDA_REAL_PRICE

    # Every provider times out on the next forced sync: the live state must survive.
    feed.routes.clear()
    batch = await Provider.fetch_live_quotes_batch(force_refresh=True)

    assert batch["NVDA"]["base_price"] == NVDA_REAL_PRICE
    assert batch["NVDA"]["previous_close"] == 12400.0
    assert abs(batch["NVDA"]["last_price"] - NVDA_REAL_PRICE) <= NVDA_REAL_PRICE * 0.0009


async def test_google_fallback_measures_change_against_live_previous_close(feed: FakeYahoo):
    feed.routes["NVDA.BA"] = FakeResponse(
        200, _daily_quote_payload(NVDA_REAL_PRICE, NVDA_REAL_OPEN, previous_close=12400.0)
    )
    await Provider.fetch_live_quotes_batch(force_refresh=True)

    feed.routes.clear()
    feed.routes["quote/NVDA:BCBA"] = FakeResponse(200, text='nvda <div data-last-price="12200.0">')
    await Provider.fetch_live_quotes_batch(force_refresh=True)

    quote = Provider._LIVE_STATE["NVDA"]
    assert quote["base_price"] == 12200.0
    assert quote["previous_close"] == 12400.0
    assert mdp.BYMA_CURATED_UNIVERSE_MAP["NVDA"]["target_price"] == 12200.0


async def test_micro_tick_stays_within_tight_band_of_real_price(feed: FakeYahoo):
    feed.routes["NVDA.BA"] = FakeResponse(
        200, _daily_quote_payload(NVDA_REAL_PRICE, NVDA_REAL_OPEN, previous_close=12400.0)
    )
    await Provider.fetch_live_quotes_batch(force_refresh=True)

    tolerance = NVDA_REAL_PRICE * 0.0008 + 0.01  # ±0.08% plus cent rounding
    for _ in range(300):
        batch = await Provider.fetch_live_quotes_batch(["NVDA"])
        assert abs(batch["NVDA"]["last_price"] - NVDA_REAL_PRICE) <= tolerance


async def test_intraday_bars_are_real_and_add_after_hours_only_when_closed(
    monkeypatch: pytest.MonkeyPatch, feed: FakeYahoo
):
    closes = [12260.0, 12240.0, 12215.0, 12190.0, 12185.0]
    feed.routes["NVDA.BA?range=5d&interval=1d"] = FakeResponse(
        200, _daily_quote_payload(NVDA_REAL_PRICE, NVDA_REAL_OPEN, previous_close=12400.0)
    )
    feed.routes["NVDA.BA?range=1d&interval=5m"] = FakeResponse(
        200, _intraday_payload(NVDA_REAL_OPEN, closes)
    )
    _freeze_time(monkeypatch, SESSION_DAY.replace(hour=19, minute=0))

    bars = await Provider.fetch_live_historical_bars("NVDA", "1D")

    session = [b for b in bars if b["is_market_open"]]
    after_hours = [b for b in bars if not b["is_market_open"]]
    # Real candles, then the session is extended to the official close at the last traded price
    assert [b["close"] for b in session] == [*closes, NVDA_REAL_PRICE]
    assert session[-1]["timestamp"].startswith("2026-11-10T18:00:00")
    assert bars[0]["open"] == NVDA_REAL_OPEN
    assert bars[0]["timestamp"].startswith("2026-11-10T10:30:00")
    assert len(after_hours) == 4
    assert bars[: len(session)] == session  # after-hours points only at the tail
    assert bars[-1]["close"] == Provider._LIVE_STATE["NVDA"]["last_price"]
    assert Provider._LIVE_STATE["NVDA"]["open_price"] == NVDA_REAL_OPEN


async def test_intraday_bars_have_no_future_points_while_market_is_open(
    monkeypatch: pytest.MonkeyPatch, feed: FakeYahoo
):
    feed.routes["NVDA.BA?range=5d&interval=1d"] = FakeResponse(
        200, _daily_quote_payload(NVDA_REAL_PRICE, NVDA_REAL_OPEN, previous_close=12400.0)
    )
    feed.routes["NVDA.BA?range=1d&interval=5m"] = FakeResponse(
        200, _intraday_payload(NVDA_REAL_OPEN, [12260.0, 12240.0, 12215.0])
    )
    now = SESSION_DAY.replace(hour=10, minute=47)
    _freeze_time(monkeypatch, now)

    bars = await Provider.fetch_live_historical_bars("NVDA", "1D")

    # Three real candles (last one at 10:40) plus the live point at "now"; real candles intact
    assert [b["close"] for b in bars[:3]] == [12260.0, 12240.0, 12215.0]
    assert len(bars) == 4
    assert bars[-1]["timestamp"].startswith("2026-11-10T10:47:00")
    assert all(b["is_market_open"] for b in bars)
    assert all(datetime.fromisoformat(b["timestamp"]) <= now for b in bars)
    assert bars[-1]["close"] == Provider._LIVE_STATE["NVDA"]["last_price"]


async def test_intraday_falls_back_to_last_real_series_then_synthetic_session(
    monkeypatch: pytest.MonkeyPatch, feed: FakeYahoo
):
    _freeze_time(monkeypatch, SESSION_DAY.replace(hour=12, minute=0))

    # No provider reachable and nothing cached: deterministic session, never past "now".
    synthetic = await Provider.fetch_live_historical_bars("NVDA", "1D")
    assert synthetic[0]["timestamp"].startswith("2026-11-10T10:30:00")
    assert synthetic[-1]["timestamp"].startswith("2026-11-10T12:00:00")
    assert all(b["is_market_open"] for b in synthetic)

    # Once a real series was seen, a later outage keeps serving it.
    closes = [12260.0, 12240.0, 12215.0]
    feed.routes["NVDA.BA?range=1d&interval=5m"] = FakeResponse(
        200, _intraday_payload(NVDA_REAL_OPEN, closes)
    )
    await Provider.fetch_live_historical_bars("NVDA", "1D")
    feed.routes.clear()
    monkeypatch.setattr(Provider, "_BARS_TTL_SECONDS", {"1D": 0.0})
    feed.requested.clear()

    bars = await Provider.fetch_live_historical_bars("NVDA", "1D")

    assert any("interval=5m" in url for url in feed.requested)  # expired cache: it did retry
    assert [b["close"] for b in bars[:3]] == closes
    assert bars[0]["open"] == NVDA_REAL_OPEN


async def test_daily_timeframes_never_flag_after_hours(
    monkeypatch: pytest.MonkeyPatch, feed: FakeYahoo
):
    first_ts = int((SESSION_DAY - timedelta(days=10)).astimezone(UTC).timestamp())
    closes = [12000.0 + i * 20.0 for i in range(8)]
    feed.routes["NVDA.BA?range=1mo&interval=1d"] = FakeResponse(
        200,
        {
            "chart": {
                "result": [
                    {
                        "meta": {},
                        "timestamp": [first_ts + i * 86400 for i in range(len(closes))],
                        "indicators": {"quote": [{"close": closes}]},
                    }
                ]
            }
        },
    )
    _freeze_time(monkeypatch, SESSION_DAY.replace(hour=21, minute=0))  # market closed

    for timeframe in ("1M", "1W", "1Y"):
        bars = await Provider.fetch_live_historical_bars("NVDA", timeframe)
        assert bars, timeframe
        assert all(b["is_market_open"] for b in bars), timeframe


async def test_previous_close_is_the_prior_session_not_the_range_start(feed: FakeYahoo):
    payload = _daily_quote_payload(NVDA_REAL_PRICE, NVDA_REAL_OPEN, previous_close=13040.0)
    feed.routes["NVDA.BA"] = FakeResponse(200, payload)

    await Provider.fetch_live_quotes_batch(force_refresh=True)

    quote = Provider._LIVE_STATE["NVDA"]
    assert quote["previous_close"] == 13040.0
    assert quote["change_pct"] == pytest.approx(
        (NVDA_REAL_PRICE - 13040.0) / 13040.0 * 100, abs=0.2
    )


async def test_previous_close_when_todays_daily_bar_is_still_pending(feed: FakeYahoo):
    payload = _daily_quote_payload(NVDA_REAL_PRICE, NVDA_REAL_OPEN, previous_close=13040.0)
    quote_series = payload["chart"]["result"][0]["indicators"]["quote"][0]
    quote_series["close"] = [13040.0, None]
    feed.routes["NVDA.BA"] = FakeResponse(200, payload)

    await Provider.fetch_live_quotes_batch(force_refresh=True)

    assert Provider._LIVE_STATE["NVDA"]["previous_close"] == 13040.0


async def test_intraday_first_point_matches_the_quote_open_column(
    monkeypatch: pytest.MonkeyPatch, feed: FakeYahoo
):
    feed.routes["NVDA.BA?range=5d&interval=1d"] = FakeResponse(
        200, _daily_quote_payload(NVDA_REAL_PRICE, NVDA_REAL_OPEN, previous_close=13040.0)
    )
    intraday = _intraday_payload(NVDA_REAL_OPEN, [12260.0, 12240.0, 12215.0])
    intraday["chart"]["result"][0]["meta"] = {}  # Yahoo chart meta carries no regularMarketOpen
    feed.routes["NVDA.BA?range=1d&interval=5m"] = FakeResponse(200, intraday)
    _freeze_time(monkeypatch, SESSION_DAY.replace(hour=10, minute=42))

    bars = await Provider.fetch_live_historical_bars("NVDA", "1D")

    assert bars[0]["open"] == NVDA_REAL_OPEN
    assert Provider._LIVE_STATE["NVDA"]["open_price"] == NVDA_REAL_OPEN
