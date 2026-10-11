"""
Re-exportación canónica del modelo UserModel para retrocompatibilidad.
La entidad relacional canónica reside en app.infrastructure.db.models.user.
"""
from app.infrastructure.db.models.user import UserModel

__all__ = ["UserModel"]
