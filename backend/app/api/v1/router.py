from fastapi import APIRouter
from app.api.v1.endpoints import (
    holdings,
    imports,
    portfolios,
    rebalancing,
    risk,
)

api_router = APIRouter()

api_router.include_router(portfolios.router, prefix="/portfolios", tags=["Portfolios"])
api_router.include_router(holdings.router, prefix="/portfolios", tags=["Holdings"])
api_router.include_router(imports.router, prefix="/portfolios", tags=["Imports"])
api_router.include_router(risk.router, prefix="/portfolios", tags=["Risk Engine"])
api_router.include_router(rebalancing.router, prefix="/portfolios", tags=["Rebalancing"])
