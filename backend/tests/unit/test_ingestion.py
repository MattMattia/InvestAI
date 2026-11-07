import io
import unittest

import pandas as pd
from app.domain.models.asset import AssetType, Currency
from app.schemas.ingestion import IngestionBatchPayload, RawHoldingRecord
from app.services.parsers.universal_parser import UniversalHoldingParser
from pydantic import ValidationError


class TestIngestionSchemasAndParser(unittest.TestCase):
    def test_raw_holding_record_valid_and_sanitized(self):
        record = RawHoldingRecord(
            ticker="  aapl  ",
            quantity=15.0,
            purchase_price=1200.50,
            current_price=1350.00,
            currency="  ars  ",
            market="bcba",
            asset_type="cedear",
        )
        self.assertEqual(record.ticker, "AAPL")
        self.assertEqual(record.currency, "ARS")
        self.assertEqual(record.quantity, 15.0)
        self.assertEqual(record.purchase_price, 1200.50)
        self.assertEqual(record.current_price, 1350.00)

    def test_raw_holding_record_rejection_negative_quantity(self):
        with self.assertRaises(ValidationError) as ctx:
            RawHoldingRecord(ticker="AAPL", quantity=-5.0, purchase_price=100.0)
        self.assertIn("estrictamente positiva", str(ctx.exception))

        with self.assertRaises(ValidationError) as ctx_zero:
            RawHoldingRecord(ticker="AAPL", quantity=0.0, purchase_price=100.0)
        self.assertIn("estrictamente positiva", str(ctx_zero.exception))

    def test_raw_holding_record_rejection_negative_price(self):
        with self.assertRaises(ValidationError) as ctx:
            RawHoldingRecord(ticker="AAPL", quantity=10.0, purchase_price=-10.0)
        self.assertIn("El precio no puede ser negativo", str(ctx.exception))

    def test_raw_holding_record_rejection_nan_inf(self):
        with self.assertRaises(ValidationError):
            RawHoldingRecord(ticker="AAPL", quantity=float("nan"), purchase_price=100.0)
        with self.assertRaises(ValidationError):
            RawHoldingRecord(ticker="AAPL", quantity=float("inf"), purchase_price=100.0)
        with self.assertRaises(ValidationError):
            RawHoldingRecord(ticker="AAPL", quantity=10.0, purchase_price=float("nan"))

    def test_raw_holding_record_rejection_empty_ticker(self):
        with self.assertRaises(ValidationError) as ctx:
            RawHoldingRecord(ticker="   ", quantity=10.0)
        self.assertIn("no puede ser una cadena vacía", str(ctx.exception))

    def test_ingestion_batch_payload_validation(self):
        rec = RawHoldingRecord(ticker="AAPL", quantity=10.0, purchase_price=100.0)
        payload = IngestionBatchPayload(
            user_id="user_123",
            portfolio_name="Mi Cartera Principal",
            records=[rec],
            implicit_fx_rate=1350.0,
        )
        self.assertEqual(payload.user_id, "user_123")
        self.assertEqual(len(payload.records), 1)

        with self.assertRaises(ValidationError):
            IngestionBatchPayload(
                user_id="user_123",
                portfolio_name="Port",
                records=[rec],
                implicit_fx_rate=-10.0,
            )

    def test_csv_parsing_standard_headers(self):
        csv_content = (
            "Especie,Cantidad,Precio Compra,Precio Actual,Moneda\n"
            "AAPL,10,1200.50,1350.00,ARS\n"
            "AL30,500,280.00,320.00,ARS\n"
            "MSFT,5,2500.00,2700.00,USD\n"
        )
        parser = UniversalHoldingParser()
        report = parser.parse(csv_content.encode("utf-8"))

        self.assertEqual(report.total_rows, 3)
        self.assertEqual(report.valid_records_count, 3)
        self.assertEqual(report.discarded_records_count, 0)
        self.assertTrue(report.is_successful)

        holdings = report.holdings
        self.assertEqual(len(holdings), 3)

        aapl_h = holdings[0]
        self.assertEqual(aapl_h.asset.ticker, "AAPL")
        self.assertEqual(aapl_h.asset.asset_type, AssetType.CEDEAR)
        self.assertEqual(aapl_h.quantity, 10.0)
        self.assertEqual(aapl_h.average_buy_price, 1200.50)
        self.assertEqual(aapl_h.currency, Currency.ARS)

        al30_h = holdings[1]
        self.assertEqual(al30_h.asset.ticker, "AL30")
        self.assertEqual(al30_h.asset.asset_type, AssetType.BOND_SOVEREIGN)
        self.assertEqual(al30_h.quantity, 500.0)

        msft_h = holdings[2]
        self.assertEqual(msft_h.asset.currency, Currency.USD)

    def test_csv_semicolon_and_latin_decimals(self):
        csv_content = (
            "Simbolo;Nominales;Precio_Promedio;Cotizacion;Divisa\n"
            "GGAL;100;1.850,50;2.100,00;ARS\n"
            "YPFD;50;15.200,00;16.400,00;ARS\n"
        )
        parser = UniversalHoldingParser()
        report = parser.parse(csv_content.encode("utf-8"))

        self.assertEqual(report.valid_records_count, 2)
        self.assertEqual(report.discarded_records_count, 0)
        self.assertEqual(report.holdings[0].average_buy_price, 1850.50)
        self.assertEqual(report.holdings[0].current_price, 2100.00)
        self.assertEqual(report.holdings[1].average_buy_price, 15200.00)

    def test_excel_buffer_parsing(self):
        df = pd.DataFrame(
            {
                "Ticker": ["KO", "GD30"],
                "Nominales": [20, 1000],
                "Costo": [850.0, 310.0],
                "Precio Mercado": [920.0, 345.0],
                "Moneda": ["ARS", "USD"],
            }
        )
        buffer = io.BytesIO()
        df.to_excel(buffer, index=False, engine="openpyxl")
        excel_bytes = buffer.getvalue()

        parser = UniversalHoldingParser()
        report = parser.parse(excel_bytes, file_format="xlsx")

        self.assertEqual(report.total_rows, 2)
        self.assertEqual(report.valid_records_count, 2)
        self.assertEqual(report.holdings[0].asset.ticker, "KO")
        self.assertEqual(report.holdings[0].asset.asset_type, AssetType.CEDEAR)
        self.assertEqual(report.holdings[1].asset.ticker, "GD30")
        self.assertEqual(report.holdings[1].asset.asset_type, AssetType.BOND_SOVEREIGN)

    def test_custom_column_mapping_override(self):
        csv_content = "Columna_Cod,Columna_Q,Columna_P\nAAPL,10,1200\n"
        custom_map = {
            "ticker": "Columna_Cod",
            "quantity": "Columna_Q",
            "purchase_price": "Columna_P",
        }
        parser = UniversalHoldingParser(column_mapping=custom_map)
        report = parser.parse(csv_content.encode("utf-8"))

        self.assertEqual(report.valid_records_count, 1)
        self.assertEqual(report.holdings[0].asset.ticker, "AAPL")
        self.assertEqual(report.holdings[0].quantity, 10.0)

    def test_resilience_to_corrupt_rows(self):
        csv_content = (
            "Ticker,Cantidad,Precio\n"
            "AAPL,10,1000\n"
            "MSFT,-5,1500\n"
            ",20,500\n"
            "AL30,100,300\n"
            "GOOGL,invalido,2000\n"
        )
        parser = UniversalHoldingParser()
        report = parser.parse(csv_content.encode("utf-8"))

        self.assertEqual(report.total_rows, 5)
        self.assertEqual(report.valid_records_count, 2)
        self.assertEqual(report.discarded_records_count, 3)
        self.assertTrue(report.has_partial_errors)
        self.assertFalse(report.is_successful)

        self.assertEqual(len(report.errors), 3)
        tickers = [h.asset.ticker for h in report.holdings]
        self.assertIn("AAPL", tickers)
        self.assertIn("AL30", tickers)

    def test_missing_mandatory_columns_error(self):
        csv_content = "Descripcion,Comentario\nFila 1,Sin ticker ni cantidad\n"
        parser = UniversalHoldingParser()
        report = parser.parse(csv_content.encode("utf-8"))

        self.assertEqual(report.valid_records_count, 0)
        self.assertEqual(report.discarded_records_count, 1)
        self.assertEqual(len(report.errors), 1)
        self.assertEqual(report.errors[0]["error_type"], "MAPPING_ERROR")


if __name__ == "__main__":
    unittest.main()
