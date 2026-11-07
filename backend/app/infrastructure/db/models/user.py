"""
Modelo relacional de usuario e identidad (Módulo 5.1 - Fase 1).
Entidad persistente con control de acceso basado en roles (RBAC),
UUID nativo, hashing de credenciales y auditoría temporal.
"""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.core.database import Base
from app.schemas.user import UserRole

if TYPE_CHECKING:
    from app.models.portfolio import PortfolioModel


class GUID(TypeDecorator):
    """
    Tipo de columna UUID agnóstico de plataforma con fallback robusto a String(36).
    Garantiza compatibilidad con SQLite (evitando AttributeError en parámetros string)
    mientras preserva la hidratación a objetos nativos uuid.UUID en Python.
    """

    impl = String(36)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if isinstance(value, uuid.UUID):
            return str(value)
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        if isinstance(value, uuid.UUID):
            return value
        try:
            return uuid.UUID(str(value))
        except (ValueError, AttributeError):
            return value


class UserModel(Base):
    """
    Entidad relacional de usuario en la base de datos.
    Soporta autenticación segura, RBAC y relaciones patrimoniales.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        primary_key=True,
        default=uuid.uuid4,
    )
    email: Mapped[str] = mapped_column(
        String(254),
        unique=True,
        index=True,
        nullable=False,
    )
    hashed_password: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    full_name: Mapped[str] = mapped_column(
        String(100),
        default="InvestAI User",
        server_default="InvestAI User",
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
        nullable=False,
    )
    role: Mapped[UserRole] = mapped_column(
        SQLEnum(UserRole, native_enum=False, length=20),
        default=UserRole.VIEWER,
        server_default=UserRole.VIEWER.value,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    # Campos de compatibilidad con modelo legado y gestión patrimonial
    investor_profile: Mapped[str] = mapped_column(
        String(50),
        default="MODERATE",
        server_default="MODERATE",
        nullable=False,
    )

    portfolios: Mapped[list["PortfolioModel"]] = relationship(
        "PortfolioModel",
        back_populates="user",
        cascade="all, delete-orphan",
    )
