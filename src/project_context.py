"""Resolve the project assigned to an owner-scoped conversation."""

from __future__ import annotations


def session_project_id(session_id: str | None, owner: str | None) -> str | None:
    if not session_id:
        return None
    from core.database import Session, SessionLocal

    with SessionLocal() as db:
        row = db.query(Session).filter(Session.id == session_id, Session.owner == owner).first()
        return row.project_id if row else None


def project_visible_upload(info: dict | None, owner: str | None,
                           project_id: str | None) -> bool:
    """Legacy uploads remain global; new chat uploads stay in their project."""
    if not isinstance(info, dict) or info.get("owner") != owner:
        return False
    return not info.get("project_bound") or info.get("project_id") == project_id
