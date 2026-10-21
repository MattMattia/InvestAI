"""
REST Controller for Broker Statement Ingestion and Transactional Portfolio
Reconciliation (Module 6.3 - Phase 2).

Exposes `POST /api/v1/ingestion/upload-report` with strict RBAC (`TRADER`/`ADMIN`),
anti-IDOR ownership verification, multipart file sanitization, 10 MB size ceiling,
and end-to-end orchestration across Modules 6.1, 6.2, and 6.3 wrapped in the
canonical `APIResponse[IngestionReportSummary]` envelope.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_trader_or_admin
from app.domain.services.ingestion.base_parser import (
    MAX_REPORT_SIZE_BYTES,
    CorruptedReportError,
    EmptyReportError,
    MissingRequiredColumnsError,
    ReportParsingError,
    ReportSizeLimitExceededError,
    UnsupportedReportFormatError,
    get_report_parser,
)
from app.domain.services.ingestion.data_cleaning_pipeline import DataCleaningPipeline
from app.domain.services.portfolio_reconciliation import (
    EmptyReconciliationSnapshotError,
    PortfolioReconciliationService,
    ReconciliationMode,
    ReconciliationPortfolioNotFoundError,
)
from app.models.portfolio import PortfolioModel
from app.models.user import UserModel
from app.schemas.envelope import APIErrorResponse, APIResponse
from app.schemas.ingestion import IngestionReportSummary

router = APIRouter()

ALLOWED_REPORT_EXTENSIONS: frozenset[str] = frozenset({".csv", ".xlsx", ".xls"})

ALLOWED_REPORT_MIME_TYPES: frozenset[str] = frozenset(
    {
        "text/csv",
        "application/csv",
        "text/plain",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/octet-stream",
        "",
    }
)


def _resolve_portfolio_id(
    form_portfolio_id: str | None,
    request: Request,
) -> str:
    """Resolve and validate `portfolio_id` from multipart form or query params."""
    raw_id = (
        form_portfolio_id
        if form_portfolio_id is not None
        else request.query_params.get("portfolio_id")
    )
    if raw_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Field 'portfolio_id' is required.",
        )
    if any(ord(ch) < 32 for ch in raw_id):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Control characters are not permitted in 'portfolio_id'.",
        )
    cleaned = raw_id.strip()
    if not cleaned:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Field 'portfolio_id' cannot be empty.",
        )
    return cleaned


def _resolve_reconciliation_mode(
    form_mode: str | None,
    request: Request,
) -> ReconciliationMode:
    """Resolve and validate `mode` from multipart form or query params."""
    raw_mode = (
        form_mode if form_mode is not None else request.query_params.get("mode")
    )
    if raw_mode is None or not raw_mode.strip():
        return ReconciliationMode.SNAPSHOT

    normalized = raw_mode.strip().upper()
    try:
        return ReconciliationMode(normalized)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Invalid reconciliation mode '{raw_mode}'. "
                "Allowed values: SNAPSHOT, MERGE."
            ),
        ) from exc


def _resolve_allow_empty_snapshot(
    form_allow_empty: str | bool | None,
    request: Request,
) -> bool:
    """Resolve `allow_empty_snapshot` flag from multipart form or query params."""
    raw_val: str | bool | None = (
        form_allow_empty
        if form_allow_empty is not None
        else request.query_params.get("allow_empty_snapshot")
    )
    if raw_val is None:
        return False
    if isinstance(raw_val, bool):
        return raw_val

    lowered = str(raw_val).strip().lower()
    if not lowered:
        return False
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False

    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=f"Invalid boolean value '{raw_val}' for 'allow_empty_snapshot'.",
    )


def _sanitize_and_validate_filename(raw_filename: str | None) -> str:
    """
    Sanitize cross-platform path separators, enforce length and control character
    constraints, and verify the extension belongs to `ALLOWED_REPORT_EXTENSIONS`.
    """
    candidate = raw_filename or ""
    if any(ord(ch) < 32 for ch in candidate):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Filename contains prohibited control characters.",
        )

    clean_filename = candidate.replace("\\", "/").split("/")[-1].strip()
    if not clean_filename or len(clean_filename) > 255:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Filename must be between 1 and 255 characters.",
        )

    stem, dot, ext = clean_filename.rpartition(".")
    if not dot or not stem.strip(" ."):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Filename '{clean_filename}' must have a valid base name and extension.",
        )

    normalized_ext = f".{ext.lower()}"
    if normalized_ext not in ALLOWED_REPORT_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Unsupported file extension '{normalized_ext}'. "
                "Allowed extensions: .csv, .xlsx, .xls."
            ),
        )

    return clean_filename


@router.post(
    "/upload-report",
    response_model=APIResponse[IngestionReportSummary],
    status_code=status.HTTP_200_OK,
    summary="Upload and reconcile a broker holding statement (CSV / Excel)",
    description=(
        "Ingests a local broker report (.csv, .xlsx, .xls up to 10 MB), detects its "
        "column schema, cleans monetary and ticker representations, and reconciles "
        "the holdings transactionally into the user's portfolio."
    ),
    responses={
        401: {"model": APIErrorResponse},
        403: {"model": APIErrorResponse},
        404: {"model": APIErrorResponse},
        413: {"model": APIErrorResponse},
        422: {"model": APIErrorResponse},
    },
)
async def upload_broker_report(
    request: Request,
    current_user: Annotated[UserModel, Depends(require_trader_or_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    file: UploadFile = File(...),
    portfolio_id: str | None = Form(default=None),
    mode: str | None = Form(default=None),
    allow_empty_snapshot: str | None = Form(default=None),
) -> APIResponse[IngestionReportSummary]:
    """
    End-to-end broker report upload and portfolio reconciliation endpoint.
    """
    try:
        effective_portfolio_id = _resolve_portfolio_id(portfolio_id, request)
        effective_mode = _resolve_reconciliation_mode(mode, request)
        effective_allow_empty = _resolve_allow_empty_snapshot(
            allow_empty_snapshot, request
        )

        clean_filename = _sanitize_and_validate_filename(file.filename)

        base_mime = (file.content_type or "").split(";")[0].strip().lower()
        if base_mime not in ALLOWED_REPORT_MIME_TYPES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    f"Unsupported MIME content-type '{base_mime}'. "
                    "Allowed types: CSV or Excel spreadsheet."
                ),
            )

        file_bytes = await file.read(MAX_REPORT_SIZE_BYTES + 1)
    finally:
        await file.close()

    if len(file_bytes) == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Uploaded report file is empty",
        )

    if len(file_bytes) > MAX_REPORT_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Report file exceeds maximum allowed size of 10 MB",
        )

    # Early Anti-IDOR / BOLA check prior to CPU/memory-intensive parsing
    stmt = select(PortfolioModel.id, PortfolioModel.user_id).where(
        PortfolioModel.id == effective_portfolio_id
    )
    portfolio_row = (await db.execute(stmt)).first()
    if portfolio_row is None or str(portfolio_row.user_id) != str(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Portfolio '{effective_portfolio_id}' not found",
        )

    # 1. Format Parsing & Fuzzy Schema Detection (Module 6.1)
    try:
        parser = get_report_parser(clean_filename)
        raw_records = await parser.parse_report(file_bytes, clean_filename)
    except ReportSizeLimitExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=str(exc),
        ) from exc
    except (
        UnsupportedReportFormatError,
        EmptyReportError,
        CorruptedReportError,
        MissingRequiredColumnsError,
        ReportParsingError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    # 2. Data Cleaning & Monetary Normalization (Module 6.2)
    cleaning_pipeline = DataCleaningPipeline()
    clean_result = cleaning_pipeline.clean_records(raw_records)

    if clean_result.total_valid == 0 and not effective_allow_empty:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"All {clean_result.total_invalid} extracted holding row(s) "
                "failed data quality validation."
            ),
        )

    # 3. Transactional Portfolio Reconciliation (Module 6.3)
    reconciliation_service = PortfolioReconciliationService()
    try:
        reconciliation_report = await reconciliation_service.reconcile_portfolio(
            db=db,
            portfolio_id=effective_portfolio_id,
            clean_records=clean_result.valid_records,
            mode=effective_mode,
            user_id=current_user.id,
            allow_empty_snapshot=effective_allow_empty,
        )
        await db.commit()
    except ReconciliationPortfolioNotFoundError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except EmptyReconciliationSnapshotError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    # 4. Canonical Envelope Assembly
    combined_warnings = list(clean_result.warnings) + list(
        reconciliation_report.warnings
    )
    summary = IngestionReportSummary(
        filename=clean_filename,
        portfolio_id=effective_portfolio_id,
        mode=effective_mode,
        total_rows_parsed=len(raw_records),
        valid_records_count=clean_result.total_valid,
        invalid_records_count=clean_result.total_invalid,
        invalid_records=clean_result.invalid_records,
        reconciliation=reconciliation_report,
        warnings=combined_warnings,
    )

    return APIResponse(data=summary)
