from __future__ import annotations

import os
import asyncio
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlsplit

import aiohttp
from fastapi import Request


RUNTIME_MODEL_PROXY_TIMEOUT = aiohttp.ClientTimeout(total=20)
RUNTIME_MODEL_STATUS_TIMEOUT = aiohttp.ClientTimeout(total=2)
DEFAULT_UMS_BASE_URL = 'http://127.0.0.1:8090'


class RuntimeModelProxyError(RuntimeError):
    def __init__(self, status_code: int, detail: Any):
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail


def _strip_v1_suffix(url: str) -> str:
    normalized = str(url or '').strip()
    if not normalized:
        return ''
    parsed = urlsplit(normalized)
    if parsed.scheme and parsed.netloc:
        path = parsed.path or ''
        if path.endswith('/v1'):
            path = path[:-3]
        elif path == '/v1':
            path = ''
        return f'{parsed.scheme}://{parsed.netloc}{path}'.rstrip('/')
    return normalized.rstrip('/')


def _resolve_ums_base_url() -> str:
    candidates = [
        os.getenv('UMS_URL'),
        _strip_v1_suffix(os.getenv('RAG_OPENAI_API_BASE_URL', '')),
        os.getenv('AGENT_API_UMS_URL'),
        DEFAULT_UMS_BASE_URL,
    ]
    for candidate in candidates:
        normalized = str(candidate or '').strip().rstrip('/')
        if normalized:
            return normalized
    return DEFAULT_UMS_BASE_URL


def _build_ums_url(endpoint_path: str) -> str:
    base_url = _resolve_ums_base_url().rstrip('/')
    suffix = str(endpoint_path or '').strip()
    if suffix and not suffix.startswith('/'):
        suffix = f'/{suffix}'
    return f'{base_url}{suffix}'


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def is_enabled(request: Request) -> bool:
    app = getattr(request, 'app', None)
    state = getattr(app, 'state', None)
    config = getattr(state, 'config', None)
    if config is None:
        return True
    return bool(getattr(config, 'ENABLE_AGENT_NAVIGATOR_RUNTIME_MODELS', False))


def disabled_status() -> Dict[str, Any]:
    return {
        'enabled': False,
        'available': False,
        'detail': 'runtime-models-disabled',
    }


def disabled_catalog() -> Dict[str, Any]:
    return {
        'models': [],
        'active_model_id': None,
        'active_model_source': None,
    }


def assert_enabled(request: Request) -> None:
    if not is_enabled(request):
        raise RuntimeModelProxyError(404, {'status': 'runtime-models-disabled'})


async def _request_json(
    method: str,
    endpoint_path: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> Any:
    url = _build_ums_url(endpoint_path)
    try:
        async with aiohttp.ClientSession(timeout=RUNTIME_MODEL_PROXY_TIMEOUT, trust_env=True) as session:
            async with session.request(
                method.upper(),
                url,
                params=params,
                json=payload,
                headers={'Accept': 'application/json'},
            ) as response:
                content_type = str(response.headers.get('Content-Type') or '').lower()
                if 'application/json' in content_type:
                    body = await response.json()
                else:
                    body = await response.text()
                if response.status >= 400:
                    detail = body.get('detail', body) if isinstance(body, dict) else body
                    raise RuntimeModelProxyError(response.status, detail)
                return body
    except RuntimeModelProxyError:
        raise
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        raise RuntimeModelProxyError(503, f'runtime-models-backend-unavailable: {exc}') from exc


async def get_status(request: Request) -> Dict[str, Any]:
    if not is_enabled(request):
        return disabled_status()

    url = _build_ums_url('/health')
    try:
        async with aiohttp.ClientSession(timeout=RUNTIME_MODEL_STATUS_TIMEOUT, trust_env=True) as session:
            async with session.get(url, headers={'Accept': 'application/json'}) as response:
                if response.status >= 400:
                    return {
                        'enabled': True,
                        'available': False,
                        'detail': f'runtime-models-backend-status:{response.status}',
                    }
                return {
                    'enabled': True,
                    'available': True,
                    'detail': 'runtime-models-backend-available',
                }
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        return {
            'enabled': True,
            'available': False,
            'detail': f'runtime-models-backend-unavailable: {exc}',
        }


def _normalize_scan_folder_entry(payload: Any) -> Dict[str, Any]:
    body = _as_dict(payload)
    folder = body.get('folder')
    if isinstance(folder, dict):
        return folder
    return body if isinstance(body, dict) else {}


def _runtime_badges_from_catalog_entry(entry: Dict[str, Any]) -> List[str]:
    badges: List[str] = []
    runtime_type = str(entry.get('runtime_type') or '').strip().lower()
    kind = str(entry.get('kind') or '').strip().lower()
    resolved_source = _as_dict(entry.get('resolved_source'))
    if runtime_type in {'gguf', 'gguf-vl'}:
        badges.append('GGUF')
    if runtime_type == 'gguf-vl' or kind == 'vision':
        badges.append('Vision')
    shards = resolved_source.get('shards')
    if isinstance(shards, list) and shards:
        badges.append('Split')
    if not badges and bool(entry.get('user_selectable')):
        badges.append('Local')
    deduped: List[str] = []
    for badge in badges:
        if badge not in deduped:
            deduped.append(badge)
    return deduped


def _normalize_catalog_entry(payload: Any) -> Dict[str, Any]:
    entry = _as_dict(payload)
    return {
        'model_id': str(entry.get('model_id') or '').strip(),
        'display_name': str(entry.get('display_name') or entry.get('model_id') or '').strip(),
        'runtime_type': str(entry.get('runtime_type') or '').strip(),
        'kind': str(entry.get('kind') or '').strip(),
        'status': str(entry.get('status') or '').strip(),
        'catalog_origin': str(entry.get('catalog_origin') or '').strip(),
        'user_selectable': bool(entry.get('user_selectable')),
        'runtime_badges': _runtime_badges_from_catalog_entry(entry),
    }


def _resolved_preview_path(entry: Dict[str, Any]) -> str:
    runtime_type = str(entry.get('runtime_type') or '').strip().lower()
    resolved_source = entry.get('resolved_source') or {}
    if not isinstance(resolved_source, dict):
        raise RuntimeModelProxyError(422, {'status': 'invalid_preview_entry', 'reason': 'resolved_source_required'})
    if runtime_type == 'gguf-vl':
        path = str(resolved_source.get('gguf_path') or '').strip()
    elif runtime_type == 'gguf':
        path = str(resolved_source.get('gguf_path') or resolved_source.get('primary_path') or '').strip()
    else:
        raise RuntimeModelProxyError(
            422,
            {
                'status': 'invalid_preview_entry',
                'reason': f'unsupported_runtime_type:{runtime_type or "unknown"}',
            },
        )
    if not path:
        raise RuntimeModelProxyError(422, {'status': 'invalid_preview_entry', 'reason': 'model_path_required'})
    return path


def build_register_payload(source_path: str, entry: Dict[str, Any]) -> Dict[str, Any]:
    candidate_id = str(entry.get('candidate_id') or '').strip()
    if not candidate_id:
        raise RuntimeModelProxyError(422, {'status': 'invalid_preview_entry', 'reason': 'candidate_id_required'})

    runtime_type = str(entry.get('runtime_type') or '').strip().lower()
    resolved_source = entry.get('resolved_source') or {}
    if not isinstance(resolved_source, dict):
        raise RuntimeModelProxyError(422, {'status': 'invalid_preview_entry', 'reason': 'resolved_source_required'})

    payload: Dict[str, Any] = {
        'model_id': candidate_id,
        'type': runtime_type,
        'path': _resolved_preview_path(entry),
        'display_name': str(entry.get('display_name') or candidate_id),
        'kind': entry.get('kind'),
        'runtime_type': runtime_type,
        'user_selectable': bool(entry.get('user_selectable')),
        'source_path': str(source_path or '').strip() or None,
        'preview_status': str(entry.get('status') or '').strip() or None,
        'status_reason': str(entry.get('status_reason') or '').strip() or None,
        'capabilities': entry.get('capabilities') if isinstance(entry.get('capabilities'), dict) else None,
        'generation_defaults': entry.get('generation_defaults') if isinstance(entry.get('generation_defaults'), dict) else None,
        'load_defaults': entry.get('load_defaults') if isinstance(entry.get('load_defaults'), dict) else None,
    }

    mmproj_path = str(resolved_source.get('mmproj_path') or '').strip()
    if mmproj_path:
        payload['mmproj'] = mmproj_path

    shards = resolved_source.get('shards')
    if isinstance(shards, list) and shards:
        payload['shards'] = [str(item) for item in shards]

    return {key: value for key, value in payload.items() if value is not None}


async def browse_folders(request: Request, path: Optional[str] = None, show_hidden: bool = False) -> Dict[str, Any]:
    assert_enabled(request)
    params: Dict[str, Any] = {'show_hidden': str(bool(show_hidden)).lower()}
    if path:
        params['path'] = path
    return await _request_json('GET', '/models/browse-folders', params=params)


async def list_scan_folders(request: Request) -> Dict[str, Any]:
    assert_enabled(request)
    payload = _request_json('GET', '/models/scan-folders')
    body = await payload
    folders = _as_dict(body).get('folders')
    return {'folders': folders if isinstance(folders, list) else []}


async def add_scan_folder(request: Request, path: str) -> Dict[str, Any]:
    assert_enabled(request)
    body = await _request_json('POST', '/models/scan-folders', payload={'path': path})
    return _normalize_scan_folder_entry(body)


async def delete_scan_folder(request: Request, folder_id: str) -> Dict[str, Any]:
    assert_enabled(request)
    encoded_folder_id = quote(str(folder_id or '').strip(), safe='')
    return await _request_json('DELETE', f'/models/scan-folders/{encoded_folder_id}')


async def preview_path(request: Request, path: str) -> Dict[str, Any]:
    assert_enabled(request)
    return await _request_json('POST', '/models/preview-path', payload={'path': path})


async def list_catalog(request: Request) -> Dict[str, Any]:
    if not is_enabled(request):
        return disabled_catalog()

    body = await _request_json('GET', '/models')
    payload = _as_dict(body)
    items = payload.get('models')
    models = [_normalize_catalog_entry(item) for item in items] if isinstance(items, list) else []
    return {
        'models': models,
        'active_model_id': payload.get('active_model_id'),
        'active_model_source': payload.get('active_model_source'),
    }


async def register_model(request: Request, source_path: str, entry: Dict[str, Any]) -> Dict[str, Any]:
    assert_enabled(request)
    payload = build_register_payload(source_path, entry)
    return await _request_json('POST', '/models/register', payload=payload)


async def unregister_model(request: Request, model_id: str) -> Dict[str, Any]:
    assert_enabled(request)
    encoded_model_id = quote(str(model_id or '').strip(), safe='')
    return await _request_json('DELETE', f'/models/{encoded_model_id}/registration')


async def load_model(request: Request, model_id: str, device_mode: Optional[str] = None) -> Dict[str, Any]:
    assert_enabled(request)
    encoded_model_id = quote(str(model_id or '').strip(), safe='')
    payload: Dict[str, Any] = {}
    if device_mode:
        payload['device_mode'] = device_mode
    return await _request_json('POST', f'/models/{encoded_model_id}/load', payload=payload)


async def get_load_job(request: Request, job_id: str) -> Dict[str, Any]:
    assert_enabled(request)
    encoded_job_id = quote(str(job_id or '').strip(), safe='')
    return await _request_json('GET', f'/model-load-jobs/{encoded_job_id}')


async def cancel_load_job(request: Request, job_id: str) -> Dict[str, Any]:
    assert_enabled(request)
    encoded_job_id = quote(str(job_id or '').strip(), safe='')
    return await _request_json('POST', f'/model-load-jobs/{encoded_job_id}/cancel', payload={})
