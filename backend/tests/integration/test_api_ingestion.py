"""
End-to-End Integration Test Suite for the Broker Report Ingestion Pipeline
(`POST /api/v1/ingestion/upload-report` — Module 6.3 Phase 3).

Exercises the complete Chapter 6 pipeline over `httpx.AsyncClient` and SQLite
in-memory persistence:
- Module 6.1: Format parsing (CSV / Excel multi-sheet) & fuzzy schema detection
- Module 6.2: Monetary normalization, ticker cleaning & invalid row isolation
- Module 6.3: Transactional portfolio reconciliation (`SNAPSHOT` & `MERGE`),
  RBAC (`TRADER`/`ADMIN` vs `VIEWER`), Anti-IDOR isolation, and DoS/ZipBomb/XXE
  perimeter protections under Universal Envelope (`APIResponse` / `APIErrorResponse`).
"""

from __future__ import annotations

import io
import unittest
import uuid
import zipfile
from decimal import Decimal

import app.models  # noqa: F401 - register all SQLAlchemy declarative models
import httpx
import openpyxl
import pytest
from app.api.deps import get_db, get_db_session
from app.core.database import Base
from app.core.security import create_access_token, get_password_hash
from app.domain.services.ingestion.base_parser import MAX_REPORT_SIZE_BYTES
from app.main import app as fastapi_app
from app.models.asset import AssetModel
from app.models.holding import HoldingModel
from app.models.portfolio import PortfolioModel
from app.models.user import UserModel
from app.schemas.user import UserRole
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


@pytest.mark.integration
class TestAPIIngestion(unittest.IsolatedAsyncioTestCase):
    """End-to-end integration tests for POST /api/v1/ingestion/upload-report."""

    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        self.SessionLocal = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        pw_hash = get_password_hash("TestIngestionPass!2026", rounds=4)

        self.trader_id = uuid.uuid4()
        self.other_trader_id = uuid.uuid4()
        self.viewer_id = uuid.uuid4()

        self.trader_user = UserModel(
            id=self.trader_id,
            email="trader.ingestion@investai.internal",
            hashed_password=pw_hash,
            full_name="Primary Trader",
            role=UserRole.TRADER,
            is_active=True,
        )
        self.other_trader_user = UserModel(
            id=self.other_trader_id,
            email="other.trader@investai.internal",
            hashed_password=pw_hash,
            full_name="Secondary Trader",
            role=UserRole.TRADER,
            is_active=True,
        )
        self.viewer_user = UserModel(
            id=self.viewer_id,
            email="viewer.ingestion@investai.internal",
            hashed_password=pw_hash,
            full_name="Read-Only Viewer",
            role=UserRole.VIEWER,
            is_active=True,
        )

        self.trader_portfolio_id = str(uuid.uuid4())
        self.other_portfolio_id = str(uuid.uuid4())

        trader_portfolio = PortfolioModel(
            id=self.trader_portfolio_id,
            user_id=str(self.trader_id),
            name="Cartera Balanz Trader",
            cash_balance_ars=250000.0,
            cash_balance_usd=1000.0,
        )
        other_portfolio = PortfolioModel(
            id=self.other_portfolio_id,
            user_id=str(self.other_trader_id),
            name="Cartera IOL Otro Trader",
            cash_balance_ars=100000.0,
            cash_balance_usd=0.0,
        )

        assets = [
            AssetModel(
                ticker="GGAL",
                name="Grupo Financiero Galicia",
                asset_type="EQUITY",
                currency="ARS",
                sector="FINANCIALS",
                market="BYMA",
            ),
            AssetModel(
                ticker="YPFD",
                name="YPF S.A.",
                asset_type="EQUITY",
                currency="ARS",
                sector="ENERGY",
                market="BYMA",
            ),
            AssetModel(
                ticker="PAMP",
                name="Pampa Energia",
                asset_type="EQUITY",
                currency="ARS",
                sector="UTILITIES",
                market="BYMA",
            ),
        ]

        holdings = [
            # Primary trader's initial 3 holdings
            HoldingModel(
                portfolio_id=self.trader_portfolio_id,
                asset_ticker="GGAL",
                quantity=100.0,
                average_buy_price=1200.0,
                current_price=1250.0,
            ),
            HoldingModel(
                portfolio_id=self.trader_portfolio_id,
                asset_ticker="YPFD",
                quantity=50.0,
                average_buy_price=20000.0,
                current_price=20500.0,
            ),
            HoldingModel(
                portfolio_id=self.trader_portfolio_id,
                asset_ticker="PAMP",
                quantity=200.0,
                average_buy_price=1500.0,
                current_price=1550.0,
            ),
            # Other trader's holding on shared PAMP asset
            HoldingModel(
                portfolio_id=self.other_portfolio_id,
                asset_ticker="PAMP",
                quantity=500.0,
                average_buy_price=1450.0,
                current_price=1550.0,
            ),
        ]

        async with self.SessionLocal() as session:
            session.add_all(
                [
                    self.trader_user,
                    self.other_trader_user,
                    self.viewer_user,
                    trader_portfolio,
                    other_portfolio,
                    *assets,
                    *holdings,
                ]
            )
            await session.commit()

        self.trader_token = create_access_token(
            subject=self.trader_id,
            role=UserRole.TRADER,
            email=self.trader_user.email,
        )
        self.viewer_token = create_access_token(
            subject=self.viewer_id,
            role=UserRole.VIEWER,
            email=self.viewer_user.email,
        )

        async def _override_get_db():
            async with self.SessionLocal() as session:
                try:
                    yield session
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise
                finally:
                    await session.close()

        fastapi_app.dependency_overrides[get_db] = _override_get_db
        fastapi_app.dependency_overrides[get_db_session] = _override_get_db

        self.transport = httpx.ASGITransport(app=fastapi_app)
        self.client = httpx.AsyncClient(transport=self.transport, base_url="http://testserver")

    async def asyncTearDown(self) -> None:
        if hasattr(self, "client") and self.client is not None:
            await self.client.aclose()
        fastapi_app.dependency_overrides.clear()
        if hasattr(self, "engine") and self.engine is not None:
            await self.engine.dispose()

    def _auth_headers(self, token: str | None = None) -> dict[str, str]:
        tok = token or self.trader_token
        return {"Authorization": f"Bearer {tok}"}

    async def test_upload_csv_alyc_snapshot_e2e_and_idempotent_reupload(self) -> None:
        """
        Verify E2E CSV upload (Balanz/IOL style with preamble, ';' delimiter,
        comma decimals, duplicate lots for GGAL, negative row for COME, and
        summary footer) reconciles the portfolio in SNAPSHOT mode and is
        100% idempotent upon immediate re-upload.
        """
        csv_content = (
            "Balanz Capital Valores S.A.U. - Estado de Cuenta\n"
            "Comitente: 987654 - Fecha: 20/10/2026\n"
            "\n"
            "Especie;Cantidad Disponible;Precio Promedio Compra;Moneda\n"
            "GGAL.BA;100;$ 1.200,00;Pesos\n"
            "GGAL;150;$ 1.500,00;ARS\n"
            "YPFD.BA;80;$ 21.000,00;ARS\n"
            "AL30.BA;1.000,00;$ 850,00;Pesos Argentinos\n"
            "COME;-15;$ 250,00;ARS\n"
            "Total Cartera ARS;;$ 15.000.000,00;ARS\n"
        ).encode("utf-8-sig")

        response = await self.client.post(
            "/api/v1/ingestion/upload-report",
            headers=self._auth_headers(),
            data={
                "portfolio_id": self.trader_portfolio_id,
                "mode": "SNAPSHOT",
            },
            files={
                "file": (
                    "../../fakepath/balanz_octubre.csv",
                    csv_content,
                    "text/csv; charset=utf-8",
                )
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("X-Request-ID", response.headers)
        self.assertIn("X-Execution-Time-Ms", response.headers)

        body = response.json()
        self.assertTrue(body["success"])
        data = body["data"]
        self.assertEqual(data["filename"], "balanz_octubre.csv")
        self.assertEqual(data["portfolio_id"], self.trader_portfolio_id)
        self.assertEqual(data["mode"], "SNAPSHOT")
        self.assertEqual(data["total_rows_parsed"], 5)
        self.assertEqual(data["valid_records_count"], 4)
        self.assertEqual(data["invalid_records_count"], 1)
        self.assertEqual(len(data["invalid_records"]), 1)
        self.assertEqual(data["invalid_records"][0]["raw_ticker"], "COME")

        rec = data["reconciliation"]
        self.assertEqual(rec["added_count"], 1)  # AL30
        self.assertEqual(rec["updated_count"], 2)  # GGAL (250 @ 1380), YPFD (80 @ 21000)
        self.assertEqual(rec["removed_count"], 1)  # PAMP removed from trader's portfolio
        self.assertEqual(rec["unchanged_count"], 0)
        self.assertEqual(rec["total_holdings_after"], 3)

        # Verify persisted DB state in an independent session
        async with self.SessionLocal() as verify_session:
            stmt_trader = select(HoldingModel).where(
                HoldingModel.portfolio_id == self.trader_portfolio_id
            )
            trader_holdings = {
                h.asset_ticker: h
                for h in (await verify_session.execute(stmt_trader)).scalars().all()
            }
            self.assertEqual(set(trader_holdings.keys()), {"GGAL", "YPFD", "AL30"})
            # GGAL: (100*1200 + 150*1500) / 250 = 1380.0
            self.assertAlmostEqual(trader_holdings["GGAL"].quantity, 250.0)
            self.assertAlmostEqual(trader_holdings["GGAL"].average_buy_price, 1380.0)
            self.assertAlmostEqual(trader_holdings["YPFD"].quantity, 80.0)
            self.assertAlmostEqual(trader_holdings["YPFD"].average_buy_price, 21000.0)
            self.assertAlmostEqual(trader_holdings["AL30"].quantity, 1000.0)
            self.assertAlmostEqual(trader_holdings["AL30"].average_buy_price, 850.0)

            # Verify other_trader_user's PAMP holding is completely untouched
            stmt_other = select(HoldingModel).where(
                HoldingModel.portfolio_id == self.other_portfolio_id
            )
            other_holdings = (await verify_session.execute(stmt_other)).scalars().all()
            self.assertEqual(len(other_holdings), 1)
            self.assertEqual(other_holdings[0].asset_ticker, "PAMP")
            self.assertAlmostEqual(other_holdings[0].quantity, 500.0)

        # Immediate re-upload of the consolidated state -> 100% idempotent (UNCHANGED)
        reupload_csv = (
            b"Ticker,Cantidad,PPC,Moneda\n"
            b"GGAL,250,1380.00,ARS\n"
            b"YPFD,80,21000.00,ARS\n"
            b"AL30,1000,850.00,ARS\n"
        )

        res_idem = await self.client.post(
            "/api/v1/ingestion/upload-report",
            headers=self._auth_headers(),
            data={
                "portfolio_id": self.trader_portfolio_id,
                "mode": "SNAPSHOT",
            },
            files={"file": ("consolidated.csv", reupload_csv, "text/csv")},
        )
        self.assertEqual(res_idem.status_code, 200, res_idem.text)
        rec_idem = res_idem.json()["data"]["reconciliation"]
        self.assertEqual(rec_idem["unchanged_count"], 3)
        self.assertEqual(rec_idem["added_count"], 0)
        self.assertEqual(rec_idem["updated_count"], 0)
        self.assertEqual(rec_idem["removed_count"], 0)
        self.assertEqual(rec_idem["total_holdings_after"], 3)

    async def test_upload_xlsx_multi_sheet_merge_mode_via_query_params(self) -> None:
        """
        Verify multi-sheet Excel (.xlsx) upload where Sheet 1 is a cover sheet
        ('Portada') and Sheet 2 ('Tenencias') holds the table, using query string
        parameters (?portfolio_id=...&mode=MERGE).
        """
        wb = openpyxl.Workbook()
        ws_cover = wb.active
        assert ws_cover is not None
        ws_cover.title = "Portada"
        ws_cover.append(["Reporte Institucional de Tenencias"])
        ws_cover.append(["Generado por Caja de Valores / PPI"])

        ws_holdings = wb.create_sheet(title="Tenencias")
        ws_holdings.append(["Símbolo", "Nominales", "P.P.C.", "Divisa"])
        ws_holdings.append(["BMA", 300, 6500.0, "ARS"])
        ws_holdings.append(["YPFD", 90, 22000.0, "ARS"])
        ws_holdings.append(["GD30", 500, None, "USD"])  # Missing price (Caja de Valores)

        buf = io.BytesIO()
        wb.save(buf)
        xlsx_bytes = buf.getvalue()
        wb.close()

        response = await self.client.post(
            f"/api/v1/ingestion/upload-report?portfolio_id={self.trader_portfolio_id}&mode=MERGE",
            headers=self._auth_headers(),
            files={
                "file": (
                    "ppi_tenencias.xlsx",
                    xlsx_bytes,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertEqual(data["mode"], "MERGE")
        self.assertEqual(data["total_rows_parsed"], 3)
        self.assertEqual(data["valid_records_count"], 3)
        self.assertEqual(data["invalid_records_count"], 0)

        rec = data["reconciliation"]
        self.assertEqual(rec["added_count"], 2)  # BMA, GD30
        self.assertEqual(rec["updated_count"], 1)  # YPFD (50 -> 90)
        self.assertEqual(rec["removed_count"], 0)  # GGAL and PAMP preserved in MERGE
        self.assertEqual(rec["total_holdings_after"], 5)

    async def test_upload_report_rbac_rejects_unauthenticated_401_and_viewer_403(
        self,
    ) -> None:
        """
        Verify unauthenticated requests receive 401 Unauthorized and VIEWER role
        requests receive 403 Forbidden wrapped in APIErrorResponse.
        """
        csv_bytes = b"Ticker,Cantidad,Precio\nGGAL,100,1500\n"

        # 1. Unauthenticated -> 401
        res_unauth = await self.client.post(
            "/api/v1/ingestion/upload-report",
            data={"portfolio_id": self.trader_portfolio_id},
            files={"file": ("report.csv", csv_bytes, "text/csv")},
        )
        self.assertEqual(res_unauth.status_code, 401)
        err_401 = res_unauth.json()
        self.assertFalse(err_401["success"])
        self.assertEqual(err_401["error"]["code"], "UNAUTHORIZED")

        # 2. VIEWER role -> 403
        res_viewer = await self.client.post(
            "/api/v1/ingestion/upload-report",
            headers=self._auth_headers(self.viewer_token),
            data={"portfolio_id": self.trader_portfolio_id},
            files={"file": ("report.csv", csv_bytes, "text/csv")},
        )
        self.assertEqual(res_viewer.status_code, 403)
        err_403 = res_viewer.json()
        self.assertFalse(err_403["success"])
        self.assertEqual(err_403["error"]["code"], "FORBIDDEN")

    async def test_upload_report_anti_idor_blocks_cross_tenant_portfolio_404(
        self,
    ) -> None:
        """
        Verify a TRADER attempting to upload a report into another user's
        portfolio receives 404 Not Found without modifying target holdings.
        """
        csv_bytes = b"Ticker,Cantidad,Precio\nGGAL,9999,1500\n"

        res = await self.client.post(
            "/api/v1/ingestion/upload-report",
            headers=self._auth_headers(self.trader_token),
            data={"portfolio_id": self.other_portfolio_id},
            files={"file": ("attack.csv", csv_bytes, "text/csv")},
        )
        self.assertEqual(res.status_code, 404)
        err = res.json()
        self.assertFalse(err["success"])
        self.assertEqual(err["error"]["code"], "NOT_FOUND")

        # Confirm other_trader_user's portfolio in DB was not modified
        async with self.SessionLocal() as session:
            stmt = select(HoldingModel).where(HoldingModel.portfolio_id == self.other_portfolio_id)
            rows = (await session.execute(stmt)).scalars().all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].asset_ticker, "PAMP")
            self.assertAlmostEqual(rows[0].quantity, 500.0)

    async def test_upload_report_rejects_invalid_extension_mime_and_malformed_params_422(
        self,
    ) -> None:
        """
        Verify perimeter validation rejects disallowed extensions, stemless filenames,
        prohibited MIME types, empty files, invalid mode, invalid allow_empty_snapshot,
        and missing or control-char portfolio_id with 422 Unprocessable Content.
        """
        valid_csv = b"Ticker,Cantidad\nGGAL,100\n"

        # Disallowed extensions (.pdf, .exe) and stemless filename ("../../.csv")
        for bad_name in ("tenencias.pdf", "malware.exe", "../../.csv", ".xlsx"):
            res = await self.client.post(
                "/api/v1/ingestion/upload-report",
                headers=self._auth_headers(),
                data={"portfolio_id": self.trader_portfolio_id},
                files={"file": (bad_name, valid_csv, "text/csv")},
            )
            self.assertEqual(res.status_code, 422, f"Expected 422 for {bad_name}")

        # Prohibited MIME type (application/pdf)
        res_mime = await self.client.post(
            "/api/v1/ingestion/upload-report",
            headers=self._auth_headers(),
            data={"portfolio_id": self.trader_portfolio_id},
            files={"file": ("tenencias.csv", valid_csv, "application/pdf")},
        )
        self.assertEqual(res_mime.status_code, 422)

        # Empty 0-byte file
        res_empty = await self.client.post(
            "/api/v1/ingestion/upload-report",
            headers=self._auth_headers(),
            data={"portfolio_id": self.trader_portfolio_id},
            files={"file": ("empty.csv", b"", "text/csv")},
        )
        self.assertEqual(res_empty.status_code, 422)

        # Invalid reconciliation mode
        res_mode = await self.client.post(
            "/api/v1/ingestion/upload-report",
            headers=self._auth_headers(),
            data={
                "portfolio_id": self.trader_portfolio_id,
                "mode": "INVALID_MODE",
            },
            files={"file": ("tenencias.csv", valid_csv, "text/csv")},
        )
        self.assertEqual(res_mode.status_code, 422)

        # Malformed allow_empty_snapshot boolean string
        res_bool = await self.client.post(
            "/api/v1/ingestion/upload-report",
            headers=self._auth_headers(),
            data={
                "portfolio_id": self.trader_portfolio_id,
                "allow_empty_snapshot": "not_a_bool",
            },
            files={"file": ("tenencias.csv", valid_csv, "text/csv")},
        )
        self.assertEqual(res_bool.status_code, 422)

        # Missing portfolio_id and portfolio_id with control char
        res_no_pid = await self.client.post(
            "/api/v1/ingestion/upload-report",
            headers=self._auth_headers(),
            files={"file": ("tenencias.csv", valid_csv, "text/csv")},
        )
        self.assertEqual(res_no_pid.status_code, 422)

        res_ctrl_pid = await self.client.post(
            "/api/v1/ingestion/upload-report?portfolio_id=bad%00id",
            headers=self._auth_headers(),
            files={"file": ("tenencias.csv", valid_csv, "text/csv")},
        )
        self.assertEqual(res_ctrl_pid.status_code, 422)

    async def test_upload_report_rejects_oversized_stream_and_xlsx_zip_bomb_413(
        self,
    ) -> None:
        """
        Verify HTTP 413 PAYLOAD_TOO_LARGE is returned both when:
        - Case A: Raw upload stream exceeds MAX_REPORT_SIZE_BYTES (10 MB + 1 byte).
        - Case B: Compressed .xlsx archive (< 2 KB) has a compression ratio > 100x
          (Anti-ZipBomb protection).
        """
        # Case A: Oversized raw stream
        oversized_bytes = b"A" * (MAX_REPORT_SIZE_BYTES + 1)
        res_oversize = await self.client.post(
            "/api/v1/ingestion/upload-report",
            headers=self._auth_headers(),
            data={"portfolio_id": self.trader_portfolio_id},
            files={"file": ("huge.csv", oversized_bytes, "text/csv")},
        )
        self.assertEqual(res_oversize.status_code, 413)
        self.assertEqual(res_oversize.json()["error"]["code"], "PAYLOAD_TOO_LARGE")

        # Case B: Tiny .xlsx Zip Bomb with > 100x compression ratio
        bomb_buf = io.BytesIO()
        with zipfile.ZipFile(bomb_buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            # 300 KB of repetitive XML compresses to < 1 KB (ratio > 300x > 100x limit)
            zf.writestr("xl/worksheets/sheet1.xml", "<row>" + ("0" * 300_000) + "</row>")
        bomb_bytes = bomb_buf.getvalue()
        self.assertLess(len(bomb_bytes), 2048)

        res_bomb = await self.client.post(
            "/api/v1/ingestion/upload-report",
            headers=self._auth_headers(),
            data={"portfolio_id": self.trader_portfolio_id},
            files={
                "file": (
                    "bomb.xlsx",
                    bomb_bytes,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
        self.assertEqual(res_bomb.status_code, 413)
        self.assertEqual(res_bomb.json()["error"]["code"], "PAYLOAD_TOO_LARGE")

    async def test_upload_report_all_invalid_rows_rolls_back_422_and_explicit_empty_snapshot_clears(
        self,
    ) -> None:
        """
        Verify:
        - Case A: A report where 100% of rows fail validation (e.g. negative/zero
          quantities) with allow_empty_snapshot='false' returns 422 and preserves
          all 3 initial holdings in the database.
        - Case B: Uploading the same report with allow_empty_snapshot='true' in
          SNAPSHOT mode succeeds (200 OK) and liquidates all 3 holdings (total_holdings_after=0).
        """
        all_invalid_csv = b"Ticker,Cantidad,Precio\nGGAL,-50,1200\nYPFD,0,20000\n"

        # Case A: allow_empty_snapshot="false" -> 422 & DB untouched
        res_reject = await self.client.post(
            "/api/v1/ingestion/upload-report",
            headers=self._auth_headers(),
            data={
                "portfolio_id": self.trader_portfolio_id,
                "mode": "SNAPSHOT",
                "allow_empty_snapshot": "false",
            },
            files={"file": ("invalid_rows.csv", all_invalid_csv, "text/csv")},
        )
        self.assertEqual(res_reject.status_code, 422)

        async with self.SessionLocal() as session:
            stmt = select(HoldingModel).where(HoldingModel.portfolio_id == self.trader_portfolio_id)
            holdings_before = (await session.execute(stmt)).scalars().all()
            self.assertEqual(len(holdings_before), 3)

        # Case B: allow_empty_snapshot="true" -> 200 OK & clears portfolio
        res_clear = await self.client.post(
            "/api/v1/ingestion/upload-report",
            headers=self._auth_headers(),
            data={
                "portfolio_id": self.trader_portfolio_id,
                "mode": "SNAPSHOT",
                "allow_empty_snapshot": "true",
            },
            files={"file": ("invalid_rows.csv", all_invalid_csv, "text/csv")},
        )
        self.assertEqual(res_clear.status_code, 200, res_clear.text)
        data = res_clear.json()["data"]
        self.assertEqual(data["valid_records_count"], 0)
        self.assertEqual(data["invalid_records_count"], 2)
        self.assertEqual(data["reconciliation"]["removed_count"], 3)
        self.assertEqual(data["reconciliation"]["total_holdings_after"], 0)

        async with self.SessionLocal() as session:
            stmt = select(HoldingModel).where(HoldingModel.portfolio_id == self.trader_portfolio_id)
            holdings_after = (await session.execute(stmt)).scalars().all()
            self.assertEqual(len(holdings_after), 0)

    async def test_upload_report_corrupted_binary_missing_columns_and_xxe_422(
        self,
    ) -> None:
        """
        Verify missing required columns, null-byte binary corruption, and XXE
        entity declarations inside .xlsx XML streams all return HTTP 422.
        """
        # 1. Missing required columns
        missing_cols_csv = b"Fecha,Descripcion,Importe\n20/10/2026,Compra,15000\n"
        res_cols = await self.client.post(
            "/api/v1/ingestion/upload-report",
            headers=self._auth_headers(),
            data={"portfolio_id": self.trader_portfolio_id},
            files={"file": ("no_cols.csv", missing_cols_csv, "text/csv")},
        )
        self.assertEqual(res_cols.status_code, 422)

        # 2. Null-byte corrupted CSV
        null_csv = b"Ticker,Cantidad\nGGAL\x00,100\n"
        res_null = await self.client.post(
            "/api/v1/ingestion/upload-report",
            headers=self._auth_headers(),
            data={"portfolio_id": self.trader_portfolio_id},
            files={"file": ("corrupt.csv", null_csv, "text/csv")},
        )
        self.assertEqual(res_null.status_code, 422)

        # 3. XXE payload inside .xlsx zip entry
        xxe_buf = io.BytesIO()
        with zipfile.ZipFile(xxe_buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                "[Content_Types].xml",
                '<?xml version="1.0"?><!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><Types/>',
            )
        res_xxe = await self.client.post(
            "/api/v1/ingestion/upload-report",
            headers=self._auth_headers(),
            data={"portfolio_id": self.trader_portfolio_id},
            files={
                "file": (
                    "xxe.xlsx",
                    xxe_buf.getvalue(),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
        self.assertEqual(res_xxe.status_code, 422)

    async def test_upload_legacy_xls_binary_handled_gracefully_422(self) -> None:
        """
        Verify uploading a legacy binary BIFF8/OLE2 .xls file returns a clean
        422 Unprocessable Content response instead of an unhandled 500 error.
        """
        ole2_xls_bytes = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + (b"\x00" * 128)
        res = await self.client.post(
            "/api/v1/ingestion/upload-report",
            headers=self._auth_headers(),
            data={"portfolio_id": self.trader_portfolio_id},
            files={
                "file": (
                    "legacy_extracto.xls",
                    ole2_xls_bytes,
                    "application/vnd.ms-excel",
                )
            },
        )
        self.assertEqual(res.status_code, 422)
        err = res.json()
        self.assertFalse(err["success"])
        self.assertEqual(err["error"]["code"], "VALIDATION_ERROR")

    async def test_upload_report_adversarial_sub_pip_non_xlsx_zip_and_entry_bomb(
        self,
    ) -> None:
        """
        Verify E2E adversarial protections across Chapter 6:
        1. Sub-pip quantity ('0,00004') is isolated as ZERO_QUANTITY while a row with
           sub-pip average price ('0,00004') reconciles cleanly (200 OK) with avg_price=None.
        2. A valid .zip without OOXML workbook structure uploaded as 'cartera.xlsx'
           returns HTTP 422.
        3. An .xlsx with lowercase '<!entity' returns HTTP 422.
        4. An .xlsx exceeding MAX_ZIP_ENTRIES (501 entries) returns HTTP 413.
        """
        # 1. Sub-pip quantity and sub-pip average price + formula prefix '- =AL30.BA'
        sub_pip_csv = (
            b"Ticker;Cantidad;PPC;Moneda\n"
            b"SPY;0,00004;500,00;USD\n"
            b"- =AL30.BA;200;0,00004;ARS\n"
            b"AL30;300;850,00;ARS\n"
        )
        res_sub_pip = await self.client.post(
            "/api/v1/ingestion/upload-report",
            headers=self._auth_headers(),
            data={"portfolio_id": self.trader_portfolio_id, "mode": "MERGE"},
            files={"file": ("sub_pip.csv", sub_pip_csv, "text/csv")},
        )
        self.assertEqual(res_sub_pip.status_code, 200, res_sub_pip.text)
        payload = res_sub_pip.json()["data"]
        self.assertEqual(payload["valid_records_count"], 2)
        self.assertEqual(payload["invalid_records_count"], 1)
        self.assertEqual(payload["invalid_records"][0]["error_code"], "ZERO_QUANTITY")
        self.assertEqual(payload["reconciliation"]["added_count"], 1)
        self.assertEqual(payload["reconciliation"]["events"][0]["ticker"], "AL30")
        self.assertEqual(
            Decimal(str(payload["reconciliation"]["events"][0]["new_quantity"])),
            Decimal("500.0000"),
        )

        # 2. Valid .zip lacking OOXML structure renamed to cartera.xlsx -> 422
        plain_zip = io.BytesIO()
        with zipfile.ZipFile(plain_zip, mode="w") as zf:
            zf.writestr("readme.txt", "Plain zip without workbook.xml")
        res_plain_zip = await self.client.post(
            "/api/v1/ingestion/upload-report",
            headers=self._auth_headers(),
            data={"portfolio_id": self.trader_portfolio_id},
            files={
                "file": (
                    "cartera.xlsx",
                    plain_zip.getvalue(),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
        self.assertEqual(res_plain_zip.status_code, 422)

        # 3. Lowercase <!entity inside .xlsx -> 422
        lower_xxe_zip = io.BytesIO()
        with zipfile.ZipFile(lower_xxe_zip, mode="w") as zf:
            zf.writestr(
                "[Content_Types].xml",
                '<?xml version="1.0"?><!doctype foo [<!entity xxe SYSTEM "file:///etc/passwd">]><Types/>',
            )
        res_lower_xxe = await self.client.post(
            "/api/v1/ingestion/upload-report",
            headers=self._auth_headers(),
            data={"portfolio_id": self.trader_portfolio_id},
            files={
                "file": (
                    "lower_xxe.xlsx",
                    lower_xxe_zip.getvalue(),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
        self.assertEqual(res_lower_xxe.status_code, 422)

        # 4. Entry-Bomb (> 500 entries) inside .xlsx -> 413
        entry_bomb_zip = io.BytesIO()
        with zipfile.ZipFile(entry_bomb_zip, mode="w") as zf:
            for idx in range(501):
                zf.writestr(f"xl/entry_{idx}.txt", "x")
        res_entry_bomb = await self.client.post(
            "/api/v1/ingestion/upload-report",
            headers=self._auth_headers(),
            data={"portfolio_id": self.trader_portfolio_id},
            files={
                "file": (
                    "entry_bomb.xlsx",
                    entry_bomb_zip.getvalue(),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
        self.assertEqual(res_entry_bomb.status_code, 413)
        self.assertEqual(res_entry_bomb.json()["error"]["code"], "PAYLOAD_TOO_LARGE")
