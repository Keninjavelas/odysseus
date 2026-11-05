"""Project chats see global memory and their own project memory only."""

import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core import database
from src import ai_interaction
from src.chat_processor import ChatProcessor
from src.memory import MemoryManager
from src.memory_provider import NativeMemoryProvider


@pytest.fixture
def memory_scope(tmp_path, monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    database.Base.metadata.create_all(engine, tables=[database.Session.__table__])
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(database, "SessionLocal", factory)
    with factory() as db:
        for sid, owner, project in (
            ("film-chat", "alice", "film"), ("music-chat", "alice", "music"),
            ("general-chat", "alice", None), ("foreign-chat", "bob", "film"),
        ):
            db.add(database.Session(id=sid, owner=owner, project_id=project,
                                    name=sid, model="test", endpoint_url=""))
        db.commit()
    manager = MemoryManager(str(tmp_path))
    monkeypatch.setattr(ai_interaction, "_memory_manager", manager)
    yield manager
    engine.dispose()


def _manage(action, session_id):
    return asyncio.run(ai_interaction.do_manage_memory(action, session_id, owner="alice"))


def test_agent_memory_actions_are_project_scoped(memory_scope):
    global_id = _manage("add\nPrefers short answers", "general-chat")["memory_id"]
    film_id = _manage("add\nFilm budget is private", "film-chat")["memory_id"]
    music_id = _manage("add\nMusic schedule is private", "music-chat")["memory_id"]

    assert "Film budget" in _manage("list", "film-chat")["results"]
    assert "Prefers short answers" in _manage("list", "film-chat")["results"]
    assert "Music schedule" not in _manage("list", "film-chat")["results"]
    assert "Film budget" not in _manage("list", "general-chat")["results"]
    assert "No memories found" in _manage("search\nFilm budget", "music-chat")["results"]
    assert "not found" in _manage(f"edit\n{music_id}\nChanged", "film-chat")["error"]
    assert "not found" in _manage(f"delete\n{film_id}", "music-chat")["error"]
    assert memory_scope.load_all()[1]["project_id"] == "film"
    assert _manage(f"edit\n{global_id}\nPrefers concise answers", "film-chat")["action"] == "edit"


def test_chat_preface_excludes_other_project_memory(memory_scope):
    _manage("add\nGlobal writing preference", "general-chat")
    _manage("add\nFilm private detail", "film-chat")
    _manage("add\nMusic private detail", "music-chat")
    processor = ChatProcessor(memory_manager=memory_scope,
                              personal_docs_manager=SimpleNamespace(rag_manager=None))
    preface, _, _ = processor.build_context_preface(
        message="Summarize Film private detail and my writing preference",
        session=SimpleNamespace(id="film-chat"), owner="alice", use_rag=False)
    text = "\n".join(row["content"] for row in preface)
    assert "Film private detail" in text
    assert "Global writing preference" in text
    assert "Music private detail" not in text


def test_native_provider_scopes_session_recall_and_delete(memory_scope):
    class Vector:
        healthy = True

        def __init__(self):
            self.results = []

        def add(self, *args):
            pass

        def remove(self, *args):
            pass

        def search(self, *args, **kwargs):
            return self.results

    vector = Vector()
    provider = NativeMemoryProvider(memory_scope, vector)
    film = asyncio.run(provider.remember(
        "Film private deadline", owner="alice", session_id="film-chat"))
    vector.results = [{"memory_id": film.id, "score": 0.99}]
    assert memory_scope.load(owner="alice")[0]["project_id"] == "film"
    assert asyncio.run(provider.recall(
        "Film deadline", owner="alice", session_id="music-chat")) == []
    assert asyncio.run(provider.list_memories(
        owner="alice", session_id="music-chat")) == []
    assert asyncio.run(provider.delete(
        film.id, owner="alice", session_id="music-chat")) is False
    assert asyncio.run(provider.recall(
        "Film deadline", owner="alice", session_id="film-chat"))[0].memory.id == film.id


def test_legacy_session_memories_backfill_only_for_matching_owner(memory_scope):
    memory_scope.save([
        {"id": "film", "owner": "alice", "session_id": "film-chat", "text": "Film"},
        {"id": "foreign", "owner": "alice", "session_id": "foreign-chat", "text": "Foreign"},
        {"id": "general", "owner": "alice", "session_id": "general-chat", "text": "General"},
    ])
    assert memory_scope.backfill_session_projects() == 1
    assert memory_scope.backfill_session_projects() == 0
    rows = {entry["id"]: entry for entry in memory_scope.load(owner="alice")}
    assert rows["film"]["project_id"] == "film"
    assert rows["foreign"].get("project_id") is None
    assert rows["general"].get("project_id") is None
