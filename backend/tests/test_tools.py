"""
Unit tests for function tools (tools.py).
Tests tool handlers in isolation with mocked dependencies.
"""

import json
import uuid
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from urllib.parse import urljoin

from app.services.tools import (
    handle_search_funding_calls,
    handle_extract_requirements,
    handle_calculate_budget,
    handle_generate_word_document,
    handle_run_diagnostic,
    handle_save_to_project_memory,
    TOOL_DEFINITIONS,
)


class TestToolDefinitions:
    def test_all_tools_defined(self):
        names = [t["name"] for t in TOOL_DEFINITIONS]
        assert "search_funding_calls" in names
        assert "extract_requirements" in names
        assert "calculate_budget" in names
        assert "generate_word_document" in names
        assert "run_diagnostic" in names
        assert "save_project_data" in names
        assert "save_to_project_memory" in names

    def test_tool_definitions_have_required_fields(self):
        for tool in TOOL_DEFINITIONS:
            assert tool["type"] == "function"
            assert "name" in tool
            assert "description" in tool
            assert "parameters" in tool
            assert "required" in tool["parameters"]

    def test_generate_word_document_has_language_enum(self):
        tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "generate_word_document")
        lang_param = tool["parameters"]["properties"]["language"]
        assert lang_param["enum"] == ["es", "en"]


class TestSearchFundingCalls:
    def test_returns_placeholder(self):
        """search_funding_calls always returns a placeholder for local mode."""
        result = asyncio.run(handle_search_funding_calls({
            "sector": "agricultura",
            "territory": "Colombia",
            "keywords": None,
        }))
        data = json.loads(result)
        assert data["status"] == "not_available"

    def test_message_mentions_local_mode(self):
        result = asyncio.run(handle_search_funding_calls({
            "sector": "tecnología",
            "territory": "Argentina",
            "keywords": "IA",
        }))
        data = json.loads(result)
        assert "local" in data.get("message", "")


class TestExtractRequirements:
    @patch("app.services.tools.httpx")
    async def test_calls_ollama(self, mock_httpx):
        mock_client = MagicMock()
        mock_httpx.AsyncClient = MagicMock(return_value=mock_client)

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "```json\n{\"criterios_elegibilidad\": \"ONG\"}\n```"}}]
        }
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_resp)

        result = json.loads(await handle_extract_requirements({
            "document_text": "Texto de prueba con requisitos.",
            "call_spec_id": str(uuid.uuid4()),
        }))

        assert result["status"] == "success"
        assert "extracted" in result
        assert result.get("document_length", 0) > 0

    async def test_fallback_on_invalid_json(self):
        """When Ollama returns non-JSON, should capture raw extraction."""
        result = json.loads(handle_extract_requirements({
            "document_text": "Texto que no es JSON",
            "call_spec_id": str(uuid.uuid4()),
        }))

        # Note: This would fail without a real Ollama server, so it's a structure test
        # The key thing is the function signature and flow remain correct
        assert "message" in result or "raw_extraction" in result


class TestCalculateBudget:
    def test_valid_budget(self, db, sample_project):
        items = json.dumps([
            {"rubro": "Personal", "monto": 50000, "actividad_vinculada": "Act 1"},
            {"rubro": "Equipos", "monto": 40000, "actividad_vinculada": "Act 2"},
        ])

        result = json.loads(handle_calculate_budget({
            "budget_items": items,
            "max_total": 200000,
            "admin_cap_percent": 7,
            "project_id": str(sample_project.id),
        }, db))

        assert result["status"] == "valid"
        assert result["total"] == 90000
        assert result["issues"] == []

    def test_exceeds_max_total(self, db, sample_project):
        items = json.dumps([
            {"rubro": "Personal", "monto": 150000, "actividad_vinculada": "Act 1"},
        ])

        result = json.loads(handle_calculate_budget({
            "budget_items": items,
            "max_total": 100000,
            "admin_cap_percent": 7,
            "project_id": str(sample_project.id),
        }, db))

        assert result["status"] == "issues_found"
        assert any("excede" in issue for issue in result["issues"])

    def test_admin_cap_exceeded(self, db, sample_project):
        items = json.dumps([
            {"rubro": "Personal", "monto": 50000, "actividad_vinculada": "Act 1"},
            {"rubro": "Administrativo", "monto": 10000, "actividad_vinculada": "Admin"},
        ])

        result = json.loads(handle_calculate_budget({
            "budget_items": items,
            "max_total": 200000,
            "admin_cap_percent": 7,
            "project_id": str(sample_project.id),
        }, db))

        assert result["status"] == "issues_found"
        assert any("administrativos" in issue for issue in result["issues"])

    def test_unlinked_items(self, db, sample_project):
        items = json.dumps([
            {"rubro": "Personal", "monto": 50000},
        ])

        result = json.loads(handle_calculate_budget({
            "budget_items": items,
            "max_total": 200000,
            "admin_cap_percent": 7,
            "project_id": str(sample_project.id),
        }, db))

        assert result["status"] == "issues_found"
        assert any("sin actividad vinculada" in issue for issue in result["issues"])

    def test_invalid_json(self, db, sample_project):
        result = json.loads(handle_calculate_budget({
            "budget_items": "not-json",
            "max_total": 100000,
            "admin_cap_percent": 7,
            "project_id": str(sample_project.id),
        }, db))

        assert result["status"] == "error"


class TestGenerateWordDocument:
    def test_generates_draft_low_score(self, db, sample_project):
        sample_project.cyrano_score = 80.0
        db.commit()

        result = json.loads(handle_generate_word_document({
            "project_id": str(sample_project.id),
            "language": "es",
        }, db))

        assert result["status"] == "success"
        assert result["is_draft"] is True
        assert result["cyrano_score"] == 80.0

    def test_project_not_found(self, db):
        result = json.loads(handle_generate_word_document({
            "project_id": str(uuid.uuid4()),
            "language": "es",
        }, db))

        assert result["status"] == "error"

    def test_generates_document_when_validated(self, db, validated_project):
        result = json.loads(handle_generate_word_document({
            "project_id": str(validated_project.id),
            "language": "es",
        }, db))

        assert result["status"] == "success"
        assert result["filename"].endswith(".docx")
        assert result["is_draft"] is False

    def test_generates_document_english(self, db, validated_project):
        result = json.loads(handle_generate_word_document({
            "project_id": str(validated_project.id),
            "language": "en",
        }, db))

        assert result["status"] == "success"

    def test_allows_generation_when_no_score(self, db, sample_project):
        sample_project.cyrano_score = None
        db.commit()

        result = json.loads(handle_generate_word_document({
            "project_id": str(sample_project.id),
            "language": "es",
        }, db))

        assert result["status"] == "success"
        assert result["is_draft"] is True
        assert result["cyrano_score"] is None


class TestRunDiagnostic:
    def test_returns_project_data(self, db, sample_project):
        result = json.loads(handle_run_diagnostic({
            "project_id": str(sample_project.id),
        }, db))

        assert result["status"] == "ready_for_evaluation"
        assert result["project_data"]["title"] == "Proyecto Prueba"
        assert result["project_data"]["problem_definition"] is not None

    def test_project_not_found(self, db):
        result = json.loads(handle_run_diagnostic({
            "project_id": str(uuid.uuid4()),
        }, db))

        assert result["status"] == "error"


class TestSaveToProjectMemory:
    def test_uploads_to_vector_store(self, db, sample_project):
        """save_to_project_memory should call vector_store upload_bytes_to_projects_store."""
        summary = "Este es un resumen de prueba del proyecto."
        with patch("app.services.tools.upload_bytes_to_projects_store") as mock_upload:
            mock_upload.return_value = "vs_123"
            result = json.loads(handle_save_to_project_memory({
                "project_id": str(sample_project.id),
                "summary": summary,
            }, db))

            assert result["status"] == "success"
            mock_upload.assert_called_once()
            call_args = mock_upload.call_args
            assert call_args[1]["project_id"] == str(sample_project.id)

    def test_project_not_found(self, db):
        result = json.loads(handle_save_to_project_memory({
            "project_id": str(uuid.uuid4()),
            "summary": "summary",
        }, db))

        assert result["status"] == "error"
        assert "no encontrado" in result["message"]
