"""
Unit tests for prompts and configuration.
"""

from app.core.prompts import SYSTEM_PROMPT, CYRANO_DIAGNOSTIC_PROMPT, EXTRACT_REQUIREMENTS_PROMPT
from app.config import Settings


class TestSystemPrompt:
    def test_contains_role_section(self):
        assert "<role>" in SYSTEM_PROMPT
        assert "</role>" in SYSTEM_PROMPT

    def test_contains_intent_section(self):
        assert "<intent>" in SYSTEM_PROMPT
        assert "OBJECTIVE" in SYSTEM_PROMPT
        assert "SUCCESS_CRITERIA" in SYSTEM_PROMPT
        assert "CONSTRAINTS" in SYSTEM_PROMPT

    def test_contains_glossary(self):
        assert "<glossary>" in SYSTEM_PROMPT
        assert "Árbol de problemas" in SYSTEM_PROMPT
        assert "Cadena de valor" in SYSTEM_PROMPT
        assert "Contrapartida" in SYSTEM_PROMPT
        assert "Indicador" in SYSTEM_PROMPT

    def test_contains_methodology_steps(self):
        assert "Identificación del Problema" in SYSTEM_PROMPT
        assert "Árbol de Problemas" in SYSTEM_PROMPT
        assert "Establecimiento de Objetivos" in SYSTEM_PROMPT
        assert "Cadena de Valor" in SYSTEM_PROMPT
        assert "Cronograma" in SYSTEM_PROMPT
        assert "Presupuesto" in SYSTEM_PROMPT

    def test_contains_tools_section(self):
        assert "search_funding_calls" in SYSTEM_PROMPT
        assert "extract_requirements" in SYSTEM_PROMPT
        assert "calculate_budget" in SYSTEM_PROMPT
        assert "generate_word_document" in SYSTEM_PROMPT
        assert "run_diagnostic" in SYSTEM_PROMPT

    def test_contains_workflow_phases(self):
        assert "FASE DETECTA" in SYSTEM_PROMPT or "DETECTA" in SYSTEM_PROMPT
        assert "FASE CREA" in SYSTEM_PROMPT or "CREA" in SYSTEM_PROMPT
        assert "FASE VALIDA" in SYSTEM_PROMPT or "VALIDA" in SYSTEM_PROMPT

    def test_cyrano_threshold(self):
        assert "95.01" in SYSTEM_PROMPT
        assert "borradores" in SYSTEM_PROMPT.lower() or "borrador" in SYSTEM_PROMPT.lower()

    def test_bilingual_terms(self):
        assert "Problem Tree" in SYSTEM_PROMPT or "problem tree" in SYSTEM_PROMPT.lower()


class TestCyranoDiagnosticPrompt:
    def test_contains_evaluation_criteria(self):
        assert "Definición del Problema" in CYRANO_DIAGNOSTIC_PROMPT
        assert "Árbol de Problemas" in CYRANO_DIAGNOSTIC_PROMPT
        assert "Objetivos SMART" in CYRANO_DIAGNOSTIC_PROMPT
        assert "Cadena de Valor" in CYRANO_DIAGNOSTIC_PROMPT
        assert "Cronograma" in CYRANO_DIAGNOSTIC_PROMPT
        assert "Presupuesto" in CYRANO_DIAGNOSTIC_PROMPT

    def test_weights_defined(self):
        assert "15%" in CYRANO_DIAGNOSTIC_PROMPT
        assert "20%" in CYRANO_DIAGNOSTIC_PROMPT

    def test_threshold_rule(self):
        assert "95.01" in CYRANO_DIAGNOSTIC_PROMPT


class TestExtractRequirementsPrompt:
    def test_contains_extraction_categories(self):
        assert "elegibilidad" in EXTRACT_REQUIREMENTS_PROMPT.lower()
        assert "montos" in EXTRACT_REQUIREMENTS_PROMPT.lower()
        assert "contrapartidas" in EXTRACT_REQUIREMENTS_PROMPT.lower()
        assert "fechas" in EXTRACT_REQUIREMENTS_PROMPT.lower()


class TestSettings:
    def test_default_values(self):
        settings = Settings(
            OPENAI_API_KEY="test-key",
            OPENAI_VECTOR_STORE_ID="vs-1",
            OPENAI_PROJECTS_VECTOR_STORE_ID="vs-2",
        )
        assert settings.APP_NAME == "Pipidepulus AI"
        assert settings.CYRANO_THRESHOLD == 95.01
        assert settings.DEBUG is False

    def test_cors_origins(self):
        settings = Settings(
            OPENAI_API_KEY="test-key",
            OPENAI_VECTOR_STORE_ID="vs-1",
            OPENAI_PROJECTS_VECTOR_STORE_ID="vs-2",
        )
        assert "http://localhost:3000" in settings.CORS_ORIGINS
