"""
Unit tests for function tools (tools.py).
Tests tool handlers in isolation with mocked dependencies.
"""

import json
import uuid
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock

from app.services.tools import (
    handle_search_funding_calls,
    handle_extract_requirements,
    handle_calculate_budget,
    handle_generate_word_document,
    handle_run_diagnostic,
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
    @patch("app.services.tools.AsyncOpenAI")
    def test_returns_results(self, mock_openai_cls):
        # Mock the AsyncOpenAI response with web search results
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_content = MagicMock()
        mock_content.type = "output_text"
        mock_content.text = "Convocatoria de agricultura - Colombia 2024"
        mock_message = MagicMock()
        mock_message.type = "message"
        mock_message.content = [mock_content]
        mock_response = MagicMock()
        mock_response.output = [mock_message]
        mock_client.responses.create = AsyncMock(return_value=mock_response)

        result = json.loads(asyncio.run(handle_search_funding_calls({
            "sector": "agricultura",
            "territory": "Colombia",
            "keywords": None,
        })))

        assert result["status"] == "success"
        assert "results" in result

    @patch("app.services.tools.AsyncOpenAI")
    def test_no_results(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_response.output = []
        mock_client.responses.create = AsyncMock(return_value=mock_response)

        result = json.loads(asyncio.run(handle_search_funding_calls({
            "sector": "espacial",
            "territory": "Marte",
            "keywords": None,
        })))

        assert result["status"] == "no_results"

    @patch("app.services.tools.AsyncOpenAI")
    def test_handles_error(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.responses.create = AsyncMock(side_effect=Exception("API error"))

        result = json.loads(asyncio.run(handle_search_funding_calls({
            "sector": "salud",
            "territory": "México",
            "keywords": "oncología",
        })))

        assert result["status"] == "error"


class TestExtractRequirements:
    def test_returns_ready_status(self, db):
        result = json.loads(handle_extract_requirements({
            "document_text": "Este es un documento de convocatoria de prueba con requisitos.",
            "call_spec_id": "some-id",
        }, db))

        assert result["status"] == "ready"
        assert result["document_length"] > 0
        assert result["call_spec_id"] == "some-id"

    def test_without_call_spec_id(self, db):
        result = json.loads(handle_extract_requirements({
            "document_text": "Texto",
        }, db))

        assert result["status"] == "ready"
        assert result["call_spec_id"] is None


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
            "admin_cap_percent": 7,  # Admin is 16.7%
            "project_id": str(sample_project.id),
        }, db))

        assert result["status"] == "issues_found"
        assert any("administrativos" in issue for issue in result["issues"])

    def test_unlinked_items(self, db, sample_project):
        items = json.dumps([
            {"rubro": "Personal", "monto": 50000},  # No actividad_vinculada
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
        """Low score should generate a draft, not block."""
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
        """No score set = draft document."""
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
