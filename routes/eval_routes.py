"""Saved evaluation cases, trace replay grades, and pairwise comparisons."""

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from core.database import EvaluationCase, EvaluationRun, SessionLocal
from services.eval_lab import grade_trace
from src.agent_trace import CanonicalTrace, CanonicalTraceEvent, decode_native_trace
from src.auth_helpers import effective_user, require_chat_api_token_scope


router = APIRouter(prefix="/api/evals", tags=["evaluations"],
                   dependencies=[Depends(require_chat_api_token_scope)])


class CaseInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=1, max_length=12000)
    expected_tools: list[str] = Field(default_factory=list, max_length=30)
    forbidden_tools: list[str] = Field(default_factory=list, max_length=30)
    required_text: str = Field(default="", max_length=500)


class GradeInput(BaseModel):
    model_label: str = Field(default="", max_length=120)
    response_text: str = Field(default="", max_length=200000)
    trace: list[dict] = Field(min_length=1, max_length=5000)


class NativeGradeInput(BaseModel):
    model_label: str = Field(default="", max_length=120)
    response_text: str = Field(default="", max_length=200000)
    records: list[dict] = Field(min_length=1, max_length=5000)


def _case_payload(case):
    return {"id": case.id, "name": case.name, "prompt": case.prompt,
            "expected_tools": case.expected_tools or [],
            "forbidden_tools": case.forbidden_tools or [],
            "required_text": case.required_text or ""}


def _run_payload(run, *, include_trace=False):
    result = {"id": run.id, "case_id": run.case_id,
              "model_label": run.model_label, "response_text": run.response_text,
              "grade": run.grade_json,
              "created_at": run.created_at.isoformat() if run.created_at else None}
    if include_trace:
        result["trace"] = run.trace_json
    return result


@router.get("/cases")
def list_cases(request: Request):
    db = SessionLocal()
    try:
        rows = (db.query(EvaluationCase).filter(EvaluationCase.owner == effective_user(request))
                .order_by(EvaluationCase.updated_at.desc()).all())
        return [_case_payload(row) for row in rows]
    finally:
        db.close()


@router.post("/cases", status_code=201)
def create_case(request: Request, payload: CaseInput):
    if not payload.name.strip() or not payload.prompt.strip():
        raise HTTPException(422, "name and prompt cannot be blank")
    db = SessionLocal()
    try:
        case = EvaluationCase(id=str(uuid.uuid4()), owner=effective_user(request),
                              name=payload.name.strip(), prompt=payload.prompt.strip(),
                              expected_tools=payload.expected_tools,
                              forbidden_tools=payload.forbidden_tools,
                              required_text=payload.required_text.strip())
        db.add(case)
        db.commit()
        return _case_payload(case)
    finally:
        db.close()


@router.get("/cases/{case_id}/runs")
def list_runs(request: Request, case_id: str):
    owner = effective_user(request)
    db = SessionLocal()
    try:
        if db.query(EvaluationCase).filter(EvaluationCase.id == case_id,
                                           EvaluationCase.owner == owner).first() is None:
            raise HTTPException(404, "Evaluation case not found")
        rows = (db.query(EvaluationRun).filter(EvaluationRun.case_id == case_id,
                                               EvaluationRun.owner == owner)
                .order_by(EvaluationRun.created_at.desc()).limit(100).all())
        return [_run_payload(row) for row in rows]
    finally:
        db.close()


@router.post("/cases/{case_id}/grade", status_code=201)
def grade_case(request: Request, case_id: str, payload: GradeInput):
    if len(json.dumps(payload.trace)) > 2_000_000:
        raise HTTPException(413, "Trace exceeds 2 MB")
    try:
        events = [CanonicalTraceEvent.from_dict(item) for item in payload.trace]
        trace = CanonicalTrace(events[0].run_id, events)
    except (ValueError, KeyError, TypeError) as error:
        raise HTTPException(422, f"Invalid canonical trace: {error}") from error
    return _save_grade(request, case_id, trace, payload.model_label,
                       payload.response_text)


@router.post("/cases/{case_id}/grade-native", status_code=201)
def grade_native_case(request: Request, case_id: str, payload: NativeGradeInput):
    if len(json.dumps(payload.records)) > 2_000_000:
        raise HTTPException(413, "Trace exceeds 2 MB")
    try:
        trace = decode_native_trace(payload.records, run_id=str(uuid.uuid4()))
    except (ValueError, KeyError, TypeError) as error:
        raise HTTPException(422, f"Invalid native trace: {error}") from error
    return _save_grade(request, case_id, trace, payload.model_label,
                       payload.response_text)


def _save_grade(request: Request, case_id: str, trace: CanonicalTrace,
                model_label: str, response_text: str):
    owner = effective_user(request)
    db = SessionLocal()
    try:
        case = db.query(EvaluationCase).filter(EvaluationCase.id == case_id,
                                               EvaluationCase.owner == owner).first()
        if case is None:
            raise HTTPException(404, "Evaluation case not found")
        grade = grade_trace(trace, expected_tools=case.expected_tools or [],
                            forbidden_tools=case.forbidden_tools or [],
                            required_text=case.required_text or "",
                            response_text=response_text)
        run = EvaluationRun(id=str(uuid.uuid4()), owner=owner, case_id=case_id,
                            model_label=model_label.strip(),
                            response_text=response_text,
                            trace_json=trace.to_list(), grade_json=grade)
        db.add(run)
        db.commit()
        return _run_payload(run)
    finally:
        db.close()


@router.get("/runs/{run_id}")
def get_run(request: Request, run_id: str):
    db = SessionLocal()
    try:
        run = db.query(EvaluationRun).filter(EvaluationRun.id == run_id,
                                             EvaluationRun.owner == effective_user(request)).first()
        if run is None:
            raise HTTPException(404, "Evaluation run not found")
        return _run_payload(run, include_trace=True)
    finally:
        db.close()


@router.get("/compare/{left_id}/{right_id}")
def compare_runs(request: Request, left_id: str, right_id: str):
    owner = effective_user(request)
    db = SessionLocal()
    try:
        runs = [db.query(EvaluationRun).filter(EvaluationRun.id == identifier,
                                                EvaluationRun.owner == owner).first()
                for identifier in (left_id, right_id)]
        if any(run is None for run in runs):
            raise HTTPException(404, "Evaluation run not found")
        if runs[0].case_id != runs[1].case_id:
            raise HTTPException(422, "Runs must belong to the same case")
        def measurement_delta(key):
            left = runs[0].grade_json.get("measurements", {}).get(key)
            right = runs[1].grade_json.get("measurements", {}).get(key)
            return right - left if isinstance(left, (int, float)) and isinstance(right, (int, float)) else None
        return {"case_id": runs[0].case_id,
                "left": _run_payload(runs[0]), "right": _run_payload(runs[1]),
                "delta": {"tool_count": runs[1].grade_json["tool_count"] - runs[0].grade_json["tool_count"],
                          "response_time": measurement_delta("response_time"),
                          "total_tokens": measurement_delta("total_tokens"),
                          "passed": [runs[0].grade_json["passed"], runs[1].grade_json["passed"]]}}
    finally:
        db.close()
