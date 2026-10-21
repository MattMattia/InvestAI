from typing import Annotated
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, require_trader_or_admin
from app.domain.services.ingestion.base_parser import MAX_REPORT_SIZE_BYTES
from app.models.holding import HoldingModel
from app.models.user import UserModel
from app.schemas.ingestion import IngestionUploadResponse
from app.services.parsers.universal_parser import UniversalHoldingParser
from app.services.portfolio_service import ensure_asset, get_user_portfolio_or_404

router = APIRouter()


@router.post("/{id}/upload", response_model=IngestionUploadResponse, status_code=status.HTTP_200_OK)
async def upload_portfolio_file(
    id: str,
    current_user: Annotated[UserModel, Depends(require_trader_or_admin)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    file: UploadFile = File(...),
) -> IngestionUploadResponse:
    """
    Broker-agnostic universal file ingestion endpoint.
    Parses CSV or Excel reports (including Balanz exports), sanitizes tabular data,
    persists valid holdings into the portfolio, and returns an execution report.
    Enforces RBAC (TRADER or ADMIN) and anti-IDOR/BOLA tenant isolation.
    """
    try:
        portfolio = await get_user_portfolio_or_404(id, current_user, db)

        filename = file.filename or "holdings.csv"
        ext = filename.split(".")[-1].lower() if "." in filename else "csv"
        file_format = "xlsx" if ext in ("xlsx", "xls") else "csv"

        content = await file.read(MAX_REPORT_SIZE_BYTES + 1)
    finally:
        await file.close()

    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo subido está vacío.",
        )

    if len(content) > MAX_REPORT_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="El archivo subido excede el límite máximo de 10 MB.",
        )

    parser = UniversalHoldingParser()
    report = parser.parse(content=content, file_format=file_format)

    # Persist successfully parsed positions
    for domain_h in report.holdings:
        asset = await ensure_asset(
            db=db,
            ticker=domain_h.asset.ticker,
            asset_type=domain_h.asset.asset_type.value,
            currency=domain_h.currency.value,
            market="BYMA",
            sector=domain_h.asset.sector.value,
        )

        stmt = select(HoldingModel).where(
            HoldingModel.portfolio_id == portfolio.id,
            HoldingModel.asset_ticker == asset.ticker,
        )
        result = await db.execute(stmt)
        existing_holding = result.scalar_one_or_none()

        if existing_holding:
            existing_holding.quantity = domain_h.quantity
            existing_holding.average_buy_price = domain_h.average_buy_price
            existing_holding.current_price = domain_h.current_price
        else:
            new_holding = HoldingModel(
                portfolio_id=portfolio.id,
                asset_ticker=asset.ticker,
                quantity=domain_h.quantity,
                average_buy_price=domain_h.average_buy_price,
                current_price=domain_h.current_price,
            )
            db.add(new_holding)

    await db.flush()

    return IngestionUploadResponse(
        portfolio_id=portfolio.id,
        total_rows=report.total_rows,
        valid_records_count=report.valid_records_count,
        discarded_records_count=report.discarded_records_count,
        is_successful=report.is_successful,
        has_partial_errors=report.has_partial_errors,
        errors=report.errors,
    )
