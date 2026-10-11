"""
Suite de pruebas unitarias para el servicio criptográfico defensivo (Módulo 5.1 - Fase 2).
Valida hashing y verificación con bcrypt nativo, soporte de SecretStr,
unicidad de salt, rechazo de tipos inválidos, cadenas vacías y bytes nulos,
límite estricto de 72 bytes UTF-8 (multibyte DoS boundary), manejo seguro de hashes corruptos
y validación de factor de costo (rounds).
"""
import unittest
import pytest
from pydantic import SecretStr

from app.core.security import get_password_hash, verify_password


@pytest.mark.unit
class TestSecurityCrypto(unittest.TestCase):
    """Pruebas unitarias para hashing de contraseñas y verificación con bcrypt."""

    def test_hashing_and_verification_plain_string(self):
        """Valida hashing y verificación exitosa utilizando cadenas de texto plano."""
        password = "SecurePassword123!"
        hashed = get_password_hash(password, rounds=4)

        self.assertIsInstance(hashed, str)
        self.assertTrue(hashed.startswith("$2b$04$"))
        self.assertTrue(verify_password(password, hashed))
        self.assertFalse(verify_password("WrongPassword123!", hashed))

    def test_hashing_and_verification_secret_str(self):
        """Valida que pydantic.SecretStr sea procesado de forma nativa e interoperable con str."""
        secret_pass = SecretStr("SecretToken#2026")
        hashed = get_password_hash(secret_pass, rounds=4)

        self.assertIsInstance(hashed, str)
        # Verificar con SecretStr
        self.assertTrue(verify_password(secret_pass, hashed))
        # Verificar con str plano equivalente
        self.assertTrue(verify_password("SecretToken#2026", hashed))
        # Verificar rechazo con SecretStr erróneo
        self.assertFalse(verify_password(SecretStr("WrongToken#2026"), hashed))

    def test_salt_uniqueness(self):
        """Valida que dos hashes para la misma contraseña utilicen salts criptográficos distintos."""
        password = "SamePasswordTwice"
        hash_1 = get_password_hash(password, rounds=4)
        hash_2 = get_password_hash(password, rounds=4)

        self.assertNotEqual(hash_1, hash_2)
        self.assertTrue(verify_password(password, hash_1))
        self.assertTrue(verify_password(password, hash_2))

    def test_invalid_type_raises_type_error(self):
        """Valida que cualquier tipo distinto de str o SecretStr arroje TypeError."""
        invalid_types = [12345, 12.34, ["pass"], {"pass": "word"}, None, True]
        for bad_input in invalid_types:
            with self.assertRaises(TypeError) as ctx:
                get_password_hash(bad_input, rounds=4)
            self.assertEqual(str(ctx.exception), "Password must be a string or SecretStr")

    def test_empty_password_raises_value_error(self):
        """Valida que contraseñas vacías arrojen ValueError."""
        with self.assertRaises(ValueError) as ctx:
            get_password_hash("", rounds=4)
        self.assertEqual(str(ctx.exception), "Password cannot be empty")

        with self.assertRaises(ValueError) as ctx:
            get_password_hash(SecretStr(""), rounds=4)
        self.assertEqual(str(ctx.exception), "Password cannot be empty")

    def test_null_bytes_handling(self):
        """Valida que bytes nulos sean rechazados en hashing y no verifiquen en verify_password."""
        with self.assertRaises(ValueError) as ctx:
            get_password_hash("password\x00leak", rounds=4)
        self.assertEqual(str(ctx.exception), "Password cannot contain null bytes")

        valid_hash = get_password_hash("normal_pass", rounds=4)
        self.assertFalse(verify_password("normal_pass\x00", valid_hash))
        self.assertFalse(verify_password(SecretStr("normal_pass\x00"), valid_hash))

    def test_utf8_multibyte_72_byte_boundary(self):
        """
        Valida rigurosamente la frontera de 72 bytes con caracteres UTF-8 multibyte.
        El emoji 🔒 ocupa exactamente 4 bytes en UTF-8.
        - 18 emojis = 72 bytes (debe procesarse correctamente).
        - 19 emojis = 76 bytes (debe arrojar ValueError en hash y retornar False en verify).
        """
        exact_72_multibyte = "🔒" * 18
        self.assertEqual(len(exact_72_multibyte.encode("utf-8")), 72)

        hashed = get_password_hash(exact_72_multibyte, rounds=4)
        self.assertTrue(verify_password(exact_72_multibyte, hashed))

        exceeding_76_multibyte = "🔒" * 19
        self.assertEqual(len(exceeding_76_multibyte.encode("utf-8")), 76)

        with self.assertRaises(ValueError) as ctx:
            get_password_hash(exceeding_76_multibyte, rounds=4)
        self.assertEqual(str(ctx.exception), "Password exceeds 72-byte bcrypt limit")

        # verify_password debe fallar de forma segura sin arrojar excepción
        self.assertFalse(verify_password(exceeding_76_multibyte, hashed))

    def test_ascii_72_byte_boundary(self):
        """Valida frontera de 72 bytes con caracteres ASCII."""
        exact_72_ascii = "A" * 72
        hashed = get_password_hash(exact_72_ascii, rounds=4)
        self.assertTrue(verify_password(exact_72_ascii, hashed))

        exceeding_73_ascii = "A" * 73
        with self.assertRaises(ValueError) as ctx:
            get_password_hash(exceeding_73_ascii, rounds=4)
        self.assertEqual(str(ctx.exception), "Password exceeds 72-byte bcrypt limit")

        self.assertFalse(verify_password(exceeding_73_ascii, hashed))

    def test_corrupted_or_invalid_hash_returns_false_safely(self):
        """Valida que hashes corruptos o entradas vacías/nulas retornen False sin excepciones 500."""
        valid_pass = "ValidPassword123!"
        valid_hash = get_password_hash(valid_pass, rounds=4)

        # Hashes no válidos o corruptos
        self.assertFalse(verify_password(valid_pass, "not_a_bcrypt_hash"))
        self.assertFalse(verify_password(valid_pass, ""))
        self.assertFalse(verify_password(valid_pass, "$2b$04$corrupted_short_payload"))
        self.assertFalse(verify_password(valid_pass, "$2b$99$invalid_rounds_specifier"))

        # Entradas vacías o tipos inválidos
        self.assertFalse(verify_password("", valid_hash))
        self.assertFalse(verify_password(SecretStr(""), valid_hash))
        self.assertFalse(verify_password(None, valid_hash))  # type: ignore
        self.assertFalse(verify_password(valid_pass, None))  # type: ignore
        self.assertFalse(verify_password(12345, valid_hash))  # type: ignore
        self.assertFalse(verify_password(valid_pass, 12345))  # type: ignore

    def test_cost_factor_rounds_validation(self):
        """Valida que cost factor rounds fuera de [4, 16] o de tipo inválido arroje ValueError."""
        # Menor a 4
        with self.assertRaises(ValueError) as ctx:
            get_password_hash("test_pass", rounds=3)
        self.assertEqual(str(ctx.exception), "Cost factor rounds must be between 4 and 16")

        # Mayor a 16
        with self.assertRaises(ValueError) as ctx:
            get_password_hash("test_pass", rounds=17)
        self.assertEqual(str(ctx.exception), "Cost factor rounds must be between 4 and 16")

        # Booleano o tipos no enteros
        with self.assertRaises(ValueError) as ctx:
            get_password_hash("test_pass", rounds=True)  # type: ignore
        self.assertEqual(str(ctx.exception), "Cost factor rounds must be between 4 and 16")

    def test_production_default_rounds_12(self):
        """
        Valida que el factor de costo por defecto sea 12 (estándar OWASP para bcrypt en producción).
        El prefijo del hash generado debe contener '$2b$12$' o '$2a$12$'.
        """
        password = "ProductionTestPass"
        hashed = get_password_hash(password)  # rounds omitido -> default=12

        self.assertTrue(
            hashed.startswith("$2b$12$") or hashed.startswith("$2a$12$"),
            f"Expected bcrypt hash with cost factor 12, got prefix: {hashed[:7]}",
        )
        self.assertTrue(verify_password(password, hashed))


if __name__ == "__main__":
    unittest.main()

