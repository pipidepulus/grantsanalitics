"""
Integration tests for API routes.
Tests CRUD operations through the FastAPI TestClient.
"""

import json
import uuid
from app.models.user import User
from app.models.project import Project


class TestUsersAPI:
    def test_create_user(self, client):
        resp = client.post("/api/users/", json={
            "name": "Test User",
            "email": "testuser@example.com",
            "organization": "Test Org",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Test User"
        assert data["email"] == "testuser@example.com"
        assert "id" in data

    def test_get_user(self, client, sample_user):
        resp = client.get(f"/api/users/{sample_user.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == sample_user.name

    def test_get_user_not_found(self, client):
        resp = client.get(f"/api/users/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_update_user(self, client, sample_user):
        resp = client.patch(f"/api/users/{sample_user.id}", json={
            "name": "Updated Name",
            "email": sample_user.email,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Updated Name"


class TestProjectsAPI:
    def test_create_project(self, client, sample_user):
        resp = client.post("/api/projects/", json={
            "user_id": str(sample_user.id),
            "title": "Nuevo Proyecto",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Nuevo Proyecto"
        assert data["status"] == "draft"

    def test_list_projects(self, client, sample_user, sample_project):
        resp = client.get(f"/api/projects/?user_id={sample_user.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_get_project(self, client, sample_project):
        resp = client.get(f"/api/projects/{sample_project.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == sample_project.title

    def test_get_project_not_found(self, client):
        resp = client.get(f"/api/projects/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_update_project(self, client, sample_project):
        resp = client.patch(f"/api/projects/{sample_project.id}", json={
            "title": "Updated Title",
            "status": "in_progress",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Updated Title"
        assert data["status"] == "in_progress"

    def test_update_project_methodology(self, client, sample_project):
        resp = client.patch(f"/api/projects/{sample_project.id}", json={
            "problem_definition": "Nuevo problema definido",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["problem_definition"] == "Nuevo problema definido"


class TestDocumentsAPI:
    def test_list_documents_empty(self, client, sample_project):
        resp = client.get(f"/api/documents/project/{sample_project.id}")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_download_not_found(self, client):
        resp = client.get(f"/api/documents/{uuid.uuid4()}/download")
        assert resp.status_code == 404


class TestCallSpecsAPI:
    def test_create_call_spec(self, client):
        resp = client.post("/api/calls/", json={
            "title": "New Call",
            "max_amount": "1000000",
            "deadline": "2026-06-30",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "New Call"

    def test_list_call_specs(self, client, sample_call_spec):
        resp = client.get("/api/calls/")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_get_call_spec(self, client, sample_call_spec):
        resp = client.get(f"/api/calls/{sample_call_spec.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Convocatoria Test"


class TestChatAPI:
    def test_post_chat_requires_fields(self, client):
        resp = client.post("/api/chat/", json={})
        assert resp.status_code == 422

    def test_get_conversations(self, client, sample_user):
        resp = client.get(f"/api/chat/conversations/{sample_user.id}")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestHealthCheck:
    def test_health(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"
