"""
Pruebas unitarias para el Universal Envelope y contratos de transporte (ARQ-02).
Valida inmutabilidad, sanitización de frontera (extra="forbid") y serialización de APIResponse y APIErrorResponse.
"""

import unittest
import uuid

from app.schemas.envelope import (
    APIErrorResponse,
    APIResponse,
    ErrorDetail,
    ResponseMeta,
    SubErrorDetail,
)
from pydantic import ValidationError


class TestEnvelopeSchemas(unittest.TestCase):
    """Suite de validación de invariantes para el Universal Envelope."""

    def test_api_response_serialization_success(self):
        """Valida que APIResponse[T] serialice correctamente la envoltura estándar."""
        req_id = str(uuid.uuid4())
        meta = ResponseMeta(request_id=req_id, execution_time_ms=12.5)
        payload = {"portfolio_id": 42, "status": "rebalanced"}

        response = APIResponse[dict](
            success=True,
            data=payload,
            meta=meta,
        )

        dump = response.model_dump(mode="json")
        self.assertTrue(dump["success"])
        self.assertEqual(dump["data"]["portfolio_id"], 42)
        self.assertEqual(dump["meta"]["request_id"], req_id)
        self.assertEqual(dump["meta"]["execution_time_ms"], 12.5)
        self.assertIn("timestamp", dump["meta"])

    def test_api_response_immutability(self):
        """Valida que los esquemas basados en BaseSchema sean inmutables (frozen=True)."""
        meta = ResponseMeta(request_id="test-req-123")
        response = APIResponse[str](
            success=True,
            data="información inmutable",
            meta=meta,
        )

        with self.assertRaises(ValidationError):
            # Intentar modificar un campo en un modelo frozen debe fallar
            response.success = False

        with self.assertRaises(ValidationError):
            response.data = "nuevo valor"

        with self.assertRaises(ValidationError):
            meta.request_id = "otro-id"

    def test_api_response_extra_forbid(self):
        """Valida que se rechacen campos no autorizados (extra='forbid')."""
        meta = ResponseMeta(request_id="req-1")

        with self.assertRaises(ValidationError):
            APIResponse[str](
                success=True,
                data="ok",
                meta=meta,
                extra_unauthorized_field="malicious_payload",
            )

        with self.assertRaises(ValidationError):
            ResponseMeta(
                request_id="req-2",
                unexpected_field="forbidden",
            )

    def test_api_error_response_structure(self):
        """Valida la taxonomía y anidamiento correcto de APIErrorResponse y SubErrorDetail."""
        req_id = str(uuid.uuid4())
        sub_errors = [
            SubErrorDetail(field="body.tickers", issue="El campo no puede estar vacío."),
            SubErrorDetail(field=None, issue="Error global de consistencia."),
        ]
        error_detail = ErrorDetail(
            code="VALIDATION_ERROR",
            message="Error en la validación de la solicitud.",
            details=sub_errors,
        )
        meta = ResponseMeta(request_id=req_id)

        error_response = APIErrorResponse(
            success=False,
            error=error_detail,
            meta=meta,
        )

        dump = error_response.model_dump(mode="json")
        self.assertFalse(dump["success"])
        self.assertEqual(dump["error"]["code"], "VALIDATION_ERROR")
        self.assertEqual(len(dump["error"]["details"]), 2)
        self.assertEqual(dump["error"]["details"][0]["field"], "body.tickers")
        self.assertIsNone(dump["error"]["details"][1]["field"])
        self.assertEqual(dump["meta"]["request_id"], req_id)

    def test_api_error_response_immutability_and_extra_forbid(self):
        """Valida inmutabilidad y rechazo de campos extra en APIErrorResponse y ErrorDetail."""
        sub_err = SubErrorDetail(field="test", issue="falló")
        err_detail = ErrorDetail(code="ERR_01", message="Mensaje", details=[sub_err])
        meta = ResponseMeta(request_id="req-3")

        error_resp = APIErrorResponse(success=False, error=err_detail, meta=meta)

        with self.assertRaises(ValidationError):
            error_resp.success = True

        with self.assertRaises(ValidationError):
            err_detail.code = "OTRO"

        with self.assertRaises(ValidationError):
            ErrorDetail(code="ERR_02", message="Msg", unauthorized_attr="hacker")

        with self.assertRaises(ValidationError):
            SubErrorDetail(field="x", issue="y", extra_attr="no")


if __name__ == "__main__":
    unittest.main()
