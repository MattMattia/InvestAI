"""
API Package: Re-exportación canónica de dependencias de seguridad, base de datos y servicios.
"""
from app.api.deps import (
    RoleChecker,
    check_login_rate_limit,
    check_register_rate_limit,
    get_client_ip,
    get_current_active_user,
    get_current_token_payload,
    get_current_user,
    get_db,
    get_db_session,
    get_market_service,
    global_quote_cache,
    oauth2_scheme,
    require_admin,
    require_trader_or_admin,
)

__all__ = [
    "global_quote_cache",
    "get_db_session",
    "get_db",
    "oauth2_scheme",
    "get_current_token_payload",
    "get_current_user",
    "get_current_active_user",
    "RoleChecker",
    "require_trader_or_admin",
    "require_admin",
    "get_client_ip",
    "check_login_rate_limit",
    "check_register_rate_limit",
    "get_market_service",
]

