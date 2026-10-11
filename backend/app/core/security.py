"""
Servicio criptográfico defensivo y gestión de secretos (Módulo 5.1 - Fase 2).
Implementación directa sobre la biblioteca nativa `bcrypt` (sin passlib),
con soporte para pydantic.SecretStr, mitigación de ataques DoS (límite 72 bytes),
rechazo de bytes nulos y verificación en tiempo constante.
"""
from typing import Union
import bcrypt
from pydantic import SecretStr

__all__ = [
    "get_password_hash",
    "verify_password",
]


def get_password_hash(password: Union[str, SecretStr], rounds: int = 12) -> str:
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
    if not isinstance(password, (str, SecretStr)):
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


def verify_password(plain_password: Union[str, SecretStr], hashed_password: str) -> bool:
    """
    Verifica una contraseña contra un hash bcrypt en tiempo constante.

    Reglas defensivas:
    - Retorna False de forma segura ante tipos no válidos o cadenas vacías.
    - Retorna False ante contraseñas que excedan 72 bytes o contengan bytes nulos.
    - Captura cualquier excepción de decodificación o formato de hash devolviendo False,
      evitando la propagación de errores no controlados (500 Internal Server Error).
    """
    if not isinstance(plain_password, (str, SecretStr)) or not isinstance(hashed_password, str) or not hashed_password:
        return False

    raw = plain_password.get_secret_value() if isinstance(plain_password, SecretStr) else plain_password
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

