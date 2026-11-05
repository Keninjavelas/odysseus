"""Offline, deterministic grading of canonical agent traces."""

from src.agent_trace import CanonicalTrace, TraceKind, tool_events_from_trace
from src.context_budget import CONTEXT_PROFILES
from src.generation_budget import context_safety_margin


def _nonnegative_number(value):
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 else None


def profile_budget_from_trace(trace: CanonicalTrace, metrics: dict) -> dict | None:
    """Compare the recorded request against profile caps; no model rerun is implied."""
    requests = []
    for event in trace.events:
        if event.kind != TraceKind.RUNTIME or event.payload.get("type") != "tool_routing_audit":
            continue
        audit = event.payload.get("data") or {}
        if not isinstance(audit, dict):
            continue
        prompt = _nonnegative_number(audit.get("prompt_tokens_estimate"))
        if prompt is None:
            continue
        schema = _nonnegative_number(audit.get("tool_schema_tokens_estimate"))
        if schema is None:
            chars = _nonnegative_number(audit.get("tool_schema_chars"))
            schema = int(chars * 0.3) if chars is not None and chars > 2 else 0
        requests.append({
            "prompt_tokens_estimate": prompt,
            "tool_schema_tokens_estimate": schema,
            "tool_schema_count": _nonnegative_number(audit.get("tool_schema_count")),
            "request_tokens_estimate": prompt + schema,
        })
    if requests:
        peak = max(requests, key=lambda item: item["request_tokens_estimate"])
        source = "routing_audit"
    else:
        recorded = _nonnegative_number(metrics.get("request_context_tokens"))
        if recorded is None:
            return None
        peak = {"prompt_tokens_estimate": None, "tool_schema_tokens_estimate": None,
                "tool_schema_count": None, "request_tokens_estimate": recorded}
        source = "final_metrics"
    requested = peak["request_tokens_estimate"]
    return {
        "source": source,
        "rounds_observed": len(requests),
        "recorded_context_window": _nonnegative_number(metrics.get("context_length")),
        **peak,
        "profiles": {
            name: {
                "window": window,
                "safety_margin": context_safety_margin(window),
                "remaining_after_margin": window - requested - context_safety_margin(window),
                "fits_recorded_request": requested + context_safety_margin(window) < window,
                "utilization_percent": round(requested / window * 100, 1),
            }
            for name, window in CONTEXT_PROFILES.items()
        },
    }


def _ordered_subsequence(actual: list[str], expected: list[str]) -> bool:
    pending = iter(actual)
    return all(any(item == target for item in pending) for target in expected)


def grade_trace(trace: CanonicalTrace, *, expected_tools: list[str],
                forbidden_tools: list[str], required_text: str,
                response_text: str) -> dict:
    summary = trace.summary()
    events = tool_events_from_trace(trace)
    tools = [str(event.get("tool") or "") for event in events]
    checks = {
        "complete_trace": bool(summary["complete"]),
        "linked_tool_calls": bool(summary["tool_linkage_valid"]),
        "expected_tool_order": _ordered_subsequence(tools, expected_tools),
        "no_forbidden_tools": not set(forbidden_tools).intersection(tools),
        "required_response_text": required_text.casefold() in response_text.casefold(),
        "tool_execution": all(event.get("exit_code") in (None, 0) and not event.get("error")
                              for event in events),
    }
    metrics = next((event.payload.get("data", {}) for event in reversed(trace.events)
                    if event.kind == TraceKind.RUNTIME and event.payload.get("type") == "metrics"), {})
    measurements = {key: metrics.get(key) for key in
                    ("response_time", "input_tokens", "output_tokens", "total_tokens",
                     "request_context_tokens", "context_length", "context_percent",
                     "cost_usd", "time_to_first_token")
                    if isinstance(metrics.get(key), (int, float))
                    and not isinstance(metrics.get(key), bool)}
    for key in ("cost_source", "usage_source"):
        if metrics.get(key) in ({"reported", "estimated"} if key == "cost_source"
                                else {"real", "estimated", "mixed"}):
            measurements[key] = metrics[key]
    profile_budget = profile_budget_from_trace(trace, metrics)
    return {"passed": all(checks.values()), "checks": checks,
            "actual_tools": tools, "tool_count": len(tools),
            "measurements": measurements,
            "profile_budget": profile_budget,
            "trace_summary": summary}
