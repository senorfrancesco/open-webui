from __future__ import annotations

import copy
import json
import os
from typing import Any, Awaitable, Callable

from fastapi.responses import StreamingResponse


LONG_RUNNING_TOOL_NAMES = frozenset(
    {
        "analyze_equipment_deep",
        "analyze_document_deep",
    }
)

SESSION_RAG_HANDOFF_MARKER = "llm_tools_platform_session_rag_handoff"

_LONG_RUNNING_TOOL_LAUNCH_LABELS = {
    "analyze_equipment_deep": "инструмент глубокого анализа оборудования",
    "analyze_document_deep": "инструмент глубокого анализа документа",
}


def build_long_running_tool_launch_error(tool_name: str | None = None) -> str:
    tool_label = _LONG_RUNNING_TOOL_LAUNCH_LABELS.get(
        str(tool_name or "").strip(),
        "инструмент глубокого анализа",
    )
    return (
        f"Не удалось запустить {tool_label}.\n"
        "Инструмент не вернул подтверждение запуска (`job_id` и `status_url`). "
        "Повторите запрос и проверьте, что инструмент включён в текущем чате."
    )


LONG_RUNNING_TOOL_LAUNCH_ERROR = build_long_running_tool_launch_error()


def _session_rag_handoff_mode() -> str:
    raw = str(os.environ.get("OPENWEBUI_SESSION_RAG_HANDOFF", "preferred") or "").strip().lower()
    if raw in {"", "preferred", "required"}:
        return raw or "preferred"
    if raw in {"0", "false", "no", "off", "disabled"}:
        return "off"
    return "preferred"


def _extract_metadata_files(body: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(body, dict):
        return []
    metadata = body.get("metadata")
    if not isinstance(metadata, dict):
        return []
    files = metadata.get("files")
    if not isinstance(files, list):
        return []
    return [item for item in files if isinstance(item, dict)]


def _extract_top_level_files(body: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(body, dict):
        return []
    files = body.get("files")
    if not isinstance(files, list):
        return []
    return [item for item in files if isinstance(item, dict)]


def extract_body_files(body: dict[str, Any] | None) -> list[dict[str, Any]]:
    metadata_files = _extract_metadata_files(body)
    if metadata_files:
        return metadata_files
    return _extract_top_level_files(body)


def should_enable_session_rag_handoff(body: dict[str, Any] | None) -> bool:
    return _session_rag_handoff_mode() in {"preferred", "required"} and bool(extract_body_files(body))


def _build_session_rag_handoff_payload(body: dict[str, Any]) -> dict[str, Any]:
    metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
    files = extract_body_files(body)
    original_model = str(body.get("model") or "").strip() or None
    return {
        "enabled": True,
        "mode": _session_rag_handoff_mode(),
        "chat_id": str(metadata.get("chat_id") or "").strip() or None,
        "message_id": str(metadata.get("message_id") or "").strip() or None,
        "file_count": len(files),
        "original_model": original_model,
        "routed_model": original_model,
    }


def annotate_body_with_session_rag_handoff(body: dict[str, Any]) -> dict[str, Any]:
    metadata = body.setdefault("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
        body["metadata"] = metadata
    if "files" not in metadata:
        body_files = _extract_top_level_files(body)
        if body_files:
            metadata["files"] = [copy.deepcopy(item) for item in body_files]
    metadata[SESSION_RAG_HANDOFF_MARKER] = _build_session_rag_handoff_payload(body)
    return body


def prepare_openai_form_data_for_session_rag_handoff(form_data: dict[str, Any]) -> dict[str, Any]:
    prepared = dict(form_data)
    metadata = prepared.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    else:
        metadata = dict(metadata)
    prepared["metadata"] = metadata
    if "files" not in metadata:
        body_files = _extract_top_level_files(prepared)
        if body_files:
            metadata["files"] = [copy.deepcopy(item) for item in body_files]

    body_for_marker = {"metadata": metadata, "files": prepared.get("files"), "model": prepared.get("model")}
    handoff_payload = _build_session_rag_handoff_payload(body_for_marker)
    metadata[SESSION_RAG_HANDOFF_MARKER] = handoff_payload

    files = prepared.get("files")
    if not isinstance(files, list) or not files:
        metadata_files = _extract_metadata_files({"metadata": metadata})
        if metadata_files:
            prepared["files"] = [copy.deepcopy(item) for item in metadata_files]
    if handoff_payload.get("chat_id") and not str(prepared.get("thread_id") or "").strip():
        prepared["thread_id"] = str(handoff_payload["chat_id"])
    if handoff_payload.get("chat_id") and not str(prepared.get("session_id") or "").strip():
        prepared["session_id"] = str(handoff_payload["chat_id"])
    prepared["openwebui_session_rag_handoff"] = handoff_payload
    return prepared


def _extract_tool_call_name(tool_call: dict[str, Any]) -> str:
    function = tool_call.get("function", {})
    if isinstance(function, dict):
        return str(function.get("name") or "").strip()
    return ""


def _normalize_message_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        chunks: list[str] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if text is None:
                continue
            chunks.append(str(text))
        return "".join(chunks).strip()
    if content is None:
        return ""
    return str(content).strip()


def _normalize_output_content(output: Any) -> str:
    if isinstance(output, str):
        return output.strip()
    if isinstance(output, list):
        chunks: list[str] = []
        for part in output:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if text is None:
                continue
            chunks.append(str(text))
        return "".join(chunks).strip()
    if output is None:
        return ""
    return str(output).strip()


def _is_confirmed_long_running_text(text: str) -> bool:
    normalized = str(text or "").strip()
    if "job_id:" in normalized and "status_url:" in normalized:
        return True
    if not normalized or normalized[0] not in "{[":
        return False
    try:
        payload = json.loads(normalized)
    except json.JSONDecodeError:
        return False
    if isinstance(payload, dict):
        return bool(str(payload.get("job_id") or "").strip() and str(payload.get("status_url") or "").strip())
    return False


def _is_tracked_long_running_tool_name(name: str) -> bool:
    return str(name or "").strip() in LONG_RUNNING_TOOL_NAMES


def detect_unconfirmed_long_running_launch(messages: list[dict[str, Any]] | None) -> dict[str, str] | None:
    if not isinstance(messages, list):
        return None

    call_lookup: dict[str, str] = {}
    for message in messages:
        if not isinstance(message, dict):
            continue
        if str(message.get("role") or "").strip() != "assistant":
            continue
        for tool_call in message.get("tool_calls") or []:
            if not isinstance(tool_call, dict):
                continue
            call_id = str(tool_call.get("id") or "").strip()
            if not call_id:
                continue
            call_lookup[call_id] = _extract_tool_call_name(tool_call)

    for message in reversed(messages):
        if not isinstance(message, dict):
            continue
        if str(message.get("role") or "").strip() != "tool":
            continue
        call_id = str(message.get("tool_call_id") or "").strip()
        if not call_id or not _is_tracked_long_running_tool_name(call_lookup.get(call_id, "")):
            continue
        content = _normalize_message_content(message.get("content"))
        if _is_confirmed_long_running_text(content):
            return None
        return {
            "call_id": call_id,
            "content": content,
            "message": build_long_running_tool_launch_error(call_lookup.get(call_id, "")),
        }
    return None


def detect_unconfirmed_long_running_output(output: list[dict[str, Any]] | None) -> dict[str, str] | None:
    if not isinstance(output, list):
        return None

    call_lookup: dict[str, str] = {}
    deep_job_call_ids: set[str] = set()
    for item in output:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "function_call":
            call_id = str(item.get("call_id") or "").strip()
            name = str(item.get("name") or "").strip()
            if call_id:
                call_lookup[call_id] = name
        elif item.get("type") == "open_webui:deep_job":
            tool_call_id = str(item.get("tool_call_id") or "").strip()
            if tool_call_id:
                deep_job_call_ids.add(tool_call_id)

    for item in reversed(output):
        if not isinstance(item, dict):
            continue
        if item.get("type") != "function_call_output":
            continue
        call_id = str(item.get("call_id") or "").strip()
        if call_id in deep_job_call_ids:
            continue
        if not call_id or not _is_tracked_long_running_tool_name(call_lookup.get(call_id, "")):
            continue
        content = _normalize_output_content(item.get("output"))
        if _is_confirmed_long_running_text(content):
            return None
        return {
            "call_id": call_id,
            "content": content,
            "message": build_long_running_tool_launch_error(call_lookup.get(call_id, "")),
        }
    return None


def build_synthetic_launch_error_stream(message: str) -> StreamingResponse:
    async def _iterator():
        yield (
            "data: "
            + json.dumps(
                {"choices": [{"delta": {"role": "assistant"}, "finish_reason": None}]},
                ensure_ascii=False,
            )
            + "\n\n"
        )
        yield (
            "data: "
            + json.dumps(
                {"choices": [{"delta": {"content": message}, "finish_reason": None}]},
                ensure_ascii=False,
            )
            + "\n\n"
        )
        yield (
            "data: "
            + json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}]}, ensure_ascii=False)
            + "\n\n"
        )
        yield "data: [DONE]\n\n"

    return StreamingResponse(_iterator(), media_type="text/event-stream")


async def run_openai_with_session_rag_handoff(
    form_data: dict[str, Any],
    invoke: Callable[[dict[str, Any]], Awaitable[Any]],
    *,
    logger: Any | None = None,
) -> Any:
    if not isinstance(form_data, dict) or not should_enable_session_rag_handoff(form_data):
        return await invoke(form_data)

    prepared = prepare_openai_form_data_for_session_rag_handoff(form_data)
    return await invoke(prepared)
