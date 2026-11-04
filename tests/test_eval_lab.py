import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import Base, EvaluationCase, EvaluationRun
from routes import eval_routes
from services.eval_lab import grade_trace
from src.agent_trace import decode_native_trace


def _trace():
    return decode_native_trace([
        {"sse": 'data: ' + json.dumps({"type": "tool_start", "tool": "web_search",
                                       "command": "climate", "round": 1}) + "\n\n"},
        {"sse": 'data: ' + json.dumps({"type": "tool_output", "tool": "web_search",
                                       "command": "climate", "output": "found", "exit_code": 0}) + "\n\n"},
        {"sse": "data: [DONE]\n\n"},
    ], run_id="eval-test")


def test_grade_trace_checks_tool_order_and_response():
    trace = _trace()
    good = grade_trace(trace, expected_tools=["web_search"], forbidden_tools=["bash"],
                       required_text="climate", response_text="Climate sources found")
    assert good["passed"] is True
    bad = grade_trace(trace, expected_tools=["read_file"], forbidden_tools=["web_search"],
                      required_text="missing", response_text="Climate sources found")
    assert bad["passed"] is False
    assert bad["checks"]["no_forbidden_tools"] is False


@pytest.fixture
def eval_db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[EvaluationCase.__table__, EvaluationRun.__table__])
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(eval_routes, "SessionLocal", factory)
    monkeypatch.setattr(eval_routes, "effective_user", lambda request: request.owner)
    yield factory
    engine.dispose()


def test_saved_case_replay_and_compare_are_private(eval_db):
    alice = SimpleNamespace(owner="alice")
    bob = SimpleNamespace(owner="bob")
    case = eval_routes.create_case(alice, eval_routes.CaseInput(
        name="Find sources", prompt="Find climate sources", expected_tools=["web_search"]))
    payload = eval_routes.GradeInput(model_label="small-model", response_text="Found sources",
                                     trace=_trace().to_list())
    first = eval_routes.grade_case(alice, case["id"], payload)
    second = eval_routes.grade_case(alice, case["id"], payload)
    native = eval_routes.grade_native_case(alice, case["id"], eval_routes.NativeGradeInput(
        model_label="native", response_text="Found sources", records=[
            {"sse": 'data: ' + json.dumps({"type": "tool_start", "tool": "web_search",
                                           "command": "climate", "round": 1}) + "\n\n"},
            {"sse": 'data: ' + json.dumps({"type": "tool_output", "tool": "web_search",
                                           "command": "climate", "output": "found", "exit_code": 0}) + "\n\n"},
            {"sse": 'data: ' + json.dumps({"type": "metrics", "data": {
                "input_tokens": 100, "output_tokens": 30, "total_tokens": 130,
                "response_time": 1.5}}) + "\n\n"},
            {"sse": "data: [DONE]\n\n"},
        ]))
    assert first["grade"]["passed"] is True
    assert native["grade"]["passed"] is True
    assert native["grade"]["measurements"]["total_tokens"] == 130
    comparison = eval_routes.compare_runs(alice, first["id"], second["id"])
    assert comparison["delta"]["tool_count"] == 0
    assert comparison["delta"]["response_time"] is None
    assert comparison["delta"]["total_tokens"] is None
    assert eval_routes.compare_runs(alice, first["id"], native["id"])["delta"]["total_tokens"] is None
    assert len(eval_routes.list_runs(alice, case["id"])) == 3
    with pytest.raises(HTTPException) as denied:
        eval_routes.get_run(bob, first["id"])
    assert denied.value.status_code == 404
