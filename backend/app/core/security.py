"""
Servicio criptográfico defensivo, gestión de secretos y motor de tokens JWT (Módulo 5.1 & Módulo 5.2).
Implementación directa sobre bcrypt nativo (hashing) y PyJWT (RFC 7519 / HS256),
con soporte para pydantic.SecretStr, mitigación de ataques DoS, verificación en tiempo constante,
emisión atómica de pares de tokens (access/refresh) y validación estricta de claims tipados.
"""

import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from pydantic import SecretStr, ValidationError

from app.core.config import settings
from app.schemas.token import TokenPayload, TokenResponse, TokenType
from app.schemas.user import UserRole

__all__ = [
    "SecurityError",
    "TokenSecurityError",
    "InvalidTokenError",
    "ExpiredTokenError",
    "get_password_hash",
    "verify_password",
    "create_access_token",
    "create_refresh_token",
    "create_token_pair",
    "decode_token",
]


class SecurityError(Exception):
    """Clase base para excepciones de seguridad en InvestAI."""

    pass


class TokenSecurityError(SecurityError):
    """Clase base para errores de procesamiento o validación de tokens."""

    pass


class InvalidTokenError(TokenSecurityError):
    """Arrojada cuando un token es inválido, manipulado, corrupto o malformado."""

    pass


class ExpiredTokenError(TokenSecurityError):
    """Arrojada cuando un token criptográfico ha expirado."""

    pass


def get_password_hash(password: str | SecretStr, rounds: int = 12) -> str:
    """
    Genera un hash criptográfico bcrypt seguro a partir de una contraseña plana o SecretStr.

    Reglas defensivas:
    - Valida que el tipo sea estrictamente `str` o `SecretStr`.
    - Rechaza contraseñas vacías o de sólo espacios si están vacías.
    - Rechaza contraseñas que contengan bytes nulos (\\x00).
    - Valida el límite estructural de bcrypt de 72 bytes en UTF-8 para prevenir ataques DoS.
    - Valida que el factor de costo `rounds` esté acotado entre 4 y 16 (default 12).
    - Retorna el hash serializado como string UTF-8.
    """
    if not isinstance(password, str | SecretStr):
        raise TypeError("Password must be a string or SecretStr")

    raw = password.get_secret_value() if isinstance(password, SecretStr) else password
    if not raw:
        raise ValueError("Password cannot be empty")

    password_bytes = raw.encode("utf-8")
    if b"\x00" in password_bytes:
        raise ValueError("Password cannot contain null bytes")

    if len(password_bytes) > 72:
        raise ValueError("Password exceeds 72-byte bcrypt limit")

    if not isinstance(rounds, int) or isinstance(rounds, bool) or rounds < 4 or rounds > 16:
        raise ValueError("Cost factor rounds must be between 4 and 16")

    salt = bcrypt.gensalt(rounds=rounds)
    hash_bytes = bcrypt.hashpw(password_bytes, salt)
    return hash_bytes.decode("utf-8")


def verify_password(plain_password: str | SecretStr, hashed_password: str) -> bool:
    """
    Verifica una contraseña contra un hash bcrypt en tiempo constante.

    Reglas defensivas:
    - Retorna False de forma segura ante tipos no válidos o cadenas vacías.
    - Retorna False ante contraseñas que excedan 72 bytes o contengan bytes nulos.
    - Captura cualquier excepción de decodificación o formato de hash devolviendo False,
      evitando la propagación de errores no controlados (500 Internal Server Error).
    """
    if (
        not isinstance(plain_password, str | SecretStr)
        or not isinstance(hashed_password, str)
        or not hashed_password
    ):
        return False

    raw = (
        plain_password.get_secret_value()
        if isinstance(plain_password, SecretStr)
        else plain_password
    )
    if not raw:
        return False

    try:
        plain_bytes = raw.encode("utf-8")
        hash_bytes = hashed_password.encode("utf-8")

        if b"\x00" in plain_bytes or len(plain_bytes) > 72:
            return False

        return bcrypt.checkpw(plain_bytes, hash_bytes)
    except Exception:
        return False


def create_access_token(
    subject: str | uuid.UUID,
    role: UserRole,
    email: str | None = None,
    expires_delta: timedelta | None = None,
    jti: str | None = None,
) -> str:
    """
    Genera y firma criptográficamente un Access Token JWT conforme a RFC 7519.

    Claims inyectados:
    - sub: Identificador del sujeto/usuario normalizado a string.
    - role: Rol RBAC del usuario.
    - type: Tipo canónico de token ('access').
    - iat / nbf: Marca de tiempo de emisión y validez (UTC epoch).
    - exp: Expiración acotada según configuración o delta específico.
    - jti: Identificador único global del token para trazabilidad y mitigación de repetición.
    - email: Opcional, normalizado en minúsculas.
    """
    sub_str = str(subject).strip()
    if not sub_str:
        raise ValueError("Subject (sub) cannot be empty")

    now = datetime.now(UTC)
    expire_duration = (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )

    payload = {
        "sub": sub_str,
        "role": role.value if isinstance(role, UserRole) else str(role),
        "type": TokenType.ACCESS.value,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int((now + expire_duration).timestamp()),
        "jti": jti or str(uuid.uuid4()),
    }

    if email:
        payload["email"] = email.strip().lower()

    return jwt.encode(
        payload,
        settings.JWT_SECRET_KEY.get_secret_value(),
        algorithm=settings.JWT_ALGORITHM,
    )


def create_refresh_token(
    subject: str | uuid.UUID,
    role: UserRole,
    email: str | None = None,
    expires_delta: timedelta | None = None,
    jti: str | None = None,
) -> str:
    """
    Genera y firma criptográficamente un Refresh Token JWT de ciclo extendido conforme a RFC 7519.

    Claims inyectados:
    - sub: Identificador del sujeto/usuario normalizado a string.
    - role: Rol RBAC del usuario.
    - type: Tipo canónico de token ('refresh').
    - iat / nbf: Marca de tiempo de emisión y validez (UTC epoch).
    - exp: Expiración acotada en días (default settings.REFRESH_TOKEN_EXPIRE_DAYS).
    - jti: Identificador único global independiente para revocación granular.
    - email: Opcional, normalizado en minúsculas.
    """
    sub_str = str(subject).strip()
    if not sub_str:
        raise ValueError("Subject (sub) cannot be empty")

    now = datetime.now(UTC)
    expire_duration = (
        expires_delta
        if expires_delta is not None
        else timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    )

    payload = {
        "sub": sub_str,
        "role": role.value if isinstance(role, UserRole) else str(role),
        "type": TokenType.REFRESH.value,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int((now + expire_duration).timestamp()),
        "jti": jti or str(uuid.uuid4()),
    }

    if email:
        payload["email"] = email.strip().lower()

    return jwt.encode(
        payload,
        settings.JWT_SECRET_KEY.get_secret_value(),
        algorithm=settings.JWT_ALGORITHM,
    )


def create_token_pair(
    subject: str | uuid.UUID,
    role: UserRole,
    email: str | None = None,
    access_expires_delta: timedelta | None = None,
    refresh_expires_delta: timedelta | None = None,
) -> TokenResponse:
    """
    Emisión atómica y coordinada de un par de tokens (Access Token + Refresh Token).
    Garantiza que ambos tokens posean identificadores criptográficos JTI independientes.
    """
    access_token = create_access_token(
        subject=subject,
        role=role,
        email=email,
        expires_delta=access_expires_delta,
    )
    refresh_token = create_refresh_token(
        subject=subject,
        role=role,
        email=email,
        expires_delta=refresh_expires_delta,
    )

    expires_in_seconds = (
        int(access_expires_delta.total_seconds())
        if access_expires_delta is not None
        else settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",  # noqa: S106  # OAuth2 token type, not a secret
        expires_in=expires_in_seconds,
    )


def decode_token(
    token: str,
    expected_type: TokenType | None = TokenType.ACCESS,
) -> TokenPayload:
    """
    Decodifica, valida criptográficamente y mapea un token JWT a un DTO TokenPayload.

    Garantías de seguridad:
    - Mitiga Algorithm Confusion exigiendo algoritmos explícitos (`[settings.JWT_ALGORITHM]`).
    - Valida presencia mandatoria de claims esenciales ('exp', 'iat', 'sub', 'type', 'jti').
    - Incorpora tolerancia de reloj (leeway=10 segundos).
    - Mapea de forma segura excepciones a tipos canónicos (ExpiredTokenError, InvalidTokenError).
    - Valida coincidencia de propósito/tipo de token (ej. TokenType.ACCESS o TokenType.REFRESH).
    """
    if not token or not isinstance(token, str) or not token.strip():
        raise InvalidTokenError("Token must be a non-empty string")

    try:
        decoded = jwt.decode(
            token.strip(),
            settings.JWT_SECRET_KEY.get_secret_value(),
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": ["exp", "iat", "sub", "type", "jti"]},
            leeway=10,
        )
    except jwt.ExpiredSignatureError as e:
        raise ExpiredTokenError("Token has expired") from e
    except jwt.PyJWTError as e:
        raise InvalidTokenError("Token is invalid or corrupted") from e

    try:
        payload = TokenPayload(
            sub=decoded["sub"],
            role=decoded["role"],
            type=decoded["type"],
            exp=datetime.fromtimestamp(decoded["exp"], tz=UTC),
            iat=datetime.fromtimestamp(decoded["iat"], tz=UTC),
            jti=decoded["jti"],
            email=decoded.get("email"),
        )
    except (ValidationError, ValueError, KeyError, TypeError, OSError, OverflowError) as e:
        raise InvalidTokenError("Token payload claims are malformed") from e

    if expected_type is not None and payload.type != expected_type:
        raise InvalidTokenError(
            f"Invalid token type: expected {expected_type.value}, got {payload.type.value}"
        )

    return payload
