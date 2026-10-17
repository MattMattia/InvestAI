"""
Concrete CSV report parsing strategy for local broker statements (Module 6.1 - Phase 1).
Supports multi-encoding fallback (UTF-8-SIG, UTF-8, CP1252, Latin-1) and automatic
delimiter and header line discovery.
"""
from __future__ import annotations

import asyncio
import csv
import io
from pathlib import PurePath
from typing import Any

from pydantic import ValidationError

from app.domain.services.ingestion.base_parser import (
     MAX_HEADER_SCAN_LINES,
    MAX_REPORT_ROWS,
    BaseReportParser,
    CorruptedReportError,
    EmptyReportError,
    MissingRequiredColumnsError,
    RawHoldingRecord,
    ReportSizeLimitExceededError,
    UnsupportedReportFormatError,
    is_ignored_summary_ticker,
    resolve_header_mapping,
)

_CANDIDATE_ENCODINGS: tuple[str, ...] = ("utf-8-sig", "utf-8", "cp1252", "latin-1")
_CANDIDATE_DELIMITERS: tuple[str, ...] = (";", ",", "\t", "|")
_BINARY_MAGIC_SIGNATURES: tuple[bytes, ...] = (
    b"PK\x03\x04",  # ZIP / XLSX archive
    b"\xd0\xcf\x11\xe0",  # OLE2 / legacy XLS
    b"%PDF-",  # PDF document
    b"\x7fELF",  # ELF binary
    b"\x89PNG\r\n\x1a\n",  # PNG image
)


class CSVReportParser(BaseReportParser):
    """
    Asynchronous-safe CSV report parser capable of handling Argentine ALyC
    statements with preamble banners, semicolon/comma/tab/pipe delimiters,
    and legacy Windows-1252/Latin-1 encodings.
    """

    async def parse_report(
        self, file_stream: bytes, filename: str
    ) -> list[RawHoldingRecord]:
        """Parse a CSV binary stream in a worker thread to avoid blocking the event loop."""
        return await asyncio.to_thread(self._parse_sync, file_stream, filename)

    def _parse_sync(
        self, file_stream: bytes, filename: str
    ) -> list[RawHoldingRecord]:
        self.validate_stream(file_stream, filename)

        ext = PurePath(filename.strip()).suffix.lower()
        if ext != ".csv":
            raise UnsupportedReportFormatError(
                f"CSVReportParser requires a '.csv' file, got '{ext or '<no extension>'}'"
            )

        if b"\x00" in file_stream:
            raise CorruptedReportError(
                "Null bytes detected in CSV stream; binary files are not allowed"
            )

        for sig in _BINARY_MAGIC_SIGNATURES:
            if file_stream.startswith(sig):
                raise CorruptedReportError(
                    "Binary file signature detected in CSV upload"
                )

        decoded_text = self._decode_stream(file_stream)
        if not decoded_text.strip():
            raise EmptyReportError("CSV report contains no text content")

        lines = decoded_text.splitlines()
        non_empty_exist = any(line.strip() for line in lines)
        if not non_empty_exist:
            raise EmptyReportError("CSV report contains only blank lines")

        header_line_idx, delimiter, header_cells, column_map = self._detect_header(
            lines
        )

        clean_headers: list[str] = [str(h).strip() for h in header_cells]
        remaining_text = "\n".join(lines[header_line_idx + 1 :])

        records: list[RawHoldingRecord] = []
        try:
            reader = csv.reader(io.StringIO(remaining_text), delimiter=delimiter)
            for offset, row in enumerate(reader, start=1):
                row_number = header_line_idx + 1 + offset
                if not row or all(not cell.strip() for cell in row):
                    continue

                ticker_idx = column_map["ticker"]
                qty_idx = column_map["quantity"]

                if ticker_idx >= len(row) or qty_idx >= len(row):
                    continue

                raw_ticker_cell = row[ticker_idx].strip()
                raw_qty_cell = row[qty_idx].strip()

                if not raw_ticker_cell or not raw_qty_cell:
                    continue

                if is_ignored_summary_ticker(raw_ticker_cell):
                    continue

                if len(records) >= MAX_REPORT_ROWS:
                    raise ReportSizeLimitExceededError(
                        f"CSV report exceeds maximum allowed row count of {MAX_REPORT_ROWS}"
                    )

                raw_avg_price: str | None = None
                if "avg_price" in column_map and column_map["avg_price"] < len(row):
                    avg_cell = row[column_map["avg_price"]].strip()
                    raw_avg_price = avg_cell if avg_cell else None

                raw_currency: str | None = None
                if "currency" in column_map and column_map["currency"] < len(row):
                    curr_cell = row[column_map["currency"]].strip()
                    raw_currency = curr_cell if curr_cell else None

                raw_fields: dict[str, Any] = {}
                for col_idx, header_name in enumerate(clean_headers):
                    if not header_name:
                        continue
                    cell_val = row[col_idx].strip() if col_idx < len(row) else ""
                    raw_fields[header_name] = cell_val

                try:
                    record = RawHoldingRecord(
                        row_number=row_number,
                        raw_ticker=raw_ticker_cell,
                        raw_quantity=raw_qty_cell,
                        raw_avg_price=raw_avg_price,
                        raw_currency=raw_currency,
                        raw_fields=raw_fields,
                    )
                except (ValidationError, ValueError) as exc:
                    raise CorruptedReportError(
                        f"Invalid holding data at CSV row {row_number}: {exc}"
                    ) from exc

                records.append(record)
        except csv.Error as exc:
            raise CorruptedReportError(f"Malformed CSV structure: {exc}") from exc

        if not records:
            raise EmptyReportError(
                "CSV report contains headers but no valid holding rows"
            )

        return records

    @staticmethod
    def _decode_stream(file_stream: bytes) -> str:
        """Decode byte stream trying UTF-8-SIG, UTF-8, CP1252, and Latin-1 in sequence."""
        for encoding in _CANDIDATE_ENCODINGS:
            try:
                return file_stream.decode(encoding, errors="strict")
            except UnicodeDecodeError:
                continue
        raise CorruptedReportError(
            "Unable to decode CSV stream with supported character encodings"
        )

    @staticmethod
    def _detect_header(
        lines: list[str],
    ) -> tuple[int, str, list[str], dict[str, int]]:
        """
        Scan up to `MAX_HEADER_SCAN_LINES` non-empty lines to identify the delimiter
        and header row containing at least 'ticker' and 'quantity' columns.
        """
        scanned_non_empty = 0
        for line_idx, line in enumerate(lines):
            if not line.strip():
                continue
            scanned_non_empty += 1
            if scanned_non_empty > MAX_HEADER_SCAN_LINES:
                break

            best_delimiter: str | None = None
            best_row: list[str] | None = None
            best_mapping: dict[str, int] | None = None

            for delimiter in _CANDIDATE_DELIMITERS:
                try:
                    parsed_rows = list(csv.reader([line], delimiter=delimiter))
                except csv.Error as exc:
                    raise CorruptedReportError(
                        f"Malformed CSV header candidate at line {line_idx + 1}: {exc}"
                    ) from exc

                if not parsed_rows:
                    continue
                candidate_cells = parsed_rows[0]
                if len(candidate_cells) < 2:
                    continue

                mapping = resolve_header_mapping(candidate_cells)
                if "ticker" in mapping and "quantity" in mapping:
                    if best_mapping is None or len(mapping) > len(best_mapping):
                        best_delimiter = delimiter
                        best_row = candidate_cells
                        best_mapping = mapping

            if (
                best_delimiter is not None
                and best_row is not None
                and best_mapping is not None
            ):
                return line_idx, best_delimiter, best_row, best_mapping

        raise MissingRequiredColumnsError(
            "Required columns ('ticker' and 'quantity') were not found in the CSV report"
        )

