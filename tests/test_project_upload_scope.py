import io
from types import SimpleNamespace

from src.project_context import project_visible_upload
from src.upload_handler import UploadHandler


def test_chat_uploads_dedupe_within_session_and_move_with_project(tmp_path):
    base = tmp_path / "base"
    uploads = tmp_path / "uploads"
    base.mkdir()
    uploads.mkdir()
    handler = UploadHandler(str(base), str(uploads))

    def save(session_id, project_id):
        return handler.save_upload(
            SimpleNamespace(filename="brief.txt", file=io.BytesIO(b"same brief")),
            "127.0.0.1", owner="alice", session_id=session_id,
            project_id=project_id)

    first = save("chat-a", "project-a")
    repeat = save("chat-a", "project-a")
    second = save("chat-b", "project-b")
    assert first["id"] == repeat["id"]
    assert repeat["is_duplicate"] is True
    assert first["id"] != second["id"]
    assert project_visible_upload(first, "alice", "project-a")
    assert not project_visible_upload(first, "alice", "project-b")
    assert not project_visible_upload(first, "bob", "project-a")

    changes = handler.reassign_project("alice", "project-b", session_id="chat-a")
    moved = handler.resolve_upload(first["id"], owner="alice")
    assert project_visible_upload(moved, "alice", "project-b")
    assert not project_visible_upload(moved, "alice", "project-a")
    assert handler.resolve_upload(second["id"], owner="alice")["project_id"] == "project-b"
    handler.restore_project_assignments(changes)
    assert handler.resolve_upload(first["id"], owner="alice")["project_id"] == "project-a"


def test_legacy_uploads_remain_global_for_existing_references():
    assert project_visible_upload({"owner": "alice"}, "alice", "project-a")
