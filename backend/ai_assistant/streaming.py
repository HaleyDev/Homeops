"""Structured, per-turn processing for ADK assistant events."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from google.adk.events import Event


@dataclass(frozen=True)
class StreamEvent:
    """A serializable event that can be encoded as an SSE frame."""

    name: str
    data: dict[str, Any]


@dataclass(frozen=True)
class TurnResult:
    """The assistant data persisted after an ADK turn finishes normally."""

    content: str
    thinking: str
    tool_calls: list[dict[str, Any]]


class TurnStreamCollector:
    """Collect one turn without using encoded SSE as an intermediate format.

    ADK's SSE mode can emit both partial chunks and a final, non-partial
    aggregate. Text channels are tracked independently so an aggregate never
    duplicates chunks, while a non-streaming/legacy response still has a
    reliable fallback for either channel.
    """

    def __init__(self) -> None:
        self._content: list[str] = []
        self._thinking: list[str] = []
        self._tool_calls: list[dict[str, Any]] = []
        self._partial_seen = {"text": False, "thinking": False}
        self._fallback_call_number = 0

    def process(self, event: Event) -> list[StreamEvent]:
        """Consume one ADK event and return zero or more structured events."""

        emitted: list[StreamEvent] = []
        content = event.content
        for part in content.parts if content else []:
            if part.function_call:
                emitted.append(self._start_tool_call(part.function_call))
                continue
            if part.function_response:
                emitted.append(self._complete_tool_call(part.function_response))
                continue
            if not part.text:
                continue

            channel = "thinking" if part.thought else "text"
            if event.partial:
                self._partial_seen[channel] = True
            elif self._partial_seen[channel]:
                # This is the final aggregate of chunks already emitted.
                continue

            if channel == "thinking":
                self._thinking.append(part.text)
                emitted.append(StreamEvent("thinking", {"detail": part.text}))
            else:
                self._content.append(part.text)
                emitted.append(StreamEvent("text", {"detail": part.text}))
        return emitted

    def finish(self) -> TurnResult:
        """Return final data, marking unanswered calls as incomplete."""

        for record in self._tool_calls:
            if record["status"] == "running":
                record["status"] = "incomplete"
        return TurnResult(
            content="".join(self._content),
            thinking="".join(self._thinking),
            tool_calls=deepcopy(self._tool_calls),
        )

    def _new_fallback_id(self) -> str:
        existing_ids = {record["id"] for record in self._tool_calls}
        while True:
            self._fallback_call_number += 1
            call_id = f"call_{self._fallback_call_number}"
            if call_id not in existing_ids:
                return call_id

    def _start_tool_call(self, call: Any) -> StreamEvent:
        record = {
            "id": call.id or self._new_fallback_id(),
            "name": call.name or "",
            "args": deepcopy(dict(call.args or {})),
            "status": "running",
        }
        self._tool_calls.append(record)
        return StreamEvent("tool_call", deepcopy(record))

    def _complete_tool_call(self, response: Any) -> StreamEvent:
        record = None
        response_id = response.id or ""
        response_name = response.name or ""

        if response_id:
            for candidate in reversed(self._tool_calls):
                if candidate["id"] == response_id:
                    record = candidate
                    break
        if record is None and response_name:
            # If ID matching is unavailable or fails, the latest running call
            # with this name is the safest match. Earlier duplicates remain
            # independently visible and the original stable call ID is kept.
            for candidate in reversed(self._tool_calls):
                if (
                    candidate["name"] == response_name
                    and candidate["status"] == "running"
                ):
                    record = candidate
                    break

        if record is None:
            record = {
                "id": response_id or self._new_fallback_id(),
                "name": response_name,
                "args": {},
                "status": "running",
            }
            self._tool_calls.append(record)

        result = deepcopy(dict(response.response or {}))
        record["result"] = result
        record["status"] = (
            "error"
            if result.get("error") is not None or result.get("status") == "error"
            else "success"
        )
        return StreamEvent("tool_response", deepcopy(record))
