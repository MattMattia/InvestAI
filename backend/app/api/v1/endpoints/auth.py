"""
Controlador REST de Autenticación, Endpoints /auth y Manejo Seguro de Sesión (Módulo 5.4 - Fase 1).
Implementa registro público blindado contra Mass Assignment, inicio de sesión con mitigación
de Timing Attacks (CWE-204), rotación criptográfica de Refresh Tokens y perfil de sesión activa,
bajo el contrato canónico Universal Envelope (APIResponse[T] / APIErrorResponse).
"""
from typing import Annotated
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_db_session
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
from app.schemas.user import UserResponse, UserRole

router = APIRouter()

# Hash bcrypt precalculado a nivel de módulo para mitigación de Timing Attacks (CWE-204)
# cuando se intenta autenticar un correo electrónico inexistente.
_DUMMY_PASSWORD_HASH: str = get_password_hash(
    "investai_dummy_timing_defense_secret", rounds=12
)


@router.post(
    "/register",
    response_model=APIResponse[UserResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Registrar nueva cuenta de usuario",
    description=(
        "Registra un nuevo usuario asignando por defecto el rol de privilegio mínimo (VIEWER) "
        "y estado activo. Protegido contra Mass Assignment y condiciones de carrera TOCTOU."
    ),
    responses={
        409: {"model": APIErrorResponse},
        422: {"model": APIErrorResponse},
    },
)
async def register_user(
    payload: RegisterRequest,
    db: Annotated[AsyncSession, Depends(get_db_session)],
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
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

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
    },
)
async def login_user(
    payload: LoginRequest,
    db: Annotated[AsyncSession, Depends(get_db_session)],
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
        )
    except InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        )

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

