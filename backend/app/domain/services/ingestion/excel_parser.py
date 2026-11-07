"""
Concrete Excel (.xlsx) report parsing strategy for local broker statements (Module 6.1 - Phase 1).
Implements pre-parse Zip-Bomb, XXE/DOCTYPE, and VBA macro shields, non-blocking
read-only workbook streaming, and multi-sheet table discovery.
"""

from __future__ import annotations

import asyncio
import io
import itertools
import math
import zipfile
import zlib
from collections.abc import Sequence
from decimal import Decimal
from pathlib import PurePath
from typing import Any

import openpyxl
from pydantic import ValidationError

from app.domain.services.ingestion.base_parser import (
    MAX_COMPRESSION_RATIO,
    MAX_DECOMPRESSED_XLSX_BYTES,
    MAX_HEADER_SCAN_LINES,
    MAX_REPORT_ROWS,
    MAX_ZIP_ENTRIES,
    BaseReportParser,
    CorruptedReportError,
    EmptyReportError,
    MissingRequiredColumnsError,
    RawHoldingRecord,
    ReportParsingError,
    ReportSizeLimitExceededError,
    UnsupportedReportFormatError,
    is_ignored_summary_ticker,
)
from app.domain.services.ingestion.schema_detector import SchemaDetector

_XML_HEAD_INSPECTION_BYTES: int = 4096


def _clean_cell_value(val: Any) -> Any:
    """
    Convert an openpyxl cell value into a clean primitive free of IEEE-754 float noise.
    """
    if val is None:
        return None
    if isinstance(val, bool):
        return str(val)
    if isinstance(val, float):
        if not math.isfinite(val):
            return None
        return Decimal(str(val))
    if isinstance(val, int | Decimal):
        return val
    return str(val).replace("\xa0", " ").strip()


def _is_empty_cell(val: Any) -> bool:
    """Return True if a cleaned cell value represents an empty cell."""
    if val is None:
        return True
    if isinstance(val, str) and not val.strip():
        return True
    return False


class ExcelReportParser(BaseReportParser):
    """
    Asynchronous-safe Excel (.xlsx) parser using `openpyxl` in `read_only=True, data_only=True`
    mode with defensive archive inspection.
    """

    def __init__(self, schema_detector: SchemaDetector | None = None) -> None:
        self._schema_detector: SchemaDetector = schema_detector or SchemaDetector()

    async def parse_report(self, file_stream: bytes, filename: str) -> list[RawHoldingRecord]:
        """Parse an XLSX binary stream in a worker thread to avoid blocking the event loop."""
        return await asyncio.to_thread(self._parse_sync, file_stream, filename)

    def _parse_sync(self, file_stream: bytes, filename: str) -> list[RawHoldingRecord]:
        self.validate_stream(file_stream, filename)

        ext = PurePath(filename.strip()).suffix.lower()
        if ext != ".xlsx":
            raise UnsupportedReportFormatError(
                f"ExcelReportParser only supports '.xlsx' files (got '{ext or '<no extension>'}'). "
                "Legacy '.xls' and macro-enabled '.xlsm' formats are rejected."
            )

        self._inspect_zip_envelope(file_stream)

        try:
            workbook = openpyxl.load_workbook(
                io.BytesIO(file_stream),
                read_only=True,
                data_only=True,
            )
        except ReportParsingError:
            raise
        except (KeyError, ValueError, IndexError, TypeError, Exception) as exc:
            raise CorruptedReportError(f"Failed to open XLSX workbook: {exc}") from exc

        try:
            return self._extract_from_workbook(workbook)
        except ReportParsingError:
            raise
        except (KeyError, ValueError, IndexError, TypeError, Exception) as exc:
            raise CorruptedReportError(f"Failed while reading XLSX workbook rows: {exc}") from exc
        finally:
            workbook.close()

    @staticmethod
    def _inspect_zip_envelope(file_stream: bytes) -> None:
        """
        Inspect the ZIP container before passing to openpyxl to block:
        1. Corrupted non-ZIP streams.
        2. Entry-Bomb / Inode exhaustion archives (`> MAX_ZIP_ENTRIES`).
        3. VBA macro binaries (`vbaProject.bin`).
        4. Zip-Bombs via compression ratio or total decompressed size.
        5. Case-insensitive XML External Entities (`<!entity` / `<!doctype`).
        """
        try:
            with zipfile.ZipFile(io.BytesIO(file_stream), mode="r") as zf:
                infos = zf.infolist()
                if not infos:
                    raise CorruptedReportError("XLSX archive contains no entries")

                if len(infos) > MAX_ZIP_ENTRIES:
                    raise ReportSizeLimitExceededError(
                        f"XLSX archive entry count ({len(infos)}) exceeds "
                        f"maximum safety limit ({MAX_ZIP_ENTRIES})"
                    )

                total_decompressed = 0
                for zinfo in infos:
                    entry_name_lower = zinfo.filename.lower()
                    if "vbaproject.bin" in entry_name_lower:
                        raise CorruptedReportError(
                            "Excel macros (vbaProject.bin) are not permitted"
                        )

                    compress_size = max(1, zinfo.compress_size)
                    ratio = zinfo.file_size / compress_size
                    if ratio > MAX_COMPRESSION_RATIO:
                        raise ReportSizeLimitExceededError(
                            f"Archive entry '{zinfo.filename}' compression ratio ({ratio:.1f}) "
                            f"exceeds safety threshold ({MAX_COMPRESSION_RATIO})"
                        )

                    total_decompressed += zinfo.file_size
                    if total_decompressed > MAX_DECOMPRESSED_XLSX_BYTES:
                        raise ReportSizeLimitExceededError(
                            f"Decompressed XLSX size ({total_decompressed} bytes) exceeds "
                            f"safety limit ({MAX_DECOMPRESSED_XLSX_BYTES} bytes)"
                        )

                    if entry_name_lower.endswith((".xml", ".rels")):
                        with zf.open(zinfo, mode="r") as xml_file:
                            head_bytes = xml_file.read(_XML_HEAD_INSPECTION_BYTES).lower()
                            if b"<!entity" in head_bytes or b"<!doctype" in head_bytes:
                                raise CorruptedReportError(
                                    "XML external entities or DOCTYPE declarations are not permitted"
                                )
        except ReportParsingError:
            raise
        except (zipfile.BadZipFile, OSError, EOFError, zlib.error) as exc:
            raise CorruptedReportError(f"Invalid or corrupted XLSX archive: {exc}") from exc

    def _extract_from_workbook(self, workbook: Any) -> list[RawHoldingRecord]:
        has_any_content = False

        for sheet_name in workbook.sheetnames:
            sheet = workbook[sheet_name]
            row_iter = sheet.iter_rows(values_only=True)

            buffered_rows: list[Sequence[Any]] = []
            scanned_non_empty = 0

            for raw_row in row_iter:
                row_seq: Sequence[Any] = raw_row if raw_row is not None else ()
                buffered_rows.append(row_seq)
                if not row_seq or all(_is_empty_cell(_clean_cell_value(c)) for c in row_seq):
                    continue

                has_any_content = True
                scanned_non_empty += 1
                if scanned_non_empty >= MAX_HEADER_SCAN_LINES:
                    break

            best_schema = self._schema_detector.find_best_header_row(buffered_rows)
            if best_schema is not None:
                header_idx = best_schema.header_row_index
                header_row_number = header_idx + 1
                raw_header_row = buffered_rows[header_idx]
                header_cells = [str(c).strip() if c is not None else "" for c in raw_header_row]
                column_map = {
                    field.value: col_map.column_index
                    for field, col_map in best_schema.mappings.items()
                }
                remaining_iter = itertools.chain(
                    buffered_rows[header_idx + 1 :],
                    row_iter,
                )
                return self._extract_rows_after_header(
                    row_iter=remaining_iter,
                    start_row_number=header_row_number,
                    header_cells=header_cells,
                    column_map=column_map,
                )

        if not has_any_content:
            raise EmptyReportError("XLSX workbook contains no data rows across all sheets")

        raise MissingRequiredColumnsError(
            "Required columns ('ticker' and 'quantity') were not found in any worksheet"
        )

    @staticmethod
    def _extract_rows_after_header(
        row_iter: Any,
        start_row_number: int,
        header_cells: list[str],
        column_map: dict[str, int],
    ) -> list[RawHoldingRecord]:
        records: list[RawHoldingRecord] = []
        row_number = start_row_number

        ticker_idx = column_map["ticker"]
        qty_idx = column_map["quantity"]
        avg_idx = column_map.get("avg_price")
        curr_idx = column_map.get("currency")

        for raw_row in row_iter:
            row_number += 1
            if not raw_row:
                continue

            cleaned_row = [_clean_cell_value(cell) for cell in raw_row]
            if all(_is_empty_cell(c) for c in cleaned_row):
                continue

            if ticker_idx >= len(cleaned_row) or qty_idx >= len(cleaned_row):
                continue

            raw_ticker_val = cleaned_row[ticker_idx]
            raw_qty_val = cleaned_row[qty_idx]

            if _is_empty_cell(raw_ticker_val) or _is_empty_cell(raw_qty_val):
                continue

            if is_ignored_summary_ticker(raw_ticker_val):
                continue

            if len(records) >= MAX_REPORT_ROWS:
                raise ReportSizeLimitExceededError(
                    f"XLSX report exceeds maximum allowed row count of {MAX_REPORT_ROWS}"
                )

            raw_avg_price: Any = None
            if avg_idx is not None and avg_idx < len(cleaned_row):
                candidate_avg = cleaned_row[avg_idx]
                if not _is_empty_cell(candidate_avg):
                    raw_avg_price = candidate_avg

            raw_currency: str | None = None
            if curr_idx is not None and curr_idx < len(cleaned_row):
                candidate_curr = cleaned_row[curr_idx]
                if not _is_empty_cell(candidate_curr):
                    raw_currency = str(candidate_curr).strip()

            raw_fields: dict[str, Any] = {}
            for col_idx, header_name in enumerate(header_cells):
                if not header_name:
                    continue
                cell_val = cleaned_row[col_idx] if col_idx < len(cleaned_row) else None
                raw_fields[header_name] = cell_val

            try:
                record = RawHoldingRecord(
                    row_number=row_number,
                    raw_ticker=str(raw_ticker_val),
                    raw_quantity=raw_qty_val,
                    raw_avg_price=raw_avg_price,
                    raw_currency=raw_currency,
                    raw_fields=raw_fields,
                )
            except (ValidationError, ValueError) as exc:
                raise CorruptedReportError(
                    f"Invalid holding data at Excel row {row_number}: {exc}"
                ) from exc

            records.append(record)

        if not records:
            raise EmptyReportError("XLSX worksheet contains headers but no valid holding rows")

        return records
