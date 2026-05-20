"""
End-to-end test: full user workflow.
Tests the complete flow: create user → create project → update methodology → run diagnostic → generate document.
External API calls (OpenAI) are mocked.
"""

import json
import uuid
from unittest.mock import patch, MagicMock

from app.models.project import Project


class TestE2EWorkflow:
    def test_full_project_lifecycle(self, client, db):
        """Test complete workflow from user creation to document generation."""

        # === Step 1: Create User ===
        resp = client.post("/api/users/", json={
            "name": "E2E Tester",
            "email": "e2e@test.com",
            "organization": "E2E Corp",
            "sector": "Tecnología",
            "territory": "España",
        })
        assert resp.status_code == 201
        user = resp.json()
        user_id = user["id"]

        # === Step 2: Create Project ===
        resp = client.post("/api/projects/", json={
            "user_id": user_id,
            "title": "Proyecto E2E",
        })
        assert resp.status_code == 201
        project = resp.json()
        project_id = project["id"]
        assert project["status"] == "draft"

        # === Step 3: Build methodology (problem definition through budget) ===
        methodology_update = {
            "problem_definition": "La falta de digitalización en PYMES rurales limita su acceso a mercados.",
            "problem_tree": {
                "central": "Brecha digital en PYMES rurales",
                "causes": ["Falta de infraestructura", "Baja formación digital", "Alto costo de soluciones"],
                "effects": ["Pérdida de competitividad", "Éxodo de talento joven", "Estancamiento económico"],
            },
            "objectives_tree": {
                "general": "Reducir la brecha digital en PYMES rurales en un 40% en 3 años",
                "specific": [
                    "Implementar plataformas de e-commerce en 100 PYMES",
                    "Capacitar a 500 empresarios en herramientas digitales",
                    "Establecer 10 puntos de conectividad rural",
                ],
            },
            "value_chain": {
                "activities": [
                    {"name": "Diagnóstico digital", "resources": ["Consultores", "Software de diagnóstico"]},
                    {"name": "Capacitación digital", "resources": ["Formadores", "Material didáctico"]},
                    {"name": "Implementación e-commerce", "resources": ["Desarrolladores", "Plataformas cloud"]},
                ],
                "indicators": [
                    {"name": "PYMES digitalizadas", "target": 100, "unit": "empresas"},
                    {"name": "Personas capacitadas", "target": 500, "unit": "personas"},
                ],
            },
            "timeline": {
                "phases": [
                    {"name": "Diagnóstico", "duration": "3 meses", "milestones": ["Informe diagnóstico"]},
                    {"name": "Capacitación", "duration": "6 meses", "milestones": ["Certificación participantes"]},
                    {"name": "Implementación", "duration": "9 meses", "milestones": ["100 PYMES activas"]},
                ],
            },
            "budget": {
                "items": [
                    {"rubro": "Personal técnico", "monto": 120000, "actividad_vinculada": "Diagnóstico digital"},
                    {"rubro": "Formación", "monto": 80000, "actividad_vinculada": "Capacitación digital"},
                    {"rubro": "Tecnología", "monto": 150000, "actividad_vinculada": "Implementación e-commerce"},
                    {"rubro": "Administrativo", "monto": 20000, "actividad_vinculada": "Gestión"},
                ],
                "total": 370000,
            },
        }

        resp = client.patch(f"/api/projects/{project_id}", json=methodology_update)
        assert resp.status_code == 200
        updated_project = resp.json()
        assert updated_project["problem_definition"] is not None
        assert updated_project["budget"]["total"] == 370000

        # === Step 4: Verify project data is consistent ===
        resp = client.get(f"/api/projects/{project_id}")
        assert resp.status_code == 200
        project_data = resp.json()
        assert project_data["problem_tree"]["central"] == "Brecha digital en PYMES rurales"
        assert len(project_data["objectives_tree"]["specific"]) == 3
        assert project_data["value_chain"]["indicators"][0]["target"] == 100

        # === Step 5: Set Cyrano score to passing (simulating diagnostic result) ===
        db_project = db.query(Project).filter(Project.id == uuid.UUID(project_id)).first()
        db_project.cyrano_score = 96.5
        db_project.status = "validated"
        db.commit()

        # === Step 6: Generate document ===
        from app.services.tools import handle_generate_word_document
        result = json.loads(handle_generate_word_document({
            "project_id": project_id,
            "language": "es",
        }, db))
        assert result["status"] == "success"
        assert result["filename"].endswith(".docx")

        # === Step 7: Verify document is listed ===
        resp = client.get(f"/api/documents/project/{project_id}")
        assert resp.status_code == 200
        docs = resp.json()
        assert len(docs) == 1
        assert docs[0]["version_number"] == 1

        # === Step 8: Download document ===
        doc_id = docs[0]["id"]
        resp = client.get(f"/api/documents/{doc_id}/download")
        assert resp.status_code == 200
        assert "application/vnd.openxmlformats-officedocument.wordprocessingml.document" in resp.headers["content-type"]

    def test_document_draft_below_threshold(self, client, db):
        """Test that document generation produces a draft when Cyrano score < 95.01."""

        # Create user and project
        resp = client.post("/api/users/", json={
            "name": "Block Tester",
            "email": "block@test.com",
        })
        user_id = resp.json()["id"]

        resp = client.post("/api/projects/", json={
            "user_id": user_id,
            "title": "Blocked Project",
            "problem_definition": "Test problem",
        })
        assert resp.status_code == 201
        project_id = resp.json()["id"]

        # Set failing score
        db_project = db.query(Project).filter(Project.id == uuid.UUID(project_id)).first()
        db_project.cyrano_score = 85.0
        db.commit()

        # Attempt document generation — should produce a draft
        from app.services.tools import handle_generate_word_document
        result = json.loads(handle_generate_word_document({
            "project_id": project_id,
            "language": "es",
        }, db))

        assert result["status"] == "success"
        assert result["is_draft"] is True
        assert result["cyrano_score"] == 85.0

    def test_call_spec_to_project_flow(self, client):
        """Test creating a call spec and linking it to project search."""

        # Create call spec
        resp = client.post("/api/calls/", json={
            "title": "Convocatoria Innovación Digital 2025",
            "max_amount": "500000",
            "deadline": "2025-12-31",
        })
        assert resp.status_code == 201
        call_data = resp.json()
        assert call_data["title"] == "Convocatoria Innovación Digital 2025"

        # Verify retrieval
        resp = client.get(f"/api/calls/{call_data['id']}")
        assert resp.status_code == 200
        assert resp.json()["max_amount"] == "500000"

    def test_conversation_persistence(self, client, sample_user):
        """Test that conversations are listed for a user."""
        resp = client.get(f"/api/chat/conversations/{sample_user.id}")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
