"""Project assignment never crosses account ownership boundaries."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import Base, Project, Session
from routes import project_routes


@pytest.fixture
def project_db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Project.__table__, Session.__table__])
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(project_routes, "SessionLocal", factory)
    monkeypatch.setattr(project_routes, "effective_user", lambda request: request.owner)
    yield factory
    engine.dispose()


def test_project_membership_is_owner_scoped(project_db):
    alice = SimpleNamespace(owner="alice")
    bob = SimpleNamespace(owner="bob")
    created = project_routes.create_project(alice, project_routes.ProjectInput(name="Film edit"))
    with project_db() as db:
        db.add(Session(id="alice-chat", name="Edit", endpoint_url="", model="", owner="alice"))
        db.add(Session(id="bob-chat", name="Other", endpoint_url="", model="", owner="bob"))
        db.commit()

    with pytest.raises(HTTPException) as denied:
        project_routes.assign_session(bob, created["id"], "bob-chat")
    assert denied.value.status_code == 404
    with pytest.raises(HTTPException) as denied:
        project_routes.assign_session(alice, created["id"], "bob-chat")
    assert denied.value.status_code == 404

    assigned = project_routes.assign_session(alice, created["id"], "alice-chat")
    assert assigned["project_id"] == created["id"]
    assert project_routes.list_projects(alice)[0]["session_count"] == 1
    assert project_routes.list_projects(bob) == []

    project_routes.delete_project(alice, created["id"])
    with project_db() as db:
        assert db.get(Session, "alice-chat").project_id is None
        assert db.get(Session, "bob-chat").project_id is None
