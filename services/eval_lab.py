"""Offline, deterministic grading of canonical agent traces."""

from src.agent_trace import CanonicalTrace, TraceKind, tool_events_from_trace


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
                     "request_context_tokens", "context_length", "context_percent")
                    if isinstance(metrics.get(key), (int, float))}
    return {"passed": all(checks.values()), "checks": checks,
            "actual_tools": tools, "tool_count": len(tools),
            "measurements": measurements,
            "trace_summary": summary}
