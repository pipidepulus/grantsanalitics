"""
Test fixtures and configuration.
Uses SQLite in-memory for fast isolated tests.
"""

import uuid
import pytest
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.database import Base, get_db
from app.main import app


# ─── In-memory SQLite for tests ───

TEST_ENGINE = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=TEST_ENGINE)


@pytest.fixture(autouse=True)
def setup_db():
    """Create all tables before each test & drop after."""
    Base.metadata.create_all(bind=TEST_ENGINE)
    yield
    Base.metadata.drop_all(bind=TEST_ENGINE)


@pytest.fixture
def db():
    """Database session for direct model tests."""
    session = TestSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db):
    """FastAPI test client with overridden DB dependency."""
    def _override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def sample_user(db):
    """Create a sample user in the test DB."""
    from app.models.user import User
    user = User(
        id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        name="Test User",
        email="test@example.com",
        organization="Test Org",
        sector="tecnología",
        territory="España",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def sample_project(db, sample_user):
    """Create a sample project in the test DB."""
    from app.models.project import Project
    project = Project(
        id=uuid.UUID("00000000-0000-0000-0000-000000000010"),
        user_id=sample_user.id,
        title="Proyecto Prueba",
        status="draft",
        language="es",
        problem_definition="Falta de acceso a agua potable en comunidades rurales.",
        problem_tree={
            "central_problem": "Falta de acceso a agua potable",
            "causes": ["Infraestructura deficiente", "Falta de inversión"],
            "effects": ["Enfermedades hídricas", "Migración rural"],
        },
        objectives_tree={
            "general": "Mejorar el acceso a agua potable en comunidades rurales",
            "specific": [
                "Construir 10 pozos de agua potable",
                "Capacitar a 200 familias en higiene",
            ],
        },
        value_chain={
            "items": [
                {
                    "actividad": "Construcción de pozos",
                    "producto": "10 pozos construidos",
                    "indicador": "Número de pozos",
                    "meta": "10",
                }
            ]
        },
        timeline={
            "activities": [
                {
                    "actividad": "Estudios de factibilidad",
                    "inicio": "2026-01",
                    "fin": "2026-03",
                    "responsable": "Equipo técnico",
                }
            ]
        },
        budget={
            "items": [
                {"rubro": "Personal", "monto": 50000, "actividad_vinculada": "Construcción de pozos"},
                {"rubro": "Equipos", "monto": 100000, "actividad_vinculada": "Construcción de pozos"},
            ],
            "total": 150000,
        },
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@pytest.fixture
def validated_project(db, sample_user):
    """Create a project with score >= 95.01 (validated)."""
    from app.models.project import Project
    project = Project(
        id=uuid.UUID("00000000-0000-0000-0000-000000000020"),
        user_id=sample_user.id,
        title="Proyecto Validado",
        status="validated",
        cyrano_score=96.5,
        language="es",
        problem_definition="Problema bien documentado con evidencia.",
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@pytest.fixture
def sample_call_spec(db):
    """Create a sample call spec in the test DB."""
    from app.models.call_spec import CallSpec
    call_spec = CallSpec(
        id=uuid.UUID("00000000-0000-0000-0000-000000000030"),
        title="Convocatoria Test",
        source_url="https://example.com/call",
        eligibility_criteria="ONG registrada",
        max_amount="500000",
        deadline="2026-12-31",
    )
    db.add(call_spec)
    db.commit()
    db.refresh(call_spec)
    return call_spec


# ─────────────────────────────────────────────────────────────────────────────
# PostgreSQL integration fixtures
# Activated only when TEST_DATABASE_URL env var is set.
# Usage:
#   TEST_DATABASE_URL=postgresql://pipidepulus:pipidepulus@localhost:5432/pipidepulus_test \
#   pytest tests/test_integration.py -v
# ─────────────────────────────────────────────────────────────────────────────

import os


@pytest.fixture(scope="session")
def pg_engine():
    """Create a real PostgreSQL engine for integration tests.
    
    Skips the entire session if TEST_DATABASE_URL is not set so that
    regular ``pytest`` runs remain fully in-memory and fast.
    """
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set — skipping PostgreSQL integration tests")

    from sqlalchemy import create_engine as _ce
    engine = _ce(url, pool_pre_ping=True)
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def pg_db(pg_engine):
    """Transactional database session for each integration test.

    Each test runs inside a rolled-back transaction so the DB state is
    clean after every test without needing to truncate tables.
    """
    from sqlalchemy.orm import sessionmaker as _sm
    connection = pg_engine.connect()
    transaction = connection.begin()
    PgSession = _sm(bind=connection, autocommit=False, autoflush=False)
    session = PgSession()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def pg_client(pg_db):
    """FastAPI TestClient backed by real PostgreSQL."""
    def _override():
        try:
            yield pg_db
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ─────────────────────────────────────────────────────────────────────────────
# ChromaDB testing fixtures
# ─────────────────────────────────────────────────────────────────────────────

import chromadb


@pytest.fixture
def chromadb_test_client():
    """In-memory ChromaDB for testing."""
    client = chromadb.EphemeralClient()
    yield client
    # Ephemeral auto-cleans


# ─────────────────────────────────────────────────────────────────────────────
# pgvector testing fixtures
# ─────────────────────────────────────────────────────────────────────────────

from sqlalchemy.orm import sessionmaker as _sm
from app.models.document import DocumentEmbedding


@pytest.fixture
def pgvector_test_engine():
    """Ephemeral pgvector table for testing."""
    from sqlalchemy import create_engine as _ce
    engine = _ce("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[DocumentEmbedding.__table__])
    Session = _sm(bind=engine)
    yield Session
    Base.metadata.drop_all(engine, tables=[DocumentEmbedding.__table__])
    engine.dispose()
