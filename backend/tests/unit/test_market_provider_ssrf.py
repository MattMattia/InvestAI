"""Outbound market-data calls must pass through the SSRF guard (CLAUDE.md rule 3)."""

import pytest
from app.domain.services import market_data_provider as mdp
from app.domain.services.market_connector import SecuritySSRFViolationError
from app.infrastructure.market_data import ssrf_guard

pytestmark = pytest.mark.unit


async def test_ssrf_checked_url_rejects_loopback():
    with pytest.raises(SecuritySSRFViolationError):
        await mdp.ssrf_checked_url("http://127.0.0.1/admin")


async def test_live_fx_fetch_validates_url_before_request(monkeypatch: pytest.MonkeyPatch):
    validated: list[str] = []
    requested: list[str] = []

    def fake_guard(url: str, dns_resolver=None) -> str:
        validated.append(url)
        return url

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return [
                {"casa": "contadoconliqui", "venta": 1700.0},
                {"casa": "bolsa", "venta": 1600.0},
            ]

    class FakeClient:
        async def get(self, url: str, **_kwargs):
            requested.append(url)
            return FakeResponse()

    monkeypatch.setattr(ssrf_guard, "validate_url_against_ssrf", fake_guard)
    provider = next(
        obj
        for obj in vars(mdp).values()
        if isinstance(obj, type) and hasattr(obj, "fetch_live_fx_rates")
    )

    ccl, mep = await provider.fetch_live_fx_rates(FakeClient())

    assert validated == [provider.DOLAR_API_URL]
    assert requested == [provider.DOLAR_API_URL]
    assert (ccl, mep) == (1700.0, 1600.0)


async def test_live_fx_fetch_falls_back_when_guard_blocks(monkeypatch: pytest.MonkeyPatch):
    def blocking_guard(url: str, dns_resolver=None) -> str:
        raise SecuritySSRFViolationError("blocked")

    class FailingClient:
        async def get(self, url: str, **_kwargs):
            raise AssertionError("request must not be sent when the guard blocks it")

    monkeypatch.setattr(ssrf_guard, "validate_url_against_ssrf", blocking_guard)
    provider = next(
        obj
        for obj in vars(mdp).values()
        if isinstance(obj, type) and hasattr(obj, "fetch_live_fx_rates")
    )

    ccl, mep = await provider.fetch_live_fx_rates(FailingClient())

    assert (ccl, mep) == (1668.0, 1581.0)
