"""Owner-scoped project containers and chat assignment."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from core.database import Document, Note, Project, Session, SessionLocal
from src.auth_helpers import effective_user, require_chat_api_token_scope
from src.constants import DATA_DIR
from src.memory import MemoryManager


router = APIRouter(prefix="/api/projects", tags=["projects"],
                   dependencies=[Depends(require_chat_api_token_scope)])


class ProjectInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)


def _payload(project, session_count=0, note_count=0, document_count=0):
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description or "",
        "session_count": session_count,
        "note_count": note_count,
        "document_count": document_count,
        "created_at": project.created_at.isoformat() if project.created_at else None,
        "updated_at": project.updated_at.isoformat() if project.updated_at else None,
    }


def _owned_project(db, project_id, owner):
    project = db.query(Project).filter(Project.id == project_id, Project.owner == owner).first()
    if project is None:
        raise HTTPException(404, "Project not found")
    return project


@router.get("")
def list_projects(request: Request):
    owner = effective_user(request)
    db = SessionLocal()
    try:
        projects = (db.query(Project).filter(Project.owner == owner)
                    .order_by(Project.updated_at.desc()).all())
        return [_payload(project, db.query(Session).filter(
            Session.owner == owner, Session.project_id == project.id).count(),
            db.query(Note).filter(Note.owner == owner, Note.project_id == project.id).count(),
            db.query(Document).filter(Document.owner == owner, Document.project_id == project.id).count())
            for project in projects]
    finally:
        db.close()


@router.post("", status_code=201)
def create_project(request: Request, payload: ProjectInput):
    owner = effective_user(request)
    name = payload.name.strip()
    if not name:
        raise HTTPException(422, "Project name is required")
    db = SessionLocal()
    try:
        project = Project(id=str(uuid.uuid4()), owner=owner, name=name,
                          description=payload.description.strip())
        db.add(project)
        db.commit()
        db.refresh(project)
        return _payload(project)
    finally:
        db.close()


@router.patch("/{project_id}")
def update_project(request: Request, project_id: str, payload: ProjectInput):
    db = SessionLocal()
    try:
        project = _owned_project(db, project_id, effective_user(request))
        name = payload.name.strip()
        if not name:
            raise HTTPException(422, "Project name is required")
        project.name = name
        project.description = payload.description.strip()
        db.commit()
        db.refresh(project)
        return _payload(project)
    finally:
        db.close()


@router.delete("/{project_id}")
def delete_project(request: Request, project_id: str):
    owner = effective_user(request)
    db = SessionLocal()
    research_changes = []
    studio_changes = []
    memory_manager = MemoryManager(DATA_DIR)
    memory_changes = []
    try:
        project = _owned_project(db, project_id, owner)
        # Deleting a container keeps its conversations; they become unassigned.
        db.query(Session).filter(Session.owner == owner, Session.project_id == project_id).update(
            {Session.project_id: None}, synchronize_session=False)
        db.query(Note).filter(Note.owner == owner, Note.project_id == project_id).update(
            {Note.project_id: None}, synchronize_session=False)
        db.query(Document).filter(Document.owner == owner, Document.project_id == project_id).update(
            {Document.project_id: None}, synchronize_session=False)
        memory_changes = memory_manager.reassign_project(
            owner, None, from_project_id=project_id)
        from routes.research.research_routes import _clear_owned_research_project
        research_changes = _clear_owned_research_project(owner, project_id)
        from routes.studio_routes import _clear_owned_studio_project
        studio_changes = _clear_owned_studio_project(owner, project_id)
        db.delete(project)
        db.commit()
        return {"deleted": project_id}
    except Exception:
        db.rollback()
        if research_changes:
            from routes.research.research_routes import _restore_research_projects
            _restore_research_projects(research_changes)
        if studio_changes:
            from routes.studio_routes import _restore_studio_projects
            _restore_studio_projects(studio_changes)
        memory_manager.restore_project_assignments(memory_changes)
        raise
    finally:
        db.close()


@router.put("/{project_id}/sessions/{session_id}")
def assign_session(request: Request, project_id: str, session_id: str):
    owner = effective_user(request)
    db = SessionLocal()
    memory_manager = MemoryManager(DATA_DIR)
    memory_changes = []
    try:
        _owned_project(db, project_id, owner)
        session = db.query(Session).filter(Session.id == session_id, Session.owner == owner).first()
        if session is None:
            raise HTTPException(404, "Session not found")
        session.project_id = project_id
        db.query(Document).filter(Document.owner == owner,
                                  Document.session_id == session_id).update(
            {Document.project_id: project_id}, synchronize_session=False)
        memory_changes = memory_manager.reassign_project(
            owner, project_id, session_id=session_id)
        db.commit()
        return {"session_id": session_id, "project_id": project_id}
    except Exception:
        db.rollback()
        memory_manager.restore_project_assignments(memory_changes)
        raise
    finally:
        db.close()


@router.delete("/{project_id}/sessions/{session_id}")
def unassign_session(request: Request, project_id: str, session_id: str):
    owner = effective_user(request)
    db = SessionLocal()
    memory_manager = MemoryManager(DATA_DIR)
    memory_changes = []
    try:
        _owned_project(db, project_id, owner)
        session = db.query(Session).filter(Session.id == session_id,
                                           Session.owner == owner,
                                           Session.project_id == project_id).first()
        if session is None:
            raise HTTPException(404, "Session not found in project")
        session.project_id = None
        db.query(Document).filter(Document.owner == owner,
                                  Document.session_id == session_id).update(
            {Document.project_id: None}, synchronize_session=False)
        memory_changes = memory_manager.reassign_project(
            owner, None, session_id=session_id)
        db.commit()
        return {"session_id": session_id, "project_id": None}
    except Exception:
        db.rollback()
        memory_manager.restore_project_assignments(memory_changes)
        raise
    finally:
        db.close()


@router.put("/{project_id}/notes/{note_id}")
def assign_note(request: Request, project_id: str, note_id: str):
    owner = effective_user(request)
    db = SessionLocal()
    try:
        _owned_project(db, project_id, owner)
        note = db.query(Note).filter(Note.id == note_id, Note.owner == owner).first()
        if note is None:
            raise HTTPException(404, "Note not found")
        note.project_id = project_id
        db.commit()
        return {"note_id": note_id, "project_id": project_id}
    finally:
        db.close()


@router.delete("/{project_id}/notes/{note_id}")
def unassign_note(request: Request, project_id: str, note_id: str):
    owner = effective_user(request)
    db = SessionLocal()
    try:
        _owned_project(db, project_id, owner)
        note = db.query(Note).filter(Note.id == note_id, Note.owner == owner,
                                     Note.project_id == project_id).first()
        if note is None:
            raise HTTPException(404, "Note not found in project")
        note.project_id = None
        db.commit()
        return {"note_id": note_id, "project_id": None}
    finally:
        db.close()


@router.put("/{project_id}/documents/{document_id}")
def assign_document(request: Request, project_id: str, document_id: str):
    owner = effective_user(request)
    db = SessionLocal()
    try:
        _owned_project(db, project_id, owner)
        document = db.query(Document).filter(Document.id == document_id,
                                             Document.owner == owner).first()
        if document is None:
            raise HTTPException(404, "Document not found")
        document.project_id = project_id
        db.commit()
        return {"document_id": document_id, "project_id": project_id}
    finally:
        db.close()


@router.delete("/{project_id}/documents/{document_id}")
def unassign_document(request: Request, project_id: str, document_id: str):
    owner = effective_user(request)
    db = SessionLocal()
    try:
        _owned_project(db, project_id, owner)
        document = db.query(Document).filter(Document.id == document_id,
                                             Document.owner == owner,
                                             Document.project_id == project_id).first()
        if document is None:
            raise HTTPException(404, "Document not found in project")
        document.project_id = None
        db.commit()
        return {"document_id": document_id, "project_id": None}
    finally:
        db.close()
