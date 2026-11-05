"""Project assignment never crosses account ownership boundaries."""

import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.database import Base, Document, Note, Project, Session
from routes import project_routes
from routes.research import research_routes


@pytest.fixture
def project_db(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[Project.__table__, Session.__table__, Note.__table__,
                                             Document.__table__])
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(project_routes, "SessionLocal", factory)
    monkeypatch.setattr(project_routes, "effective_user", lambda request: request.owner)
    monkeypatch.setattr(research_routes, "_research_storage_root", lambda: tmp_path)
    yield factory
    engine.dispose()


def test_project_membership_is_owner_scoped(project_db, tmp_path):
    alice = SimpleNamespace(owner="alice")
    bob = SimpleNamespace(owner="bob")
    created = project_routes.create_project(alice, project_routes.ProjectInput(name="Film edit"))
    with project_db() as db:
        db.add(Session(id="alice-chat", name="Edit", endpoint_url="", model="", owner="alice"))
        db.add(Session(id="bob-chat", name="Other", endpoint_url="", model="", owner="bob"))
        db.add(Note(id="alice-note", owner="alice", title="Notes", note_type="note"))
        db.add(Note(id="bob-note", owner="bob", title="Private", note_type="note"))
        db.add(Document(id="alice-doc", owner="alice", session_id="alice-chat",
                        title="Draft", current_content="Draft"))
        db.add(Document(id="bob-doc", owner="bob", session_id="bob-chat",
                        title="Private", current_content="Secret"))
        db.commit()

    with pytest.raises(HTTPException) as denied:
        project_routes.assign_session(bob, created["id"], "bob-chat")
    assert denied.value.status_code == 404
    with pytest.raises(HTTPException) as denied:
        project_routes.assign_session(alice, created["id"], "bob-chat")
    assert denied.value.status_code == 404

    assigned = project_routes.assign_session(alice, created["id"], "alice-chat")
    assert assigned["project_id"] == created["id"]
    with project_db() as db:
        assert db.get(Document, "alice-doc").project_id == created["id"]
    with pytest.raises(HTTPException):
        project_routes.assign_document(alice, created["id"], "bob-doc")
    assert project_routes.assign_document(alice, created["id"], "alice-doc")["project_id"] == created["id"]
    assert project_routes.assign_note(alice, created["id"], "alice-note")["project_id"] == created["id"]
    with pytest.raises(HTTPException):
        project_routes.assign_note(alice, created["id"], "bob-note")
    assert project_routes.list_projects(alice)[0]["session_count"] == 1
    assert project_routes.list_projects(alice)[0]["document_count"] == 1
    assert project_routes.list_projects(bob) == []

    for rid, owner in (("alice-report", "alice"), ("bob-report", "bob")):
        (tmp_path / f"{rid}.json").write_text(json.dumps({
            "owner": owner, "project_id": created["id"], "result": "Report",
        }), encoding="utf-8")

    project_routes.delete_project(alice, created["id"])
    assert json.loads((tmp_path / "alice-report.json").read_text(encoding="utf-8"))["project_id"] is None
    assert json.loads((tmp_path / "bob-report.json").read_text(encoding="utf-8"))["project_id"] == created["id"]
    with project_db() as db:
        assert db.get(Session, "alice-chat").project_id is None
        assert db.get(Session, "bob-chat").project_id is None
        assert db.get(Note, "alice-note").project_id is None
        assert db.get(Note, "bob-note").project_id is None
        assert db.get(Document, "alice-doc").project_id is None
        assert db.get(Document, "bob-doc").project_id is None


def test_document_project_migration_backfills_only_matching_owner(monkeypatch):
    from core import database

    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE sessions (id VARCHAR PRIMARY KEY, owner VARCHAR, project_id VARCHAR)"))
        connection.execute(text("CREATE TABLE documents (id VARCHAR PRIMARY KEY, owner VARCHAR, session_id VARCHAR)"))
        connection.execute(text("INSERT INTO sessions VALUES ('chat', 'alice', 'project-a')"))
        connection.execute(text("INSERT INTO documents VALUES ('mine', 'alice', 'chat')"))
        connection.execute(text("INSERT INTO documents VALUES ('foreign', 'bob', 'chat')"))
    monkeypatch.setattr(database, "engine", engine)
    database._migrate_add_document_project_id_column()
    with engine.connect() as connection:
        rows = dict(connection.execute(text("SELECT id, project_id FROM documents")).all())
    assert rows == {"mine": "project-a", "foreign": None}
    engine.dispose()


def test_document_library_project_filter(project_db, monkeypatch):
    from routes.document import document_routes

    with project_db() as db:
        db.add(Project(id="film", owner="alice", name="Film"))
        db.add(Document(id="film-doc", owner="alice", project_id="film",
                        title="Storyboard", current_content="Film notes", is_active=True))
        db.add(Document(id="other-doc", owner="alice", title="General",
                        current_content="Other notes", is_active=True))
        db.add(Document(id="bob-doc", owner="bob", project_id="film", title="Private",
                        current_content="Secret", is_active=True))
        db.commit()
    monkeypatch.setattr(document_routes, "SessionLocal", project_db)
    monkeypatch.setattr(document_routes, "get_current_user", lambda request: "alice")
    app = FastAPI()
    app.include_router(document_routes.setup_document_routes(None))
    client = TestClient(app)
    film = client.get("/api/documents/library", params={"project_id": "film"})
    assert film.status_code == 200
    assert [item["id"] for item in film.json()["documents"]] == ["film-doc"]
    assert film.json()["languages"] == {"text": 1}
    unassigned = client.get("/api/documents/library", params={"project_id": ""})
    assert [item["id"] for item in unassigned.json()["documents"]] == ["other-doc"]
