"""Document agent tools keep a chat inside its assigned project."""

import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.database import Base, Document, Project, Session
from src.agent_tools import TOOL_HANDLERS
from src.agent_runtime.authority import ExactOperation
from src.agent_runtime.owned_resources import resolve_owned_operation
from src.agent_runtime.resources import ResourceIdentityError


def test_document_agent_list_read_and_update_are_project_scoped(monkeypatch):
    from core import database as core_db
    from src import database as src_db

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[Project.__table__, Session.__table__, Document.__table__])
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(core_db, "SessionLocal", factory)
    monkeypatch.setattr(src_db, "SessionLocal", factory)
    with factory() as db:
        db.add(Project(id="film", owner="alice", name="Film"))
        db.add(Session(id="film-chat", owner="alice", project_id="film",
                       name="Film chat", endpoint_url="", model=""))
        db.add(Session(id="general-chat", owner="alice", name="General",
                       endpoint_url="", model=""))
        db.add(Document(id="film-doc", owner="alice", project_id="film",
                        title="Film", current_content="Film content", is_active=True))
        db.add(Document(id="general-doc", owner="alice", title="General",
                        current_content="General content", is_active=True))
        db.commit()

    film_ctx = {"owner": "alice", "session_id": "film-chat"}
    general_ctx = {"owner": "alice", "session_id": "general-chat"}
    film_list = asyncio.run(TOOL_HANDLERS["manage_documents"]('{"action":"list"}', film_ctx))
    assert [item["id"] for item in film_list["documents"]] == ["film-doc"]
    general_list = asyncio.run(TOOL_HANDLERS["manage_documents"]('{"action":"list"}', general_ctx))
    assert [item["id"] for item in general_list["documents"]] == ["general-doc"]
    denied = asyncio.run(TOOL_HANDLERS["manage_documents"](
        '{"action":"read","document_id":"general-doc"}', film_ctx))
    assert denied["exit_code"] == 1
    denied_edit = asyncio.run(TOOL_HANDLERS["update_document"](
        "Changed", {**film_ctx, "doc_id": "general-doc"}))
    assert denied_edit["exit_code"] == 1
    with pytest.raises(ResourceIdentityError):
        resolve_owned_operation(ExactOperation.normalize(
            "manage_documents", '{"action":"read","document_id":"general-doc"}'),
            owner="alice", thread_id="film-chat")
    latest = resolve_owned_operation(ExactOperation.normalize(
        "manage_documents", '{"action":"read","document_id":"latest"}'),
        owner="alice", thread_id="film-chat")
    assert latest.document_id == "film-doc"
    with factory() as db:
        assert db.get(Document, "general-doc").current_content == "General content"
    engine.dispose()
