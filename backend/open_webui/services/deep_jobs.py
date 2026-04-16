from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional
from urllib.parse import quote, urlsplit

import aiohttp
from fastapi import Request


BOOTSTRAP_CONNECTION_ID = 'llm_tools_platform_openapi_tool_server'
DEEP_JOB_PROXY_TIMEOUT = aiohttp.ClientTimeout(total=10)
DEFAULT_TOOL_SERVER_BASE_URL = 'http://127.0.0.1:8000'
DEFAULT_TOOL_SERVER_TOKEN = 'llm-tools-platform-tool-server-dev-token'


class DeepJobProxyError(RuntimeError):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _parse_connection_headers(raw_headers: Any) -> Dict[str, str]:
    if isinstance(raw_headers, dict):
        return {str(key): str(value) for key, value in raw_headers.items() if value is not None}
    if isinstance(raw_headers, str):
        try:
            parsed = json.loads(raw_headers)
        except Exception:
            return {}
        if isinstance(parsed, dict):
            return {str(key): str(value) for key, value in parsed.items() if value is not None}
    return {}


def _strip_openapi_suffix(path: str) -> str:
    normalized = str(path or '/openapi.json').strip() or '/openapi.json'
    parsed = urlsplit(normalized)
    if parsed.scheme and parsed.netloc:
        normalized = parsed.path or '/openapi.json'
    if not normalized.startswith('/'):
        normalized = f'/{normalized}'
    if normalized.endswith('/openapi.json'):
        return normalized[: -len('/openapi.json')]
    if normalized.endswith('openapi.json'):
        return normalized[: -len('openapi.json')].rstrip('/')
    return normalized.rstrip('/')


def _join_url(base_url: str, base_path: str, endpoint_path: str) -> str:
    left = str(base_url or '').rstrip('/')
    middle = str(base_path or '').strip()
    right = str(endpoint_path or '').strip()
    if middle and not middle.startswith('/'):
        middle = f'/{middle}'
    middle = middle.rstrip('/')
    if right and not right.startswith('/'):
        right = f'/{right}'
    return f'{left}{middle}{right}'


def _build_tool_server_url(connection: Dict[str, Any], endpoint_path: str) -> str:
    raw_path = str(connection.get('path') or '/openapi.json').strip()
    parsed = urlsplit(raw_path)
    if parsed.scheme and parsed.netloc:
        base_url = f'{parsed.scheme}://{parsed.netloc}'
        base_path = _strip_openapi_suffix(parsed.path)
    else:
        base_url = str(connection.get('url') or '').rstrip('/')
        base_path = _strip_openapi_suffix(raw_path)
    return _join_url(base_url, base_path, endpoint_path)


def _is_llm_tools_platform_connection(connection: Dict[str, Any]) -> bool:
    config = connection.get('config') or {}
    bootstrap_id = str(config.get('bootstrap_id') or '').strip()
    if bootstrap_id == BOOTSTRAP_CONNECTION_ID:
        return True
    path = str(connection.get('path') or '').strip()
    return 'tool-server/openapi.json' in path


def _build_fallback_tool_server_connection() -> Dict[str, Any] | None:
    base_url = str(
        os.getenv('LLM_TOOLS_PLATFORM_TOOL_SERVER_BASE_URL')
        or os.getenv('AGENT_API_BASE_URL')
        or DEFAULT_TOOL_SERVER_BASE_URL
    ).strip()
    if not base_url:
        return None

    token = str(os.getenv('OPENAPI_TOOL_SERVER_TOKEN') or DEFAULT_TOOL_SERVER_TOKEN).strip()

    return {
        'url': base_url.rstrip('/'),
        'path': '/tool-server/openapi.json',
        'type': 'openapi',
        'auth_type': 'bearer',
        'headers': {},
        'key': token,
        'config': {
            'enable': True,
            'bootstrap_id': BOOTSTRAP_CONNECTION_ID,
            'name': 'llm-tools-platform OpenAPI Tool Server',
        },
    }


def resolve_tool_server_connection(request: Request) -> Dict[str, Any]:
    connections = list(getattr(request.app.state.config, 'TOOL_SERVER_CONNECTIONS', []) or [])
    openapi_connections = [conn for conn in connections if str(conn.get('type', 'openapi')).strip() == 'openapi']
    for connection in openapi_connections:
        if _is_llm_tools_platform_connection(connection):
            return connection
    if openapi_connections:
        return openapi_connections[0]
    fallback_connection = _build_fallback_tool_server_connection()
    if fallback_connection is not None:
        return fallback_connection
    raise DeepJobProxyError(503, 'deep-job-tool-server-not-configured')


def build_tool_server_request_headers(connection: Dict[str, Any]) -> Dict[str, str]:
    headers = {
        'Accept': 'application/json',
        **_parse_connection_headers(connection.get('headers')),
    }
    auth_type = str(connection.get('auth_type') or 'none').strip().lower()
    key = str(connection.get('key') or '').strip()
    if auth_type == 'bearer' and key:
        headers.setdefault('Authorization', f'Bearer {key}')
    return headers


def _normalize_progress(raw_progress: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw_progress, dict):
        return None
    current = raw_progress.get('current')
    total = raw_progress.get('total')
    unit = raw_progress.get('unit')
    if current is not None or total is not None or unit is not None:
        return {
            'current': current,
            'total': total,
            'unit': unit,
        }
    fraction = raw_progress.get('fraction')
    if fraction is not None:
        try:
            normalized_fraction = float(fraction)
        except (TypeError, ValueError):
            return None
        bounded_fraction = max(0.0, min(1.0, normalized_fraction))
        return {
            'current': int(round(bounded_fraction * 100)),
            'total': 100,
            'unit': 'percent',
        }
    return None


def _normalize_steps(raw_status: Dict[str, Any]) -> list[Dict[str, Any]]:
    fallback_ts = raw_status.get('completed_at') or raw_status.get('started_at') or raw_status.get('submitted_at')
    normalized: list[Dict[str, Any]] = []
    for item in raw_status.get('status_history') or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get('content') or item.get('title') or item.get('key') or '').strip()
        if not text:
            continue
        phase = str(item.get('key') or '').strip() or None
        level = str(item.get('level') or 'info').strip() or 'info'
        ts = item.get('updated_at') or fallback_ts
        normalized.append(
            {
                'ts': str(ts) if ts is not None else None,
                'level': level,
                'phase': phase,
                'text': text,
            }
        )
    return normalized


def normalize_tool_job_snapshot(raw_status: Dict[str, Any], *, chat_id: Optional[str] = None) -> Dict[str, Any]:
    raw_state = str(raw_status.get('status') or 'queued').strip() or 'queued'
    cancel_requested = raw_state == 'cancelling'
    normalized_state = 'running' if cancel_requested else raw_state
    progress = _normalize_progress(raw_status.get('progress'))
    phase = str(raw_status.get('current_stage') or '').strip() or None
    if not phase and isinstance(raw_status.get('progress'), dict):
        phase = str(raw_status['progress'].get('phase') or '').strip() or None
    error_summary = str(raw_status.get('error_summary') or '').strip() or None
    summary = str(raw_status.get('status_text') or '').strip() or str(raw_status.get('result_preview') or '').strip() or error_summary or None
    result_message_id = str(raw_status.get('result_message_id') or '').strip() or None
    updated_at = raw_status.get('completed_at') or raw_status.get('started_at') or raw_status.get('submitted_at')
    normalized_chat_id = str(raw_status.get('chat_id') or chat_id or '').strip() or None

    return {
        'job_id': str(raw_status.get('job_id') or '').strip(),
        'chat_id': normalized_chat_id,
        'state': normalized_state,
        'phase': phase,
        'summary': summary,
        'progress': progress,
        'steps': _normalize_steps(raw_status),
        'cancel_requested': cancel_requested,
        'result_message_id': result_message_id,
        'error': ({'summary': error_summary} if error_summary else None),
        'updated_at': str(updated_at) if updated_at is not None else None,
    }


async def _request_tool_server_json(request: Request, *, method: str, endpoint_path: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    connection = resolve_tool_server_connection(request)
    url = _build_tool_server_url(connection, endpoint_path)
    headers = build_tool_server_request_headers(connection)
    if payload is not None:
        headers.setdefault('Content-Type', 'application/json')

    async with aiohttp.ClientSession(timeout=DEEP_JOB_PROXY_TIMEOUT, trust_env=True) as session:
        async with session.request(method.upper(), url, headers=headers, json=payload) as response:
            try:
                body: Any = await response.json(content_type=None)
            except Exception:
                body = {'detail': await response.text()}

            if response.status >= 400:
                detail = body.get('detail') if isinstance(body, dict) else None
                raise DeepJobProxyError(response.status, str(detail or f'deep-job-tool-server-http-{response.status}'))
            if not isinstance(body, dict):
                raise DeepJobProxyError(502, 'deep-job-tool-server-invalid-response')
            return body


async def get_deep_job_snapshot(request: Request, job_id: str) -> Dict[str, Any]:
    payload = await _request_tool_server_json(request, method='GET', endpoint_path=f'/tool-jobs/{quote(job_id, safe="")}')
    return normalize_tool_job_snapshot(payload)


def normalize_deep_job_result_payload(raw_result: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(raw_result, dict):
        raise DeepJobProxyError(502, 'deep-job-tool-server-invalid-result')

    structured_result = raw_result.get('structured_result')
    if not isinstance(structured_result, dict):
        structured_result = {}

    execution_metadata = raw_result.get('execution_metadata')
    if not isinstance(execution_metadata, dict):
        execution_metadata = {}

    def _normalize_list(value: Any) -> list[Any]:
        return value if isinstance(value, list) else []

    return {
        'status': str(raw_result.get('status') or 'completed').strip() or 'completed',
        'tool_name': str(raw_result.get('tool_name') or '').strip(),
        'assistant_message': str(raw_result.get('assistant_message') or '').strip(),
        'structured_result': structured_result,
        'sources': _normalize_list(raw_result.get('sources')),
        'artifacts': _normalize_list(raw_result.get('artifacts')),
        'embeds': _normalize_list(raw_result.get('embeds')),
        'available_actions': _normalize_list(raw_result.get('available_actions')),
        'execution_metadata': execution_metadata,
    }


async def get_deep_job_result_payload(request: Request, job_id: str) -> Dict[str, Any]:
    payload = await _request_tool_server_json(
        request,
        method='GET',
        endpoint_path=f'/tool-jobs/{quote(job_id, safe="")}/result',
    )
    return normalize_deep_job_result_payload(payload)


def _resolve_artifact_download_url(connection: Dict[str, Any], artifact_url: str) -> str:
    parsed = urlsplit(str(artifact_url or '').strip())
    if parsed.scheme and parsed.netloc:
        return artifact_url
    base_url = str(connection.get('url') or '').rstrip('/')
    path = str(artifact_url or '').strip()
    if not path.startswith('/'):
        path = f'/{path}'
    return f'{base_url}{path}'


def _resolve_artifact_download_filename(
    artifact: Dict[str, Any],
    response_headers: 'aiohttp.typedefs.LooseHeaders',
) -> str | None:
    content_disposition = str(response_headers.get('Content-Disposition') or '').strip()
    if 'filename=' in content_disposition:
        quoted_filename = content_disposition.split('filename=', 1)[1].strip().strip('"')
        if quoted_filename:
            return quoted_filename

    metadata = artifact.get('metadata')
    if isinstance(metadata, dict):
        metadata_filename = str(metadata.get('filename') or '').strip()
        if metadata_filename:
            return metadata_filename

    artifact_id = str(artifact.get('artifact_id') or '').strip()
    return artifact_id or None


async def download_deep_job_artifact(request: Request, job_id: str, artifact_id: str) -> Dict[str, Any]:
    result_payload = await get_deep_job_result_payload(request, job_id)
    artifacts = result_payload.get('artifacts')
    if not isinstance(artifacts, list):
        raise DeepJobProxyError(404, f'deep-job-artifact-not-found:{artifact_id}')

    target_artifact: Dict[str, Any] | None = None
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        current_artifact_id = str(artifact.get('artifact_id') or '').strip()
        if current_artifact_id == artifact_id:
            target_artifact = artifact
            break

    if target_artifact is None:
        raise DeepJobProxyError(404, f'deep-job-artifact-not-found:{artifact_id}')

    artifact_url = str(target_artifact.get('url') or '').strip()
    if not artifact_url:
        raise DeepJobProxyError(404, f'deep-job-artifact-url-missing:{artifact_id}')

    connection = resolve_tool_server_connection(request)
    download_url = _resolve_artifact_download_url(connection, artifact_url)
    headers = build_tool_server_request_headers(connection)

    async with aiohttp.ClientSession(timeout=DEEP_JOB_PROXY_TIMEOUT, trust_env=True) as session:
        async with session.get(download_url, headers=headers) as response:
            content = await response.read()
            if response.status >= 400:
                detail = content.decode('utf-8', errors='replace') or f'deep-job-artifact-http-{response.status}'
                raise DeepJobProxyError(response.status, detail)
            return {
                'content': content,
                'content_type': str(response.headers.get('Content-Type') or 'application/octet-stream'),
                'content_disposition': str(response.headers.get('Content-Disposition') or '').strip() or None,
                'filename': _resolve_artifact_download_filename(target_artifact, response.headers),
            }


async def record_deep_job_delivery(
    request: Request,
    job_id: str,
    result_message_id: str,
    terminal_emitted_at: Optional[str] = None,
) -> Dict[str, Any]:
    payload = {
        'result_message_id': str(result_message_id or '').strip(),
    }
    if terminal_emitted_at is not None:
        payload['terminal_emitted_at'] = str(terminal_emitted_at)

    response = await _request_tool_server_json(
        request,
        method='POST',
        endpoint_path=f'/tool-jobs/{quote(job_id, safe="")}/delivery',
        payload=payload,
    )
    return normalize_tool_job_snapshot(response)


async def cancel_deep_job_snapshot(request: Request, job_id: str) -> Dict[str, Any]:
    payload = await _request_tool_server_json(request, method='POST', endpoint_path=f'/tool-jobs/{quote(job_id, safe="")}/cancel')
    return normalize_tool_job_snapshot(payload)


async def get_active_deep_job_snapshot(request: Request, chat_id: str) -> Optional[Dict[str, Any]]:
    payload = await _request_tool_server_json(request, method='GET', endpoint_path=f'/tool-jobs/active/chat/{quote(chat_id, safe="")}')
    job = payload.get('job')
    if not isinstance(job, dict):
        return None
    return normalize_tool_job_snapshot(job, chat_id=chat_id)
