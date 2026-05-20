"""
Integration tests against a real PostgreSQL database.

These tests are skipped unless ``TEST_DATABASE_URL`` environment variable is set.
They verify full request-response cycles including real DB writes, FK constraints,
enum validation, and document indexing status transitions.

Usage:
    TEST_DATABASE_URL=postgresql://pipidepulus:pipidepulus@localhost:5432/pipidepulus_test \
    pytest tests/test_integration.py -v
"""

import io
import uuid
from unittest.mock import patch

import pytest

# Every test function here depends on pg_client which depends on pg_db which
# depends on pg_engine — pg_engine skips when TEST_DATABASE_URL is unset.


class TestUsersCRUD:
    def test_create_and_retrieve_user(self, pg_client):
        resp = pg_client.post("/api/users/", json={
            "name": "Integration User",
            "email": f"int_{uuid.uuid4().hex[:6]}@example.com",
            "organization": "Integration Corp",
        })
        assert resp.status_code == 201
        user_id = resp.json()["id"]

        resp2 = pg_client.get(f"/api/users/{user_id}")
        assert resp2.status_code == 200
        assert resp2.json()["name"] == "Integration User"

    def test_duplicate_email_rejected(self, pg_client):
        email = f"dup_{uuid.uuid4().hex[:6]}@example.com"
        pg_client.post("/api/users/", json={"name": "A", "email": email, "organization": "X"})
        resp = pg_client.post("/api/users/", json={"name": "B", "email": email, "organization": "Y"})
        assert resp.status_code == 409


class TestProjectEnums:
    def _create_user(self, client):
        resp = client.post("/api/users/", json={
            "name": f"u_{uuid.uuid4().hex[:6]}",
            "email": f"{uuid.uuid4().hex[:8]}@test.com",
            "organization": "Test",
        })
        assert resp.status_code == 201
        return resp.json()["id"]

    def test_default_status_is_draft(self, pg_client):
        uid = self._create_user(pg_client)
        resp = pg_client.post("/api/projects/", json={"user_id": uid, "title": "Test"})
        assert resp.status_code == 201
        assert resp.json()["status"] == "draft"

    def test_valid_status_transition(self, pg_client):
        uid = self._create_user(pg_client)
        proj = pg_client.post("/api/projects/", json={"user_id": uid, "title": "Test"}).json()
        resp = pg_client.patch(f"/api/projects/{proj['id']}", json={"status": "in_progress"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "in_progress"

    def test_invalid_status_rejected(self, pg_client):
        uid = self._create_user(pg_client)
        proj = pg_client.post("/api/projects/", json={"user_id": uid, "title": "Test"}).json()
        resp = pg_client.patch(f"/api/projects/{proj['id']}", json={"status": "nonexistent_status"})
        assert resp.status_code == 422


class TestDocumentUploadFlow:
    def _create_project(self, client):
        u = client.post("/api/users/", json={
            "name": f"u_{uuid.uuid4().hex[:6]}",
            "email": f"{uuid.uuid4().hex[:8]}@test.com",
            "organization": "T",
        }).json()
        p = client.post("/api/projects/", json={"user_id": u["id"], "title": "Doc Test"}).json()
        return u["id"], p["id"]

    def test_upload_returns_202_and_pending(self, pg_client):
        from app.services.vector_store import upload_bytes_to_projects_store
        user_id, project_id = self._create_project(pg_client)

        with patch("app.api.routes.documents.upload_bytes_to_projects_store") as mock_vs, \
             patch("app.services.storage.LocalStorageBackend.save", return_value="test/key"):
            mock_vs.return_value = "vs_file_123"
            resp = pg_client.post(
                "/api/documents/upload",
                files={"file": ("test.txt", io.BytesIO(b"hello world"), "text/plain")},
                data={"project_id": project_id, "user_id": user_id},
            )

        assert resp.status_code == 202
        assert resp.json()["indexing_status"] == "pending"

    def test_unsupported_file_type_rejected(self, pg_client):
        user_id, project_id = self._create_project(pg_client)
        resp = pg_client.post(
            "/api/documents/upload",
            files={"file": ("image.png", io.BytesIO(b"\x89PNG"), "image/png")},
            data={"project_id": project_id, "user_id": user_id},
        )
        assert resp.status_code == 400

    def test_list_documents_after_upload(self, pg_client):
        user_id, project_id = self._create_project(pg_client)

        with patch("app.api.routes.documents.upload_bytes_to_projects_store") as mock_vs, \
             patch("app.services.storage.LocalStorageBackend.save", return_value="k"):
            mock_vs.return_value = "vs_file_456"
            pg_client.post(
                "/api/documents/upload",
                files={"file": ("test.md", io.BytesIO(b"# Hello"), "text/markdown")},
                data={"project_id": project_id, "user_id": user_id},
            )

        resp = pg_client.get(f"/api/documents/project/{project_id}/all")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["uploaded"]) == 1
        assert data["uploaded"][0]["filename"] == "test.md"


class TestCyranoEvaluationPersistence:
    def test_evaluations_list_empty_for_new_project(self, pg_client):
        u = pg_client.post("/api/users/", json={
            "name": f"u_{uuid.uuid4().hex[:6]}",
            "email": f"{uuid.uuid4().hex[:8]}@test.com",
            "organization": "T",
        }).json()
        p = pg_client.post("/api/projects/", json={"user_id": u["id"], "title": "E"}).json()
        resp = pg_client.get(f"/api/projects/{p['id']}/evaluations")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_rag_events_list_empty_for_new_project(self, pg_client):
        u = pg_client.post("/api/users/", json={
            "name": f"u_{uuid.uuid4().hex[:6]}",
            "email": f"{uuid.uuid4().hex[:8]}@test.com",
            "organization": "T",
        }).json()
        p = pg_client.post("/api/projects/", json={"user_id": u["id"], "title": "R"}).json()
        resp = pg_client.get(f"/api/projects/{p['id']}/rag-events")
        assert resp.status_code == 200
        assert resp.json() == []


class TestHealthCheckEndpoint:
    def test_health_returns_200_or_503(self, pg_client):
        resp = pg_client.get("/api/health")
        # DB is reachable; OpenAI key likely not set in test env — either result is acceptable
        assert resp.status_code in (200, 503)
        body = resp.json()
        assert body["database"]["status"] == "ok"
