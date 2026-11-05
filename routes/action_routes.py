"""Review source-linked action proposals before adding checklist items."""

import json
import re
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


def _extract_note_actions(note: Note) -> list[tuple[str, str]]:
    """Extract explicitly marked tasks without guessing intent from prose."""
    found = []
    seen = set()
    marker = re.compile(r"^\s*(?:[-*]\s*\[\s\]\s*|(?:TODO|ACTION|NEXT STEP|FOLLOW UP)\s*:\s*)",
                        re.IGNORECASE)
    for number, line in enumerate((note.content or "").splitlines(), start=1):
        match = marker.match(line)
        if not match:
            continue
        title = line[match.end():].strip(" -*\t")
        if not title or len(title) > 300 or title.casefold() in seen:
            continue
        seen.add(title.casefold())
        found.append((title, f"Line {number}: {line.strip()}"))
        if len(found) >= 20:
            return found
    try:
        items = json.loads(note.items or "[]")
    except (TypeError, json.JSONDecodeError):
        items = []
    for number, item in enumerate(items, start=1):
        if not isinstance(item, dict) or item.get("done"):
            continue
        title = str(item.get("text") or "").strip()
        if not title or len(title) > 300 or title.casefold() in seen:
            continue
        seen.add(title.casefold())
        found.append((title, f"Checklist item {number}: {title}"))
        if len(found) >= 20:
            break
    return found


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


@router.post("/from-note/{note_id}", status_code=201)
def propose_actions_from_note(request: Request, note_id: str):
    owner = effective_user(request)
    db = SessionLocal()
    try:
        note = db.query(Note).filter(Note.id == note_id, Note.owner == owner).first()
        if note is None or note.archived:
            raise HTTPException(404, "Open source note not found")
        candidates = _extract_note_actions(note)
        existing = {row.title.casefold() for row in db.query(ActionCandidate).filter(
            ActionCandidate.owner == owner, ActionCandidate.source_kind == "note",
            ActionCandidate.source_ref == note_id).all()}
        created = []
        for title, excerpt in candidates:
            if title.casefold() in existing:
                continue
            candidate = ActionCandidate(id=str(uuid.uuid4()), owner=owner, title=title,
                                        source_kind="note", source_ref=note_id,
                                        source_excerpt=excerpt, status="pending")
            db.add(candidate)
            created.append(candidate)
            existing.add(title.casefold())
        db.commit()
        return {"created": [_payload(candidate) for candidate in created],
                "skipped": len(candidates) - len(created),
                "source_url": f"/#open=notes&note={note_id}"}
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
        if candidate.source_kind in {"note", "document"}:
            if candidate.source_kind == "note":
                source = db.query(Note).filter(Note.id == candidate.source_ref,
                                               Note.owner == owner).first()
            else:
                from core.database import Document
                source = db.query(Document).filter(Document.id == candidate.source_ref,
                                                   Document.owner == owner).first()
            if source is None:
                raise HTTPException(409, "Source record is no longer available")
            if source.project_id != note.project_id:
                raise HTTPException(409, "Source and checklist belong to different projects")
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
