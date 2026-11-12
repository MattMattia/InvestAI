"""
Controlador REST de Autenticación, Endpoints /auth y Manejo Seguro de Sesión (Módulo 5.4 - Fase 1).
Implementa registro público blindado contra Mass Assignment, inicio de sesión con mitigación
de Timing Attacks (CWE-204), rotación criptográfica de Refresh Tokens y perfil de sesión activa,
bajo el contrato canónico Universal Envelope (APIResponse[T] / APIErrorResponse).
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    check_login_rate_limit,
    check_register_rate_limit,
    get_current_active_user,
    get_db_session,
)
from app.core.security import (
    ExpiredTokenError,
    InvalidTokenError,
    create_token_pair,
    decode_token,
    get_password_hash,
    verify_password,
)
from app.models.user import UserModel
from app.schemas.auth import LoginRequest, RegisterRequest
from app.schemas.envelope import APIErrorResponse, APIResponse
from app.schemas.token import RefreshTokenRequest, TokenResponse, TokenType
from app.schemas.user import UserResponse, UserRole, UserUpdateRequest

router = APIRouter()

# Hash bcrypt precalculado a nivel de módulo para mitigación de Timing Attacks (CWE-204)
# cuando se intenta autenticar un correo electrónico inexistente.
_DUMMY_PASSWORD_HASH: str = get_password_hash("investai_dummy_timing_defense_secret", rounds=12)


@router.post(
    "/register",
    response_model=APIResponse[UserResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Registrar nueva cuenta de usuario",
    description=(
        "Registra un nuevo usuario asignando por defecto el rol de privilegio mínimo (VIEWER) "
        "y estado activo. Protegido contra Mass Assignment, Rate Limiting y condiciones de carrera TOCTOU."
    ),
    responses={
        409: {"model": APIErrorResponse},
        422: {"model": APIErrorResponse},
        429: {"model": APIErrorResponse},
    },
)
async def register_user(
    payload: RegisterRequest,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _rate_limit: None = Depends(check_register_rate_limit),
) -> APIResponse[UserResponse]:
    """
    Endpoint público de registro de usuario con asignación forzada de rol VIEWER.
    """
    stmt = select(UserModel).where(UserModel.email == payload.email)
    result = await db.execute(stmt)
    existing_user = result.scalar_one_or_none()

    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    hashed_pw = get_password_hash(payload.password)
    new_user = UserModel(
        email=payload.email,
        full_name=payload.full_name,
        hashed_password=hashed_pw,
        role=UserRole.VIEWER,
        is_active=True,
    )

    db.add(new_user)
    try:
        await db.commit()
        await db.refresh(new_user)
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        ) from exc

    return APIResponse(data=UserResponse.model_validate(new_user))


@router.post(
    "/login",
    response_model=APIResponse[TokenResponse],
    status_code=status.HTTP_200_OK,
    summary="Autenticar usuario y emitir par de tokens JWT",
    description=(
        "Verifica credenciales en tiempo constante mitigando enumeración de usuarios (CWE-204) "
        "y emite un par atómico de Access Token y Refresh Token con JTIs independientes."
    ),
    responses={
        401: {"model": APIErrorResponse},
        403: {"model": APIErrorResponse},
        422: {"model": APIErrorResponse},
        429: {"model": APIErrorResponse},
    },
)
async def login_user(
    payload: LoginRequest,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _rate_limit: None = Depends(check_login_rate_limit),
) -> APIResponse[TokenResponse]:
    """
    Endpoint de autenticación de credenciales con protección contra Timing Attacks.
    """
    stmt = select(UserModel).where(UserModel.email == payload.email)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None:
        verify_password(payload.password, _DUMMY_PASSWORD_HASH)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user account",
        )

    tokens = create_token_pair(
        subject=user.id,
        role=user.role,
        email=user.email,
    )
    return APIResponse(data=tokens)


@router.post(
    "/refresh",
    response_model=APIResponse[TokenResponse],
    status_code=status.HTTP_200_OK,
    summary="Rotar par de tokens mediante Refresh Token",
    description=(
        "Valida criptográficamente un Refresh Token (rechazando Access Tokens), "
        "comprueba el estado activo del usuario en base de datos y emite un nuevo par de tokens rotados."
    ),
    responses={
        401: {"model": APIErrorResponse},
        403: {"model": APIErrorResponse},
        422: {"model": APIErrorResponse},
    },
)
async def refresh_tokens(
    payload: RefreshTokenRequest,
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[TokenResponse]:
    """
    Endpoint de renovación y rotación criptográfica de sesión mediante Refresh Token.
    """
    try:
        token_payload = decode_token(
            payload.refresh_token,
            expected_type=TokenType.REFRESH,
        )
    except ExpiredTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has expired",
            headers={
                "WWW-Authenticate": (
                    'Bearer error="invalid_token", error_description="The token has expired"'
                )
            },
        ) from None
    except InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        ) from None

    try:
        user_id = uuid.UUID(token_payload.sub)
    except (ValueError, AttributeError):
        user_id = token_payload.sub

    stmt = select(UserModel).where(UserModel.id == user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user account",
        )

    new_tokens = create_token_pair(
        subject=user.id,
        role=user.role,
        email=user.email,
    )
    return APIResponse(data=new_tokens)


@router.get(
    "/me",
    response_model=APIResponse[UserResponse],
    status_code=status.HTTP_200_OK,
    summary="Obtener perfil del usuario autenticado",
    description="Retorna los datos de identidad y rol RBAC del usuario asociado al Access Token activo.",
    responses={
        401: {"model": APIErrorResponse},
        403: {"model": APIErrorResponse},
    },
)
async def get_current_user_profile(
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
) -> APIResponse[UserResponse]:
    """
    Endpoint protegido que devuelve el perfil público del usuario autenticado.
    """
    return APIResponse(data=UserResponse.model_validate(current_user))


# SEC: roles a user may assign to themselves. ADMIN grants cross-tenant visibility over
# every portfolio and order, so it is never self-assignable.
SELF_ASSIGNABLE_ROLES: frozenset[str] = frozenset({UserRole.VIEWER.value, UserRole.TRADER.value})


def _role_value(role: UserRole | str) -> str:
    return role.value if isinstance(role, UserRole) else str(role)


@router.patch(
    "/me",
    response_model=APIResponse[UserResponse],
    status_code=status.HTTP_200_OK,
    summary="Actualizar perfil de inversor y rol operativo del usuario autenticado",
    description=(
        "Permite actualizar nombre y perfil de riesgo, y alternar el propio rol entre VIEWER y "
        "TRADER. Asignarse ADMIN (visibilidad sobre carteras de todos los usuarios) está "
        "prohibido (403); un ADMIN sí puede conservar su rol o bajarse a uno operativo."
    ),
    responses={
        401: {"model": APIErrorResponse},
        403: {"model": APIErrorResponse},
        422: {"model": APIErrorResponse},
    },
)
async def update_current_user_profile(
    payload: UserUpdateRequest,
    current_user: Annotated[UserModel, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> APIResponse[UserResponse]:
    """
    Actualiza los atributos de perfil y rol en caliente del usuario autenticado.
    La validación de rol ocurre antes de aplicar cualquier cambio: una solicitud rechazada
    no modifica nada.
    """
    if payload.role is not None:
        requested_role = _role_value(payload.role)
        if (
            requested_role not in SELF_ASSIGNABLE_ROLES
            and _role_value(current_user.role) != UserRole.ADMIN.value
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="El rol ADMIN no puede autoasignarse.",
            )

    if payload.full_name is not None:
        current_user.full_name = payload.full_name.strip()

    if payload.investor_profile is not None:
        normalized_profile = payload.investor_profile.strip().upper()
        if normalized_profile not in {"CONSERVATIVE", "MODERATE", "AGGRESSIVE"}:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Invalid investor_profile. Allowed: CONSERVATIVE, MODERATE, AGGRESSIVE",
            )
        current_user.investor_profile = normalized_profile

    if payload.role is not None:
        current_user.role = _role_value(payload.role)

    current_user.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(current_user)
    return APIResponse(data=UserResponse.model_validate(current_user))
