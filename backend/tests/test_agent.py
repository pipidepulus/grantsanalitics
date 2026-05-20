"""
Unit tests for AI agent service.
Tests agent orchestration logic with mocked OpenAI API.
"""

import json
import uuid
from unittest.mock import patch, MagicMock, AsyncMock

from app.services.ai_agent import (
    get_or_create_conversation,
    build_message_history,
    TOOL_HANDLERS,
)
from app.services.diagnostic import extract_cyrano_score as _extract_cyrano_score
from app.models.conversation import Conversation, Message


class TestGetOrCreateConversation:
    def test_creates_new_conversation(self, db, sample_user):
        conv = get_or_create_conversation(db, sample_user.id, None, None)
        assert conv.id is not None
        assert conv.user_id == sample_user.id

    def test_returns_existing_conversation(self, db, sample_user):
        conv1 = get_or_create_conversation(db, sample_user.id, None, None)
        conv2 = get_or_create_conversation(db, sample_user.id, conv1.id, None)
        assert conv1.id == conv2.id

    def test_creates_new_if_id_not_found(self, db, sample_user):
        fake_id = uuid.uuid4()
        conv = get_or_create_conversation(db, sample_user.id, fake_id, None)
        assert conv.id != fake_id

    def test_links_project(self, db, sample_user, sample_project):
        conv = get_or_create_conversation(db, sample_user.id, None, sample_project.id)
        assert conv.project_id == sample_project.id


class TestBuildMessageHistory:
    def test_empty_conversation(self, db, sample_user):
        conv = Conversation(user_id=sample_user.id)
        db.add(conv)
        db.commit()
        db.refresh(conv)

        history = build_message_history(conv)
        assert history == []

    def test_builds_correct_format(self, db, sample_user):
        conv = Conversation(user_id=sample_user.id)
        db.add(conv)
        db.commit()

        msg1 = Message(conversation_id=conv.id, role="user", content="Hola")
        msg2 = Message(conversation_id=conv.id, role="assistant", content="¡Hola!")
        db.add_all([msg1, msg2])
        db.commit()
        db.refresh(conv)

        history = build_message_history(conv)
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "Hola"
        assert history[1]["role"] == "assistant"


class TestExtractCyranoScore:
    def test_extracts_score_from_puntaje_total(self):
        text = "El puntaje total: 87.5 puntos sobre 100"
        assert _extract_cyrano_score(text) == 87.5

    def test_extracts_score_from_slash_100(self):
        text = "La evaluación resultó en 92.3/100"
        assert _extract_cyrano_score(text) == 92.3

    def test_extracts_score_from_puntos(self):
        text = "El proyecto obtuvo 95.5 puntos"
        assert _extract_cyrano_score(text) == 95.5

    def test_returns_none_for_no_score(self):
        text = "El proyecto necesita mejoras significativas."
        assert _extract_cyrano_score(text) is None

    def test_ignores_out_of_range(self):
        text = "El valor es 150 puntos"  # > 100
        assert _extract_cyrano_score(text) is None

    def test_extracts_puntaje_final(self):
        text = "Puntaje final: 96.2"
        assert _extract_cyrano_score(text) == 96.2


class TestToolHandlers:
    def test_all_handlers_registered(self):
        expected = [
            "search_funding_calls",
            "extract_requirements",
            "calculate_budget",
            "generate_word_document",
            "run_diagnostic",
        ]
        for name in expected:
            assert name in TOOL_HANDLERS, f"Handler '{name}' not registered"
