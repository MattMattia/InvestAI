"""
Unit test suite for Module 6.1 Phase 1: Abstract Report Parser Interface
and Format Strategies (CSV / Excel).
"""
from __future__ import annotations

from decimal import Decimal
import io
import unittest
from unittest.mock import patch
import zipfile

import openpyxl
from pydantic import ValidationError
import pytest

from app.domain.services.ingestion import (
    MAX_COLUMNS_TO_SCAN,
    MAX_REPORT_SIZE_BYTES,
    CSVReportParser,
    CanonicalReportField,
    CorruptedReportError,
    EmptyReportError,
    ExcelReportParser,
    MissingRequiredColumnsError,
    RawHoldingRecord,
    ReportSizeLimitExceededError,
    SchemaDetector,
    UnsupportedReportFormatError,
    get_report_parser,
)


def _build_xlsx_bytes(sheets: dict[str, list[list[object]]]) -> bytes:
    """Create an in-memory .xlsx file from a mapping of sheet_name -> rows."""
    wb = openpyxl.Workbook()
    default_sheet = wb.active
    for idx, (sheet_name, rows) in enumerate(sheets.items()):
        if idx == 0 and default_sheet is not None:
            ws = default_sheet
            ws.title = sheet_name
        else:
            ws = wb.create_sheet(title=sheet_name)
        for row in rows:
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    wb.close()
    return buf.getvalue()


@pytest.mark.unit
class TestReportParsers(unittest.IsolatedAsyncioTestCase):
    """Comprehensive unit and adversarial tests for CSV and Excel report parsers."""

    async def test_csv_parser_standard_comma_delimited(self) -> None:
        """Verify standard UTF-8 comma-delimited CSV parsing and raw field mapping."""
        csv_content = (
            "symbol,quantity,avg_price,currency,market_value\n"
            "GGAL,1500,4250.50,ARS,6375750.00\n"
            "AAPL,25,185.20,USD,4630.00\n"
            "Total,1525,,,6380380.00\n"
        ).encode("utf-8")

        parser = CSVReportParser()
        records = await parser.parse_report(csv_content, "holdings_report.csv")

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].row_number, 2)
        self.assertEqual(records[0].raw_ticker, "GGAL")
        self.assertEqual(records[0].raw_quantity, "1500")
        self.assertEqual(records[0].raw_avg_price, "4250.50")
        self.assertEqual(records[0].raw_currency, "ARS")
        self.assertEqual(records[0].raw_fields["market_value"], "6375750.00")

        self.assertEqual(records[1].row_number, 3)
        self.assertEqual(records[1].raw_ticker, "AAPL")
        self.assertEqual(records[1].raw_quantity, "25")
        self.assertEqual(records[1].raw_avg_price, "185.20")
        self.assertEqual(records[1].raw_currency, "USD")

    async def test_csv_parser_argentine_alyc_semicolon_and_cp1252(self) -> None:
        """
        Verify Argentine ALyC statement with CP1252 encoding, diacritics,
        metadata preamble rows, semicolon delimiter, and summary footers.
        """
        alyc_text = (
            "Balanz Capital Valores S.A.U. - Estado de Cuenta\n"
            "Comitente: 987654 - Fecha de Emisión: 17/10/2026\n"
            "\n"
            "Símbolo;Tenencia;Precio Promedio;Moneda de Liquidación;Descripción\n"
            "AL30;10.000,00;68.450,25;ARS;Bono Rep. Argentina Step Up 2030\n"
            "YPFD;250;31.200,00;ARS;YPF S.A. Ordinarias Clase D\n"
            "  ;  ;  ;  ;  \n"
            "Total Cartera;10.250,00;;;---\n"
        )
        cp1252_stream = alyc_text.encode("cp1252")

        parser = CSVReportParser()
        records = await parser.parse_report(cp1252_stream, "Tenencia_Balanz.CSV")

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].row_number, 5)
        self.assertEqual(records[0].raw_ticker, "AL30")
        self.assertEqual(records[0].raw_quantity, "10.000,00")
        self.assertEqual(records[0].raw_avg_price, "68.450,25")
        self.assertEqual(records[0].raw_currency, "ARS")
        self.assertEqual(
            records[0].raw_fields["Descripción"],
            "Bono Rep. Argentina Step Up 2030",
        )

        self.assertEqual(records[1].row_number, 6)
        self.assertEqual(records[1].raw_ticker, "YPFD")
        self.assertEqual(records[1].raw_quantity, "250")

    async def test_excel_parser_read_only_and_multi_sheet_discovery(self) -> None:
        """
        Verify multi-sheet Excel discovery skipping cover sheets without headers,
        extracting clean Decimal values free of IEEE-754 float noise, and ignoring footers.
        """
        xlsx_bytes = _build_xlsx_bytes(
            {
                "Portada": [
                    ["Reporte Consolidado de Inversiones"],
                    ["Generado automáticamente - Uso Interno"],
                ],
                "Tenencias_ALyC": [
                    ["Cliente:", "Mattia Risso"],
                    [None, None, None, None],
                    ["Especie", "Nominales", "PPC", "Moneda"],
                    ["GD30", 5000, 100.55, "USD"],
                    ["PAMP", 120.5, 2450.10, "ARS"],
                    [None, None, None, None],
                    ["Subtotal:", 5120.5, None, None],
                ],
            }
        )

        parser = ExcelReportParser()
        records = await parser.parse_report(xlsx_bytes, "cartera_mensual.xlsx")

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].row_number, 4)
        self.assertEqual(records[0].raw_ticker, "GD30")
        self.assertEqual(records[0].raw_quantity, 5000)
        self.assertEqual(records[0].raw_avg_price, Decimal("100.55"))
        self.assertEqual(records[0].raw_currency, "USD")

        self.assertEqual(records[1].row_number, 5)
        self.assertEqual(records[1].raw_ticker, "PAMP")
        self.assertEqual(records[1].raw_quantity, Decimal("120.5"))
        self.assertEqual(records[1].raw_avg_price, Decimal("2450.1"))
        self.assertEqual(records[1].raw_currency, "ARS")

    async def test_formula_injection_sanitization(self) -> None:
        """
        Verify CWE-1236 Formula Injection mitigation on raw_ticker and raw_currency
        across both CSVReportParser and RawHoldingRecord direct construction.
        """
        csv_payload = (
            "Ticker,Cantidad,Precio,Moneda\n"
            "=GGAL,100,1200,=ARS\n"
            "+YPFD,50,25000,+USD\n"
            "-PAMP,75,1800,-MEP\n"
            "@ALUA,200,950,@CCL\n"
            "\"=CMD|' /C calc'!A0\",10,100,\"=++==\"\n"
        ).encode("utf-8")

        parser = CSVReportParser()
        records = await parser.parse_report(csv_payload, "adversarial.csv")

        self.assertEqual(len(records), 5)
        self.assertEqual(records[0].raw_ticker, "GGAL")
        self.assertEqual(records[0].raw_currency, "ARS")
        self.assertEqual(records[1].raw_ticker, "YPFD")
        self.assertEqual(records[1].raw_currency, "USD")
        self.assertEqual(records[2].raw_ticker, "PAMP")
        self.assertEqual(records[2].raw_currency, "MEP")
        self.assertEqual(records[3].raw_ticker, "ALUA")
        self.assertEqual(records[3].raw_currency, "CCL")
        self.assertFalse(records[4].raw_ticker.startswith(("=", "+", "-", "@")))
        self.assertIsNone(records[4].raw_currency)

        with self.assertRaises(ValidationError):
            RawHoldingRecord(
                row_number=1,
                raw_ticker="===+++---@@@",
                raw_quantity=100,
            )

    async def test_csv_null_bytes_and_binary_spoofing_rejected(self) -> None:
        """
        Verify CSVReportParser rejects streams with null bytes or ZIP/OLE2 binary signatures.
        """
        parser = CSVReportParser()

        with self.assertRaises(CorruptedReportError):
            await parser.parse_report(
                b"Ticker,Cantidad\nGGAL\x00,100\n", "null_injected.csv"
            )

        xlsx_stream = _build_xlsx_bytes(
            {"Sheet1": [["Ticker", "Cantidad"], ["GGAL", 100]]}
        )
        with self.assertRaises(CorruptedReportError):
            await parser.parse_report(xlsx_stream, "renamed_excel.csv")

        ole2_stream = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"fake_xls_content"
        with self.assertRaises(CorruptedReportError):
            await parser.parse_report(ole2_stream, "legacy_xls_spoofed.csv")

        with self.assertRaises(CorruptedReportError):
            await parser.parse_report(b"Ticker,Cantidad\nGGAL,100", "bad\x00name.csv")

    async def test_excel_corrupted_zip_bomb_and_xxe_rejected(self) -> None:
        """
        Verify ExcelReportParser blocks corrupted archives, VBA macros, XXE/DOCTYPE payloads,
        and excessive compression ratios (Zip-Bomb defense).
        """
        parser = ExcelReportParser()

        # 1. Non-zip random bytes masquerading as .xlsx
        with self.assertRaises(CorruptedReportError):
            await parser.parse_report(b"not_a_zip_archive_at_all", "corrupted.xlsx")

        # 2. VBA macro injection (vbaProject.bin)
        macro_buf = io.BytesIO()
        with zipfile.ZipFile(macro_buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("xl/vbaProject.bin", b"malicious_vba_macro_stream")
        with self.assertRaises(CorruptedReportError):
            await parser.parse_report(macro_buf.getvalue(), "macro_payload.xlsx")

        # 3. XML External Entity (XXE / DOCTYPE) injection inside XML entry
        xxe_buf = io.BytesIO()
        with zipfile.ZipFile(xxe_buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                "[Content_Types].xml",
                b'<?xml version="1.0"?>\n<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>\n<Types/>',
            )
        with self.assertRaises(CorruptedReportError):
            await parser.parse_report(xxe_buf.getvalue(), "xxe_attack.xlsx")

        # 4. Zip-Bomb compression ratio violation (> 100:1)
        bomb_buf = io.BytesIO()
        with zipfile.ZipFile(bomb_buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("xl/worksheets/sheet1.xml", b"A" * (500 * 1024))
        with self.assertRaises(ReportSizeLimitExceededError):
            await parser.parse_report(bomb_buf.getvalue(), "zip_bomb.xlsx")

    async def test_missing_required_columns_raises_error(self) -> None:
        """
        Verify MissingRequiredColumnsError is raised when required columns
        ('ticker', 'quantity') are absent in both CSV and Excel reports.
        """
        csv_parser = CSVReportParser()
        invalid_csv = b"Fecha,Descripcion,Importe\n2026-10-17,Compra,150000\n"
        with self.assertRaises(MissingRequiredColumnsError):
            await csv_parser.parse_report(invalid_csv, "movimientos.csv")

        excel_parser = ExcelReportParser()
        invalid_xlsx = _build_xlsx_bytes(
            {
                "Movimientos": [
                    ["Fecha", "Concepto", "Monto"],
                    ["2026-10-17", "Suscripción FCI", 500000],
                ]
            }
        )
        with self.assertRaises(MissingRequiredColumnsError):
            await excel_parser.parse_report(invalid_xlsx, "movimientos.xlsx")

    async def test_empty_stream_and_headers_only_raise_empty_error(self) -> None:
        """
        Verify EmptyReportError is raised for 0-byte streams, whitespace-only files,
        and files containing valid headers but 0 valid data rows.
        """
        csv_parser = CSVReportParser()
        excel_parser = ExcelReportParser()

        with self.assertRaises(EmptyReportError):
            await csv_parser.parse_report(b"", "empty.csv")

        with self.assertRaises(EmptyReportError):
            await csv_parser.parse_report(b"   \n  \r\n ", "whitespace.csv")

        with self.assertRaises(EmptyReportError):
            await csv_parser.parse_report(
                b"Ticker,Cantidad,Precio\nTotal,0,0\n", "headers_only.csv"
            )

        with self.assertRaises(EmptyReportError):
            await excel_parser.parse_report(b"", "empty.xlsx")

        blank_xlsx = _build_xlsx_bytes({"Hoja1": [[None, None], ["  ", ""]]})
        with self.assertRaises(EmptyReportError):
            await excel_parser.parse_report(blank_xlsx, "blank.xlsx")

        headers_only_xlsx = _build_xlsx_bytes(
            {
                "Hoja1": [
                    ["Ticker", "Cantidad", "Precio"],
                    ["Total Cartera", 1000, None],
                ]
            }
        )
        with self.assertRaises(EmptyReportError):
            await excel_parser.parse_report(headers_only_xlsx, "headers_only.xlsx")

    async def test_unsupported_extension_raises_error(self) -> None:
        """
        Verify UnsupportedReportFormatError is raised for .xls, .xlsm, .pdf, .exe,
        missing extensions, or mismatched parser extensions.
        """
        for bad_name in ("legacy.xls", "macros.xlsm", "statement.pdf", "script.exe", "noext", "   "):
            with self.assertRaises(UnsupportedReportFormatError):
                get_report_parser(bad_name)

        csv_parser = CSVReportParser()
        with self.assertRaises(UnsupportedReportFormatError):
            await csv_parser.parse_report(b"Ticker,Cantidad\nGGAL,10\n", "wrong.txt")

        excel_parser = ExcelReportParser()
        with self.assertRaises(UnsupportedReportFormatError):
            await excel_parser.parse_report(b"PK\x03\x04...", "legacy.xls")
        with self.assertRaises(UnsupportedReportFormatError):
            await excel_parser.parse_report(b"PK\x03\x04...", "macro.xlsm")

    async def test_factory_resolution_and_size_limits(self) -> None:
        """
        Verify get_report_parser returns the expected strategy and enforces size/row limits.
        """
        self.assertIsInstance(get_report_parser("PORTFOLIO.CSV"), CSVReportParser)
        self.assertIsInstance(get_report_parser("Tenencias.Xlsx"), ExcelReportParser)

        csv_parser = CSVReportParser()
        oversized = b"a" * (MAX_REPORT_SIZE_BYTES + 1)
        with self.assertRaises(ReportSizeLimitExceededError):
            await csv_parser.parse_report(oversized, "huge.csv")

        small_csv = b"Ticker,Cantidad\nGGAL,10\nYPFD,20\n"
        with patch("app.domain.services.ingestion.csv_parser.MAX_REPORT_ROWS", 1):
            with self.assertRaises(ReportSizeLimitExceededError):
                await csv_parser.parse_report(small_csv, "too_many_rows.csv")

    async def test_schema_detector_exact_and_synonym_matching(self) -> None:
        """
        Verify exact and synonym mapping across Argentine ALyC layouts
        (Balanz, IOL, PPI, Bull Market, Caja de Valores).
        """
        detector = SchemaDetector()

        # Balanz layout
        balanz_headers = [
            "Especie",
            "Tenencia",
            "Precio Promedio de Compra",
            "Moneda de Liquidación",
            "Saldo Valorizado",
        ]
        res_balanz = detector.detect_schema(balanz_headers)
        self.assertTrue(res_balanz.has_required_fields())
        self.assertEqual(res_balanz.get_column_index(CanonicalReportField.TICKER), 0)
        self.assertEqual(res_balanz.get_column_index(CanonicalReportField.QUANTITY), 1)
        self.assertEqual(res_balanz.get_column_index(CanonicalReportField.AVG_PRICE), 2)
        self.assertEqual(res_balanz.get_column_index(CanonicalReportField.CURRENCY), 3)
        self.assertEqual(
            res_balanz.get_column_index(CanonicalReportField.TOTAL_AMOUNT), 4
        )
        self.assertAlmostEqual(res_balanz.total_confidence, 5.0, places=4)

        # IOL / PPI / Caja de Valores layout
        ppi_headers = [
            "Instrumento",
            "Cantidad Disponible",
            "PPC",
            "Divisa",
            "Valuación Actual",
        ]
        res_ppi = detector.detect_schema(ppi_headers)
        self.assertTrue(res_ppi.has_required_fields())
        self.assertEqual(res_ppi.get_column_index(CanonicalReportField.TICKER), 0)
        self.assertEqual(res_ppi.get_column_index(CanonicalReportField.QUANTITY), 1)
        self.assertEqual(res_ppi.get_column_index(CanonicalReportField.AVG_PRICE), 2)
        self.assertEqual(res_ppi.get_column_index(CanonicalReportField.CURRENCY), 3)
        self.assertEqual(res_ppi.get_column_index(CanonicalReportField.TOTAL_AMOUNT), 4)

    async def test_schema_detector_fuzzy_matching_typos_and_abbreviations(self) -> None:
        """
        Verify fuzzy matching and normalization handle abbreviations, punctuation,
        diacritics, and minor typos.
        """
        detector = SchemaDetector()
        noisy_headers = [
            "Espécïe / Símbolo",
            "Cant. Nominales",
            "Prec. Prom. Compra",
            "Moneda Liq.",
            "Valuación Actual",
        ]
        res = detector.detect_schema(noisy_headers)
        self.assertTrue(res.has_required_fields())
        self.assertEqual(res.get_column_index(CanonicalReportField.TICKER), 0)
        self.assertEqual(res.get_column_index(CanonicalReportField.QUANTITY), 1)
        self.assertEqual(res.get_column_index(CanonicalReportField.AVG_PRICE), 2)
        self.assertEqual(res.get_column_index(CanonicalReportField.CURRENCY), 3)
        self.assertEqual(res.get_column_index(CanonicalReportField.TOTAL_AMOUNT), 4)

        # Also verify typo tolerance via SequenceMatcher and end-to-end CSV parsing
        typo_csv = (
            "Simblo;Cantidadd;Precio Promdio;Moneda Orign;Valuasion Actual\n"
            "GGAL;500;4100,00;ARS;2050000,00\n"
        ).encode("utf-8")
        records = await CSVReportParser().parse_report(typo_csv, "typo_alyc.csv")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].raw_ticker, "GGAL")
        self.assertEqual(records[0].raw_quantity, "500")
        self.assertEqual(records[0].raw_avg_price, "4100,00")
        self.assertEqual(records[0].raw_currency, "ARS")

    async def test_schema_detector_avg_price_vs_market_price_disambiguation(
        self,
    ) -> None:
        """
        Verify AVG_PRICE prioritizes 'PPC' / 'Precio Promedio' over 'Último Precio' /
        'Cotización' / 'Precio', and never maps current market price to AVG_PRICE.
        """
        detector = SchemaDetector()

        # Case 1: Both market price and PPC coexist -> AVG_PRICE must bind to PPC (col 3)
        coexisting_headers = [
            "Ticker",
            "Nominales",
            "Último Precio",
            "PPC",
            "Cotización Actual",
            "Precio",
        ]
        res_both = detector.detect_schema(coexisting_headers)
        self.assertEqual(res_both.get_column_index(CanonicalReportField.AVG_PRICE), 3)
        self.assertEqual(
            res_both.mappings[CanonicalReportField.AVG_PRICE].raw_header, "PPC"
        )

        # Case 2: Only market price columns exist (no PPC or historical cost) -> AVG_PRICE is None
        market_only_headers = [
            "Especie",
            "Cantidad",
            "Último Precio",
            "Precio Actual",
            "Cotización",
            "Precio de Mercado",
            "Precio Cierre",
        ]
        res_market_only = detector.detect_schema(market_only_headers)
        self.assertTrue(res_market_only.has_required_fields())
        self.assertIsNone(
            res_market_only.get_column_index(CanonicalReportField.AVG_PRICE)
        )

    async def test_schema_detector_rejects_unrelated_columns(self) -> None:
        """
        Verify administrative/settlement columns remain in unmapped_headers and
        do not trigger false-positive canonical mappings.
        """
        detector = SchemaDetector()
        headers = [
            "Fecha Liquidación",
            "Número de Boleto",
            "Especie",
            "Cantidad",
            "Comisión ALyC",
            "IVA",
            "Derecho de Mercado",
        ]
        res = detector.detect_schema(headers)
        self.assertTrue(res.has_required_fields())
        self.assertEqual(len(res.mappings), 2)
        self.assertEqual(res.get_column_index(CanonicalReportField.TICKER), 2)
        self.assertEqual(res.get_column_index(CanonicalReportField.QUANTITY), 3)
        self.assertEqual(
            res.unmapped_headers,
            [
                "Fecha Liquidación",
                "Número de Boleto",
                "Comisión ALyC",
                "IVA",
                "Derecho de Mercado",
            ],
        )

    async def test_find_best_header_row_prefers_richest_table_header(self) -> None:
        """
        Verify find_best_header_row (and CSV/Excel parsers) selects the richest
        5-column table header row over an earlier 2-column banner row.
        """
        detector = SchemaDetector()
        sample_rows = [
            ["Resumen por Especie", "Tenencia Consolidada"],
            ["Cliente: 12345", "Fecha: 17/10/2026"],
            ["Especie", "Cantidad", "PPC", "Moneda", "Valuación Actual"],
        ]
        best = detector.find_best_header_row(sample_rows)
        self.assertIsNotNone(best)
        assert best is not None
        self.assertEqual(best.header_row_index, 2)
        self.assertEqual(len(best.mappings), 5)

        # Verify ExcelReportParser also selects row 3 (index 2) as header and extracts data
        xlsx_bytes = _build_xlsx_bytes(
            {
                "Tenencias": [
                    ["Especie", "Cantidad"],
                    [None, None, None, None, None],
                    ["Especie", "Cantidad", "PPC", "Moneda", "Valuación Actual"],
                    ["AL30", 1000, Decimal("65.50"), "USD", Decimal("65500.00")],
                ]
            }
        )
        records = await ExcelReportParser().parse_report(xlsx_bytes, "rich_header.xlsx")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].row_number, 4)
        self.assertEqual(records[0].raw_ticker, "AL30")
        self.assertEqual(records[0].raw_quantity, 1000)
        self.assertEqual(records[0].raw_avg_price, Decimal("65.5"))
        self.assertEqual(records[0].raw_currency, "USD")

    async def test_wide_table_dos_protection_truncates_columns(self) -> None:
        """
        Verify a row with 500 columns is truncated to MAX_COLUMNS_TO_SCAN (128)
        and processed deterministically without algorithmic complexity explosion.
        """
        detector = SchemaDetector()
        wide_headers = (
            ["Ticker", "Cantidad", "PPC", "Moneda"]
            + [f"Columna_Extra_{i}" for i in range(500)]
        )
        res = detector.detect_schema(wide_headers)
        self.assertTrue(res.has_required_fields())
        self.assertEqual(res.get_column_index(CanonicalReportField.TICKER), 0)
        self.assertEqual(res.get_column_index(CanonicalReportField.QUANTITY), 1)
        self.assertEqual(res.get_column_index(CanonicalReportField.AVG_PRICE), 2)
        self.assertEqual(res.get_column_index(CanonicalReportField.CURRENCY), 3)
        self.assertEqual(
            len(res.mappings) + len(res.unmapped_headers),
            MAX_COLUMNS_TO_SCAN,
        )


