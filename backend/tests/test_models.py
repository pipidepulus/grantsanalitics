"""
Unit tests for database models.
Tests model instantiation, relationships, and default values.
"""

import uuid
from datetime import datetime

from app.models.user import User
from app.models.project import Project
from app.models.document import GeneratedDoc
from app.models.call_spec import CallSpec
from app.models.conversation import Conversation, Message


class TestUserModel:
    def test_create_user(self, db):
        user = User(name="Ana", email="ana@test.com", organization="Org A")
        db.add(user)
        db.commit()
        db.refresh(user)

        assert user.id is not None
        assert user.name == "Ana"
        assert user.email == "ana@test.com"
        assert user.organization == "Org A"

    def test_user_unique_email(self, db):
        user1 = User(name="A", email="dup@test.com")
        db.add(user1)
        db.commit()

        user2 = User(name="B", email="dup@test.com")
        db.add(user2)
        try:
            db.commit()
            assert False, "Should have raised IntegrityError"
        except Exception:
            db.rollback()

    def test_user_optional_fields(self, db):
        user = User(name="Min", email="min@test.com")
        db.add(user)
        db.commit()
        db.refresh(user)

        assert user.organization is None
        assert user.sector is None
        assert user.territory is None
        assert user.preferences is None


class TestProjectModel:
    def test_create_project(self, db, sample_user):
        project = Project(user_id=sample_user.id, title="Mi Proyecto")
        db.add(project)
        db.commit()
        db.refresh(project)

        assert project.id is not None
        assert project.title == "Mi Proyecto"
        assert project.status == "draft"
        assert project.language == "es"
        assert project.cyrano_score is None

    def test_project_with_all_fields(self, db, sample_project):
        assert sample_project.problem_definition is not None
        assert sample_project.problem_tree is not None
        assert sample_project.objectives_tree is not None
        assert sample_project.value_chain is not None
        assert sample_project.timeline is not None
        assert sample_project.budget is not None

    def test_project_json_data(self, db, sample_user):
        project = Project(
            user_id=sample_user.id,
            title="JSON Test",
            json_data={"key": "value", "nested": {"a": 1}},
        )
        db.add(project)
        db.commit()
        db.refresh(project)

        assert project.json_data["key"] == "value"
        assert project.json_data["nested"]["a"] == 1


class TestCallSpecModel:
    def test_create_call_spec(self, db, sample_call_spec):
        assert sample_call_spec.title == "Convocatoria Test"
        assert sample_call_spec.max_amount == "500000"
        assert sample_call_spec.deadline == "2026-12-31"

    def test_call_spec_optional_fields(self, db):
        cs = CallSpec(title="Minimal Call")
        db.add(cs)
        db.commit()
        db.refresh(cs)

        assert cs.source_url is None
        assert cs.extracted_requirements is None


class TestGeneratedDocModel:
    def test_create_document(self, db, sample_project):
        doc = GeneratedDoc(
            project_id=sample_project.id,
            filename="test.docx",
            binary_file=b"fake_docx_bytes",
            version_number=1,
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

        assert doc.filename == "test.docx"
        assert doc.binary_file == b"fake_docx_bytes"
        assert doc.version_number == 1


class TestConversationModel:
    def test_create_conversation(self, db, sample_user):
        conv = Conversation(user_id=sample_user.id)
        db.add(conv)
        db.commit()
        db.refresh(conv)

        assert conv.id is not None
        assert conv.title == "Nueva conversación"

    def test_add_messages(self, db, sample_user):
        conv = Conversation(user_id=sample_user.id)
        db.add(conv)
        db.commit()

        msg1 = Message(conversation_id=conv.id, role="user", content="Hola")
        msg2 = Message(conversation_id=conv.id, role="assistant", content="¡Hola!")
        db.add_all([msg1, msg2])
        db.commit()

        db.refresh(conv)
        assert len(conv.messages) == 2
        assert conv.messages[0].role == "user"
        assert conv.messages[1].role == "assistant"

    def test_message_tool_calls(self, db, sample_user):
        conv = Conversation(user_id=sample_user.id)
        db.add(conv)
        db.commit()

        msg = Message(
            conversation_id=conv.id,
            role="assistant",
            content="Resultado",
            tool_calls={"tool": "search_funding_calls", "args": {"sector": "tech"}},
        )
        db.add(msg)
        db.commit()
        db.refresh(msg)

        assert msg.tool_calls["tool"] == "search_funding_calls"
