"""
Domain ingestion services and format strategies for local broker reports (Module 6.1).
"""
from app.domain.services.ingestion.base_parser import (
    AVG_PRICE_HEADER_ALIASES,
    CURRENCY_HEADER_ALIASES,
    IGNORED_SUMMARY_TICKERS,
    MAX_COMPRESSION_RATIO,
    MAX_DECOMPRESSED_XLSX_BYTES,
    MAX_HEADER_SCAN_LINES,
    MAX_REPORT_ROWS,
    MAX_REPORT_SIZE_BYTES,
    QUANTITY_HEADER_ALIASES,
    TICKER_HEADER_ALIASES,
    BaseReportParser,
    CorruptedReportError,
    EmptyReportError,
    MissingRequiredColumnsError,
    RawHoldingRecord,
    ReportParsingError,
    ReportSizeLimitExceededError,
    UnsupportedReportFormatError,
    get_report_parser,
    is_ignored_summary_ticker,
    normalize_header_name,
    resolve_header_mapping,
)
from app.domain.services.ingestion.csv_parser import CSVReportParser
from app.domain.services.ingestion.excel_parser import ExcelReportParser

__all__ = [
    "AVG_PRICE_HEADER_ALIASES",
    "CURRENCY_HEADER_ALIASES",
    "IGNORED_SUMMARY_TICKERS",
    "MAX_COMPRESSION_RATIO",
    "MAX_DECOMPRESSED_XLSX_BYTES",
    "MAX_HEADER_SCAN_LINES",
    "MAX_REPORT_ROWS",
    "MAX_REPORT_SIZE_BYTES",
    "QUANTITY_HEADER_ALIASES",
    "TICKER_HEADER_ALIASES",
    "BaseReportParser",
    "CSVReportParser",
    "CorruptedReportError",
    "EmptyReportError",
    "ExcelReportParser",
    "MissingRequiredColumnsError",
    "RawHoldingRecord",
    "ReportParsingError",
    "ReportSizeLimitExceededError",
    "UnsupportedReportFormatError",
    "get_report_parser",
    "is_ignored_summary_ticker",
    "normalize_header_name",
    "resolve_header_mapping",
]

