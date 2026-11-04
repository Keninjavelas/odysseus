"""Review source-linked action proposals before adding checklist items."""

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from core.database import ActionCandidate, Note, SessionLocal
from src.auth_helpers import effective_user, require_chat_api_token_scope


router = APIRouter(prefix="/api/actions", tags=["actions"],
                   dependencies=[Depends(require_chat_api_token_scope)])
SOURCE_KINDS = {"email", "research", "note", "document", "meeting", "manual"}


class CandidateInput(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    source_kind: str
    source_ref: str = Field(default="", max_length=500)
    source_excerpt: str = Field(default="", max_length=2000)


class AcceptInput(BaseModel):
    note_id: str


def _payload(candidate):
    return {"id": candidate.id, "title": candidate.title,
            "source_kind": candidate.source_kind, "source_ref": candidate.source_ref,
            "source_excerpt": candidate.source_excerpt, "status": candidate.status,
            "checklist_note_id": candidate.checklist_note_id,
            "created_at": candidate.created_at.isoformat() if candidate.created_at else None}


def _owned(db, owner, candidate_id):
    candidate = db.query(ActionCandidate).filter(ActionCandidate.id == candidate_id,
                                                  ActionCandidate.owner == owner).first()
    if candidate is None:
        raise HTTPException(404, "Action proposal not found")
    return candidate


@router.get("")
def list_actions(request: Request, status: str = "pending"):
    if status not in {"pending", "accepted", "rejected", "all"}:
        raise HTTPException(422, "Invalid status")
    db = SessionLocal()
    try:
        query = db.query(ActionCandidate).filter(ActionCandidate.owner == effective_user(request))
        if status != "all":
            query = query.filter(ActionCandidate.status == status)
        return [_payload(row) for row in query.order_by(ActionCandidate.created_at.desc()).limit(100).all()]
    finally:
        db.close()


@router.post("", status_code=201)
def create_action(request: Request, payload: CandidateInput):
    owner = effective_user(request)
    title = payload.title.strip()
    if not title or payload.source_kind not in SOURCE_KINDS:
        raise HTTPException(422, "A title and supported source kind are required")
    db = SessionLocal()
    try:
        source_ref = payload.source_ref.strip()
        if payload.source_kind in {"note", "document"} and not source_ref:
            raise HTTPException(422, "A source record id is required")
        if payload.source_kind == "note" and source_ref:
            if db.query(Note).filter(Note.id == source_ref, Note.owner == owner).first() is None:
                raise HTTPException(404, "Source note not found")
        if payload.source_kind == "document" and source_ref:
            from core.database import Document
            if db.query(Document).filter(Document.id == source_ref,
                                         Document.owner == owner).first() is None:
                raise HTTPException(404, "Source document not found")
        existing = db.query(ActionCandidate).filter(
            ActionCandidate.owner == owner, ActionCandidate.status == "pending",
            ActionCandidate.title == title, ActionCandidate.source_kind == payload.source_kind,
            ActionCandidate.source_ref == source_ref).first()
        if existing:
            return _payload(existing)
        candidate = ActionCandidate(id=str(uuid.uuid4()), owner=owner, title=title,
                                    source_kind=payload.source_kind, source_ref=source_ref,
                                    source_excerpt=payload.source_excerpt.strip(), status="pending")
        db.add(candidate)
        db.commit()
        return _payload(candidate)
    finally:
        db.close()


@router.post("/{candidate_id}/accept")
def accept_action(request: Request, candidate_id: str, payload: AcceptInput):
    owner = effective_user(request)
    db = SessionLocal()
    try:
        candidate = _owned(db, owner, candidate_id)
        if candidate.status != "pending":
            raise HTTPException(409, "Action proposal is already reviewed")
        note = db.query(Note).filter(Note.id == payload.note_id, Note.owner == owner).first()
        if note is None or note.note_type not in {"checklist", "todo", "goal"} or note.archived:
            raise HTTPException(404, "Open checklist not found")
        try:
            items = json.loads(note.items or "[]")
        except (TypeError, json.JSONDecodeError):
            raise HTTPException(409, "Checklist items are malformed")
        if not isinstance(items, list):
            raise HTTPException(409, "Checklist items are malformed")
        duplicate = any(isinstance(item, dict) and
                        str(item.get("text") or "").strip().casefold() == candidate.title.casefold()
                        for item in items)
        if not duplicate:
            items.append({"text": candidate.title, "done": False})
            note.items = json.dumps(items)
        candidate.status = "accepted"
        candidate.checklist_note_id = note.id
        db.commit()
        return {**_payload(candidate), "duplicate": duplicate,
                "open_url": f"/#open=notes&note={note.id}"}
    finally:
        db.close()


@router.post("/{candidate_id}/reject")
def reject_action(request: Request, candidate_id: str):
    db = SessionLocal()
    try:
        candidate = _owned(db, effective_user(request), candidate_id)
        if candidate.status != "pending":
            raise HTTPException(409, "Action proposal is already reviewed")
        candidate.status = "rejected"
        db.commit()
        return _payload(candidate)
    finally:
        db.close()
