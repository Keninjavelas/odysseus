import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import ActionCandidate, Base, Note
from routes import action_routes


@pytest.fixture
def action_db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[ActionCandidate.__table__, Note.__table__])
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(action_routes, "SessionLocal", factory)
    monkeypatch.setattr(action_routes, "effective_user", lambda request: request.owner)
    yield factory
    engine.dispose()


def test_action_review_keeps_source_and_checklist_owner_scoped(action_db):
    alice = SimpleNamespace(owner="alice")
    bob = SimpleNamespace(owner="bob")
    with action_db() as db:
        db.add(Note(id="alice-list", owner="alice", title="Production", note_type="checklist",
                    items='[{"text":"Existing","done":false}]', archived=False))
        db.add(Note(id="bob-list", owner="bob", title="Private", note_type="checklist",
                    items="[]", archived=False))
        db.commit()
    proposal = action_routes.create_action(alice, action_routes.CandidateInput(
        title="Send review link", source_kind="email", source_ref="mail-42",
        source_excerpt="Producer asks for a review link"))
    duplicate = action_routes.create_action(alice, action_routes.CandidateInput(
        title="Send review link", source_kind="email", source_ref="mail-42"))
    assert proposal["id"] == duplicate["id"]
    assert action_routes.list_actions(alice)[0]["source_ref"] == "mail-42"
    assert action_routes.list_actions(bob) == []
    with pytest.raises(HTTPException) as denied:
        action_routes.accept_action(alice, proposal["id"], action_routes.AcceptInput(note_id="bob-list"))
    assert denied.value.status_code == 404
    accepted = action_routes.accept_action(alice, proposal["id"],
                                           action_routes.AcceptInput(note_id="alice-list"))
    assert accepted["status"] == "accepted"
    with action_db() as db:
        assert json.loads(db.get(Note, "alice-list").items) == [
            {"text": "Existing", "done": False},
            {"text": "Send review link", "done": False},
        ]
    with pytest.raises(HTTPException) as denied:
        action_routes.reject_action(bob, proposal["id"])
    assert denied.value.status_code == 404
