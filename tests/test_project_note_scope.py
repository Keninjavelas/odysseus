import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import Base, Note, Project, Session
from src.tools.notes import do_manage_notes
from routes.note import note_routes


def test_agent_notes_follow_session_project(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Session.__table__, Note.__table__])
    factory = sessionmaker(bind=engine)
    import core.database as database
    monkeypatch.setattr(database, "SessionLocal", factory)
    with factory() as db:
        db.add_all([
            Session(id="chat-a", owner="alice", name="A", model="", endpoint_url="", project_id="project-a"),
            Session(id="chat-b", owner="alice", name="B", model="", endpoint_url="", project_id="project-b"),
            Note(id="note-a", owner="alice", project_id="project-a", title="A tasks",
                 note_type="checklist", items='[{"text":"A only","done":false}]', archived=False),
            Note(id="note-b", owner="alice", project_id="project-b", title="B tasks",
                 note_type="checklist", items='[{"text":"B only","done":false}]', archived=False),
        ])
        db.commit()

    def call(payload, session_id="chat-a"):
        return asyncio.run(do_manage_notes(json.dumps(payload), owner="alice", session_id=session_id))

    listed = call({"action": "list"})
    assert "A tasks" in listed["results"]
    assert "B tasks" not in listed["results"]
    assert call({"action": "view", "id": "note-b"})["exit_code"] == 1
    assert call({"action": "append_item", "id": "note-b", "text": "Cross project"})["exit_code"] == 1
    assert call({"action": "append_item", "id": "note-a", "text": "In project"})["exit_code"] == 0
    with factory() as db:
        assert len(json.loads(db.get(Note, "note-a").items)) == 2
        assert len(json.loads(db.get(Note, "note-b").items)) == 1
    engine.dispose()


def test_notes_api_validates_project_owner_and_filters_list(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Project.__table__, Session.__table__, Note.__table__])
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(note_routes, "SessionLocal", factory)
    monkeypatch.setattr(note_routes, "require_user", lambda request: request.owner)
    router = note_routes.setup_note_routes()
    create = next(route.endpoint for route in router.routes
                  if route.path == "/api/notes" and "POST" in route.methods)
    listing = next(route.endpoint for route in router.routes
                   if route.path == "/api/notes" and "GET" in route.methods)
    with factory() as db:
        db.add(Project(id="project-a", owner="alice", name="A"))
        db.commit()
    alice = SimpleNamespace(owner="alice")
    bob = SimpleNamespace(owner="bob")
    created = create(alice, note_routes.NoteCreate(title="A note", project_id="project-a"))
    assert created["project_id"] == "project-a"
    assert len(listing(alice, project_id="project-a")["notes"]) == 1
    assert listing(alice, project_id="")["notes"] == []
    with pytest.raises(HTTPException) as denied:
        create(bob, note_routes.NoteCreate(title="Cross account", project_id="project-a"))
    assert denied.value.status_code == 404
    engine.dispose()
