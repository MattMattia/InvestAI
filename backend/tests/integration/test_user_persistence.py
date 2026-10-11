"""
Suite de pruebas de integración para persistencia relacional de usuarios (Módulo 5.1 - Fase 1).
Verifica ciclo de vida asíncrono con SQLite in-memory (aiosqlite),
defaults relacionales, restricciones de unicidad de email, mapeo canónico a UserResponse
y consultas por email y UUID.
"""
from datetime import datetime, timezone
import unittest
import uuid
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # Asegura registro de modelos relacionales
from app.core.database import Base
from app.infrastructure.db.models.user import UserModel
from app.schemas.user import UserResponse, UserRole


@pytest.mark.integration
class TestUserPersistenceIntegration(unittest.IsolatedAsyncioTestCase):
    """Pruebas de integración de persistencia relacional asíncrona de usuarios."""

    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        self.SessionLocal = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def test_user_creation_and_defaults_persistence(self) -> None:
        """Valida inserción, autogeneración de UUID, timestamps UTC y defaults relacionales."""
        async with self.SessionLocal() as session:
            new_user = UserModel(
                email="default.user@investai.com",
                hashed_password="bcrypt_hash_placeholder_123",
                full_name="Default Settings User",
            )
            session.add(new_user)
            await session.commit()
            user_id = new_user.id

        # Verificar en nueva sesión limpia
        async with self.SessionLocal() as session:
            stmt = select(UserModel).where(UserModel.id == user_id)
            result = await session.execute(stmt)
            persisted = result.scalar_one_or_none()

            self.assertIsNotNone(persisted)
            self.assertEqual(persisted.email, "default.user@investai.com")
            self.assertEqual(persisted.full_name, "Default Settings User")
            self.assertTrue(persisted.is_active)
            self.assertEqual(persisted.role, UserRole.VIEWER)
            self.assertIsInstance(persisted.id, uuid.UUID)
            self.assertIsInstance(persisted.created_at, datetime)
            self.assertIsInstance(persisted.updated_at, datetime)

    async def test_user_model_to_user_response_mapping(self) -> None:
        """Valida que un UserModel persistido se mapee de forma limpia y canónica a UserResponse."""
        async with self.SessionLocal() as session:
            user = UserModel(
                email="mapped.trader@investai.com",
                hashed_password="secret_argon_hash_xyz",
                full_name="Mapping Test Trader",
                role=UserRole.TRADER,
            )
            session.add(user)
            await session.commit()

            # Mapeo a DTO público
            response_dto = UserResponse.model_validate(user)

            self.assertEqual(response_dto.email, "mapped.trader@investai.com")
            self.assertEqual(response_dto.full_name, "Mapping Test Trader")
            self.assertEqual(response_dto.role, UserRole.TRADER)
            self.assertTrue(response_dto.is_active)
            self.assertIsInstance(response_dto.id, uuid.UUID)
            self.assertEqual(response_dto.id, user.id)
            self.assertEqual(response_dto.created_at.tzinfo, timezone.utc)
            self.assertEqual(response_dto.updated_at.tzinfo, timezone.utc)

            # Verificar que el DTO jamás contenga hash ni contraseña
            dto_dict = response_dto.model_dump()
            self.assertNotIn("hashed_password", dto_dict)
            self.assertNotIn("password", dto_dict)

    async def test_unique_email_constraint_violation(self) -> None:
        """Valida que insertar dos usuarios con el mismo email arroje IntegrityError."""
        email = "unique.investor@investai.com"

        # 1. Primer usuario se inserta con éxito
        async with self.SessionLocal() as session:
            u1 = UserModel(
                email=email,
                hashed_password="hash_user_1",
                full_name="Investor One",
            )
            session.add(u1)
            await session.commit()

        # 2. Segundo usuario con idéntico email viola la restricción única
        async with self.SessionLocal() as session:
            u2 = UserModel(
                email=email,
                hashed_password="hash_user_2",
                full_name="Investor Two Duplicate",
            )
            session.add(u2)
            with self.assertRaises(IntegrityError):
                await session.commit()

    async def test_case_insensitive_and_normalized_email_lookup(self) -> None:
        """Valida búsqueda insensible a mayúsculas utilizando funciones SQL estándar."""
        async with self.SessionLocal() as session:
            user = UserModel(
                email="alpha.trader@investai.com",
                hashed_password="hash_alpha_trader",
                full_name="Alpha Trader",
            )
            session.add(user)
            await session.commit()

        async with self.SessionLocal() as session:
            query_email = "  ALPHA.TRADER@INVESTAI.COM  ".strip().lower()
            stmt = select(UserModel).where(func.lower(UserModel.email) == query_email)
            result = await session.execute(stmt)
            found = result.scalar_one_or_none()

            self.assertIsNotNone(found)
            self.assertEqual(found.email, "alpha.trader@investai.com")
            self.assertEqual(found.full_name, "Alpha Trader")

    async def test_user_update_lifecycle(self) -> None:
        """Valida actualización de perfil y cambio de rol a ADMIN."""
        async with self.SessionLocal() as session:
            user = UserModel(
                email="admin.candidate@investai.com",
                hashed_password="initial_hashed_pw",
                full_name="Promoted User",
                role=UserRole.VIEWER,
            )
            session.add(user)
            await session.commit()
            user_id = user.id

        # Modificación
        async with self.SessionLocal() as session:
            stmt = select(UserModel).where(UserModel.id == user_id)
            result = await session.execute(stmt)
            target = result.scalar_one()

            target.role = UserRole.ADMIN
            target.full_name = "Super Admin User"
            await session.commit()

        # Comprobación de persistencia
        async with self.SessionLocal() as session:
            stmt = select(UserModel).where(UserModel.id == user_id)
            result = await session.execute(stmt)
            updated = result.scalar_one()

            self.assertEqual(updated.role, UserRole.ADMIN)
            self.assertEqual(updated.full_name, "Super Admin User")


if __name__ == "__main__":
    unittest.main()

