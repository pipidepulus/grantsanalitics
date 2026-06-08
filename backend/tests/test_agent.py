"""
Unit tests for AI agent service.
Tests agent orchestration logic with mocked Ollama API.
"""

import json
import uuid
from unittest.mock import patch, MagicMock, AsyncMock

from app.services.ai_agent import (
    get_or_create_conversation,
    build_message_history,
    build_local_search_tools,
    SEARCH_TOOL_HANDLERS,
    TOOL_HANDLERS,
    _parse_ollama_response,
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
        text = "El valor es 150 puntos"
        assert _extract_cyrano_score(text) is None

    def test_extracts_puntaje_final(self):
        text = "Puntaje final: 96.2"
        assert _extract_cyrano_score(text) == 96.2


class TestOllamaResponseParsing:
    def test_parses_plain_text(self):
        response = {
            "choices": [{"message": {"content": "Hola mundo"}}]
        }
        content, tool_calls, _ = _parse_ollama_response(response)
        assert content == "Hola mundo"
        assert tool_calls is None

    def test_parses_tool_calls(self):
        response = {
            "choices": [{
                "message": {
                    "content": "Voy a buscar",
                    "tool_calls": [{
                        "id": "call_abc",
                        "function": {"name": "retrieve_knowledge_base", "arguments": '{"query": "agua"}'}
                    }]
                }
            }]
        }
        content, tool_calls, _ = _parse_ollama_response(response)
        assert content == "Voy a buscar"
        assert tool_calls is not None
        assert len(tool_calls) == 1
        assert tool_calls[0]["name"] == "retrieve_knowledge_base"
        assert tool_calls[0]["arguments"]["query"] == "agua"

    def test_empty_choice_returns_error(self):
        response = {"choices": []}
        content, tool_calls, _ = _parse_ollama_response(response)
        assert content == "No se recibió respuesta del modelo."
        assert tool_calls is None


class TestBuildLocalSearchTools:
    def test_no_project_id_returns_one_tool(self):
        tools = build_local_search_tools(None)
        assert len(tools) == 1
        assert tools[0]["name"] == "retrieve_knowledge_base"

    def test_with_project_id_returns_two_tools(self):
        tools = build_local_search_tools(uuid.uuid4())
        assert len(tools) == 2
        names = [t["name"] for t in tools]
        assert "retrieve_knowledge_base" in names
        assert "retrieve_project_documents" in names

    def test_retrieve_kb_has_function_type(self):
        tools = build_local_search_tools(None)
        tool = tools[0]
        assert tool["type"] == "function"
        assert "query" in tool["parameters"]["required"]


# ─────────────────────────────────────────────────────────────────────────────
# Ollama response mock helpers (replaces OpenAI mocks)
# ─────────────────────────────────────────────────────────────────────

def make_ollama_text_response(text: str):
    """Build an Ollama /v1/chat/completions response with plain text."""
    return {
        "choices": [{
            "message": {
                "content": text,
            }
        }]
    }


def make_ollama_tool_then_text_response(
    tool_name: str, tool_args: dict, tool_output: str, final_text: str
):
    """Build a two-step mock: first response has tool_calls, second has text.

    Returns a list ``[first_response, second_response]`` — wire them as
    ``side_effect=[first_response, second_response]`` on the mock.
    """
    # First call: tool call
    first = {
        "choices": [{
            "message": {
                "content": "",
                "tool_calls": [{
                    "id": "call_tool",
                    "function": {"name": tool_name, "arguments": json.dumps(tool_args)},
                }]
            }]
        }]
    }

    # Second call: final text response
    second = make_ollama_text_response(final_text)
    return [first, second]
