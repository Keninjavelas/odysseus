import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import ActionCandidate, Base, Document, Note, Session
from routes import action_routes
from routes.research import research_routes
from routes import studio_routes
from services.studio.compiler import compile_subtitles, save_timeline


@pytest.fixture
def action_db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Session.__table__, ActionCandidate.__table__, Note.__table__,
                                             Document.__table__])
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


def test_note_task_extraction_is_reviewable_deduplicated_and_project_scoped(action_db):
    alice = SimpleNamespace(owner="alice")
    bob = SimpleNamespace(owner="bob")
    with action_db() as db:
        db.add(Note(id="meeting", owner="alice", project_id="film", title="Review notes",
                    note_type="note", archived=False,
                    content="Context only\nTODO: Send review link\n- [ ] Book color session\nAction: Send review link",
                    items='[{"text":"Check subtitles","done":false},{"text":"Done item","done":true}]'))
        db.add(Note(id="film-list", owner="alice", project_id="film", title="Film tasks",
                    note_type="checklist", items="[]", archived=False))
        db.add(Note(id="other-list", owner="alice", title="General tasks",
                    note_type="checklist", items="[]", archived=False))
        db.commit()
    proposed = action_routes.propose_actions_from_note(alice, "meeting")
    assert [item["title"] for item in proposed["created"]] == [
        "Send review link", "Book color session", "Check subtitles"]
    assert proposed["source_url"] == "/#open=notes&note=meeting"
    assert proposed["created"][0]["source_excerpt"].startswith("Line 2:")
    repeated = action_routes.propose_actions_from_note(alice, "meeting")
    assert repeated["created"] == [] and repeated["skipped"] == 3
    with pytest.raises(HTTPException) as denied:
        action_routes.propose_actions_from_note(bob, "meeting")
    assert denied.value.status_code == 404
    proposal_id = proposed["created"][0]["id"]
    with pytest.raises(HTTPException) as wrong_project:
        action_routes.accept_action(alice, proposal_id, action_routes.AcceptInput(note_id="other-list"))
    assert wrong_project.value.status_code == 409
    accepted = action_routes.accept_action(alice, proposal_id,
                                           action_routes.AcceptInput(note_id="film-list"))
    assert accepted["status"] == "accepted"


def test_document_task_extraction_links_source_and_keeps_project(action_db):
    alice = SimpleNamespace(owner="alice")
    bob = SimpleNamespace(owner="bob")
    with action_db() as db:
        db.add(Document(id="brief", owner="alice", project_id="film", is_active=True,
                        title="Production brief", current_content=(
                            "Overview\nNext step: Review rough cut\n- [ ] Approve music license\n"
                            "Follow up: Review rough cut")))
        db.add(Note(id="film-list", owner="alice", project_id="film", title="Film tasks",
                    note_type="checklist", items="[]", archived=False))
        db.commit()
    result = action_routes.propose_actions_from_document(alice, "brief")
    assert [item["title"] for item in result["created"]] == [
        "Review rough cut", "Approve music license"]
    assert result["source_url"] == "/#document-brief"
    assert action_routes.propose_actions_from_document(alice, "brief")["skipped"] == 2
    with pytest.raises(HTTPException) as denied:
        action_routes.propose_actions_from_document(bob, "brief")
    assert denied.value.status_code == 404
    accepted = action_routes.accept_action(alice, result["created"][0]["id"],
                                           action_routes.AcceptInput(note_id="film-list"))
    assert accepted["status"] == "accepted"


def test_research_task_extraction_checks_owner_project_and_source(action_db, tmp_path, monkeypatch):
    monkeypatch.setattr(research_routes, "_research_storage_root", lambda: tmp_path)
    (tmp_path / "rp-one.json").write_text(json.dumps({
        "owner": "alice", "project_id": "film", "query": "Editing research",
        "raw_report": "Background only\nTODO: Confirm source rights\n- [ ] Request archive scan\n"
                      "Action: Confirm source rights", "result": "Next step: Ignore fallback",
    }), encoding="utf-8")
    alice = SimpleNamespace(owner="alice")
    bob = SimpleNamespace(owner="bob")
    with action_db() as db:
        db.add(Note(id="film-list", owner="alice", project_id="film", title="Film tasks",
                    note_type="checklist", items="[]", archived=False))
        db.add(Note(id="general-list", owner="alice", title="General tasks",
                    note_type="checklist", items="[]", archived=False))
        db.commit()
    result = action_routes.propose_actions_from_research(alice, "rp-one")
    assert [item["title"] for item in result["created"]] == [
        "Confirm source rights", "Request archive scan"]
    assert result["source_url"] == "/#research-rp-one"
    assert result["created"][0]["source_excerpt"].startswith("Line 2:")
    assert action_routes.propose_actions_from_research(alice, "rp-one")["skipped"] == 2
    with pytest.raises(HTTPException) as denied:
        action_routes.propose_actions_from_research(bob, "rp-one")
    assert denied.value.status_code == 404
    with pytest.raises(HTTPException) as denied:
        action_routes.create_action(bob, action_routes.CandidateInput(
            title="Read private report", source_kind="research", source_ref="rp-one"))
    assert denied.value.status_code == 404
    proposal_id = result["created"][0]["id"]
    with pytest.raises(HTTPException) as wrong_project:
        action_routes.accept_action(alice, proposal_id,
                                    action_routes.AcceptInput(note_id="general-list"))
    assert wrong_project.value.status_code == 409
    assert action_routes.accept_action(alice, proposal_id,
                                       action_routes.AcceptInput(note_id="film-list"))["status"] == "accepted"


def test_studio_transcript_actions_link_shots_and_recheck_source(action_db, tmp_path, monkeypatch):
    monkeypatch.setattr(studio_routes, "get_default_data_dir", lambda: tmp_path)
    alice = SimpleNamespace(owner="alice")
    bob = SimpleNamespace(owner="bob")
    timeline = compile_subtitles("Interview", (
        "1\n00:00:01,000 --> 00:00:03,000\nACTION: Send review link\n\n"
        "2\n00:00:03,000 --> 00:00:05,000\nTODO: Approve title card\n"))
    timeline["project_id"] = "film"
    directory = studio_routes._episode_dir("alice", timeline["episode_id"])
    save_timeline(timeline, directory)
    with action_db() as db:
        db.add(Note(id="film-list", owner="alice", project_id="film", title="Film tasks",
                    note_type="checklist", items="[]", archived=False))
        db.add(Note(id="general-list", owner="alice", title="General tasks",
                    note_type="checklist", items="[]", archived=False))
        db.commit()
    result = action_routes.propose_actions_from_studio(alice, timeline["episode_id"])
    assert [item["title"] for item in result["created"]] == ["Send review link", "Approve title card"]
    assert result["created"][0]["source_excerpt"].startswith("1.0–3.0s")
    assert json.loads(result["created"][0]["source_ref"])["shot_id"] == "shot-002"
    assert action_routes.propose_actions_from_studio(alice, timeline["episode_id"])["skipped"] == 2
    with pytest.raises(HTTPException) as denied:
        action_routes.propose_actions_from_studio(bob, timeline["episode_id"])
    assert denied.value.status_code == 404
    with pytest.raises(HTTPException) as wrong_project:
        action_routes.accept_action(alice, result["created"][0]["id"],
                                    action_routes.AcceptInput(note_id="general-list"))
    assert wrong_project.value.status_code == 409
    assert action_routes.accept_action(alice, result["created"][0]["id"],
                                       action_routes.AcceptInput(note_id="film-list"))["status"] == "accepted"
    timeline["tracks"]["narration"][2]["text"] = "No action here"
    save_timeline(timeline, directory)
    with pytest.raises(HTTPException) as stale:
        action_routes.accept_action(alice, result["created"][1]["id"],
                                    action_routes.AcceptInput(note_id="film-list"))
    assert stale.value.status_code == 409
