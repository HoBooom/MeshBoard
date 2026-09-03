"""Version adapters for persisted interaction payloads."""

from __future__ import annotations

from typing import Any


CURRENT_INTERACTION_SCHEMA = "2.0"


def adapt_interaction_payload(schema_version: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize supported historical records to the current public shape."""
    major = str(schema_version or "1.0").split(".", 1)[0]
    if major not in {"1", "2"}:
        raise ValueError(f"지원하지 않는 interaction schema version: {schema_version}")

    if major == "1":
        tool = None
        if payload.get("tool_name") or payload.get("tool_input") or payload.get("tool_output"):
            tool = {
                "name": payload.get("tool_name"),
                "arguments": payload.get("tool_input"),
                "result": payload.get("tool_output"),
            }
        return {
            "schema_version": CURRENT_INTERACTION_SCHEMA,
            "source_schema_version": schema_version,
            "input": payload.get("prompt"),
            "output": payload.get("results"),
            "reasoning": payload.get("reasoning_trace"),
            "tool": tool,
            "metadata": payload.get("metadata") or payload.get("metadata_") or {},
        }

    return {
        "schema_version": CURRENT_INTERACTION_SCHEMA,
        "source_schema_version": schema_version,
        "input": payload.get("input", payload.get("prompt")),
        "output": payload.get("output", payload.get("results")),
        "reasoning": payload.get("reasoning", payload.get("reasoning_trace")),
        "tool": payload.get("tool") or (
            {
                "name": payload.get("tool_name"),
                "arguments": payload.get("tool_input"),
                "result": payload.get("tool_output"),
            }
            if payload.get("tool_name") or payload.get("tool_input") or payload.get("tool_output")
            else None
        ),
        "metadata": payload.get("metadata") or payload.get("metadata_") or {},
    }


def interaction_to_current_payload(interaction: Any) -> dict[str, Any]:
    return adapt_interaction_payload(
        interaction.schema_ver,
        {
            "prompt": interaction.prompt,
            "results": interaction.results,
            "reasoning_trace": interaction.reasoning_trace,
            "tool_name": interaction.tool_name,
            "tool_input": interaction.tool_input,
            "tool_output": interaction.tool_output,
            "metadata_": interaction.metadata_,
        },
    )
