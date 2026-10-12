"""Stub tool catalog for Phase 1 (no real tool execution)."""
from __future__ import annotations

from typing import Any


def list_tools() -> list[dict[str, Any]]:
    return [
        {
            "id": "weather",
            "name": "Weather",
            "description": "Gets current weather and forecast for a location",
            "configured": False,
        },
        {
            "id": "calendar",
            "name": "Calendar",
            "description": "Reads calendar events and availability",
            "configured": False,
        },
        {
            "id": "email",
            "name": "Email",
            "description": "Sends or searches email messages",
            "configured": False,
        },
    ]


def match_tools(query: str, *, top_k: int = 3) -> list[dict[str, Any]]:
    q = (query or "").lower()
    scored: list[tuple[float, dict[str, Any]]] = []
    for tool in list_tools():
        blob = f"{tool['id']} {tool['name']} {tool['description']}".lower()
        score = 0.0
        for token in q.split():
            if len(token) >= 3 and token in blob:
                score += 1.0
        if score > 0:
            scored.append((score, tool))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [t for _, t in scored[:top_k]]


def tool_stub_hits(query: str) -> list[dict[str, Any]]:
    """Return informational hits when router chooses TOOL and no tool is configured."""
    matched = match_tools(query) or list_tools()[:1]
    hits: list[dict[str, Any]] = []
    for tool in matched:
        hits.append(
            {
                "id": f"tool-stub-{tool['id']}",
                "title": f"Tool '{tool['name']}' is not configured yet",
                "snippet": (
                    f"{tool['description']}. "
                    "Phase 1 includes routing only — tool execution comes later."
                ),
                "content_type": "tool",
                "url": "",
                "score": 0.4,
                "metadata": {
                    "database_id": "tools",
                    "database_label": "Tools",
                    "retrieval": "tool_stub",
                    "tool_id": tool["id"],
                    "configured": False,
                },
            }
        )
    return hits
