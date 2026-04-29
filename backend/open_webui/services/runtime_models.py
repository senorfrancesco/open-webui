from __future__ import annotations

import os
import asyncio
import copy
import hashlib
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlsplit

import aiohttp
from fastapi import Request


RUNTIME_MODEL_PROXY_TIMEOUT = aiohttp.ClientTimeout(total=20)
RUNTIME_MODEL_STATUS_TIMEOUT = aiohttp.ClientTimeout(total=2)
DEFAULT_UMS_BASE_URL = 'http://127.0.0.1:8090'
DEFAULT_SCAN_MAX_DEPTH = int(os.getenv('OPENWEBUI_RUNTIME_MODEL_SCAN_MAX_DEPTH', '4'))
DEFAULT_SCAN_MAX_FILES = int(os.getenv('OPENWEBUI_RUNTIME_MODEL_SCAN_MAX_FILES', '5000'))
DEFAULT_SCAN_MAX_DURATION_SECONDS = float(os.getenv('OPENWEBUI_RUNTIME_MODEL_SCAN_MAX_DURATION_SECONDS', '30'))
_SPLIT_GGUF_RE = re.compile(r'^(?P<base>.+)-(?P<index>\d{5})-of-(?P<total>\d{5})\.gguf$', re.IGNORECASE)
_ADAPTER_HINT_FILENAMES = {'adapter_config.json', 'adapter_model.safetensors'}
_MODEL_CATALOG_STATUS_READY = 'ready'
_MODEL_CATALOG_STATUS_INCOMPLETE = 'incomplete'
_MODEL_CATALOG_STATUS_AMBIGUOUS = 'ambiguous'
_MODEL_CATALOG_STATUS_UNSUPPORTED = 'unsupported'
_SCAN_TERMINAL_STATES = {'completed', 'cancelled', 'failed'}
_SCAN_JOBS: Dict[str, Dict[str, Any]] = {}
_SCAN_CANCEL_FLAGS: Dict[str, threading.Event] = {}


class RuntimeModelProxyError(RuntimeError):
    def __init__(self, status_code: int, detail: Any):
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail


class RuntimeModelScanCancelled(RuntimeError):
    pass


class RuntimeModelScanLimitExceeded(RuntimeError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


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


def _scan_folder_id(path: Path) -> str:
    return hashlib.sha1(str(path).encode('utf-8')).hexdigest()[:12]


def _normalize_existing_path(path_str: str) -> Path:
    normalized = Path(str(path_str or '').strip()).expanduser().resolve()
    if not normalized.exists():
        raise RuntimeModelProxyError(422, f'Path not found: {normalized}')
    return normalized


def _path_is_within(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def _normalize_scan_folder_entry(path: Path, *, added_at: Optional[int] = None) -> Dict[str, Any]:
    try:
        normalized_added_at = int(added_at or time.time())
    except (TypeError, ValueError):
        normalized_added_at = int(time.time())
    return {
        'id': _scan_folder_id(path),
        'path': str(path),
        'name': path.name or str(path),
        'added_at': normalized_added_at,
    }


def _get_app_config(request: Request) -> Any:
    return getattr(getattr(getattr(request, 'app', None), 'state', None), 'config', None)


def _fallback_state(request: Request) -> Any:
    return getattr(getattr(request, 'app', None), 'state', None)


def _normalise_saved_scan_folders(raw_folders: Any) -> List[Dict[str, Any]]:
    folders = raw_folders if isinstance(raw_folders, list) else []
    normalized: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for entry in folders:
        raw_path = str(_as_dict(entry).get('path') or '').strip()
        if not raw_path:
            continue
        try:
            path = _normalize_existing_path(raw_path)
        except RuntimeModelProxyError:
            continue
        if not path.is_dir():
            continue
        folder_id = _scan_folder_id(path)
        if folder_id in seen:
            continue
        normalized.append(_normalize_scan_folder_entry(path, added_at=_as_dict(entry).get('added_at')))
        seen.add(folder_id)
    return sorted(normalized, key=lambda item: str(item.get('path') or ''))


def _get_saved_scan_folders(request: Request) -> List[Dict[str, Any]]:
    config = _get_app_config(request)
    if config is not None and hasattr(config, 'RUNTIME_MODEL_SCAN_FOLDERS'):
        return _normalise_saved_scan_folders(getattr(config, 'RUNTIME_MODEL_SCAN_FOLDERS', []))
    state = _fallback_state(request)
    if state is not None:
        return _normalise_saved_scan_folders(getattr(state, 'runtime_model_scan_folders', []))
    return []


def _set_saved_scan_folders(request: Request, folders: List[Dict[str, Any]]) -> None:
    normalized = _normalise_saved_scan_folders(folders)
    config = _get_app_config(request)
    if config is not None and hasattr(config, 'RUNTIME_MODEL_SCAN_FOLDERS'):
        setattr(config, 'RUNTIME_MODEL_SCAN_FOLDERS', normalized)
        return
    state = _fallback_state(request)
    if state is not None:
        setattr(state, 'runtime_model_scan_folders', normalized)


def _candidate_allowlist_paths(request: Request) -> List[Path]:
    candidates: List[Path] = [Path.home()]
    extra_roots_raw = str(os.getenv('OPENWEBUI_RUNTIME_MODEL_BROWSE_ALLOWLIST_ROOTS') or '').strip()
    if extra_roots_raw:
        candidates.extend(Path(item).expanduser() for item in extra_roots_raw.split(os.pathsep) if item.strip())
    for env_name, env_value in os.environ.items():
        if not env_name.startswith('MODEL_PATH_'):
            continue
        raw_value = str(env_value or '').strip()
        if raw_value:
            candidates.append(Path(raw_value).expanduser())
    for folder in _get_saved_scan_folders(request):
        raw_path = str(folder.get('path') or '').strip()
        if raw_path:
            candidates.append(Path(raw_path).expanduser())
    return candidates


def _browse_allowlist_roots(request: Request) -> List[Path]:
    roots: List[Path] = []
    seen: set[str] = set()
    for candidate in _candidate_allowlist_paths(request):
        try:
            resolved = candidate.resolve()
        except Exception:
            continue
        if resolved.is_file():
            resolved = resolved.parent
        if not resolved.exists() or not resolved.is_dir():
            continue
        key = str(resolved)
        if key in seen:
            continue
        roots.append(resolved)
        seen.add(key)
    return sorted(roots, key=lambda item: str(item))


def _assert_browse_allowed(request: Request, path: Path) -> Path:
    resolved = _normalize_existing_path(str(path))
    if not resolved.is_dir():
        raise RuntimeModelProxyError(422, f'Directory expected: {resolved}')
    for root in _browse_allowlist_roots(request):
        if _path_is_within(resolved, root):
            return resolved
    raise RuntimeModelProxyError(403, f'Path is outside allowed roots: {resolved}')


def _count_model_file_hints(directory: Path) -> int:
    try:
        children = list(directory.iterdir())
    except OSError:
        return 0
    hint_count = 0
    for child in children:
        try:
            if not child.is_file():
                continue
        except OSError:
            continue
        if child.suffix.lower() in {'.gguf', '.safetensors'}:
            hint_count += 1
    return hint_count


def _browse_folder_signals(directory: Path) -> Dict[str, bool]:
    signals = {
        'has_gguf': False,
        'has_safetensors': False,
        'has_adapter': False,
        'has_config': False,
    }
    try:
        children = list(directory.iterdir())
    except OSError:
        return signals
    for child in children:
        try:
            if not child.is_file():
                continue
        except OSError:
            continue
        name = child.name.lower()
        suffix = child.suffix.lower()
        if suffix == '.gguf':
            signals['has_gguf'] = True
        if suffix == '.safetensors':
            signals['has_safetensors'] = True
        if name == 'config.json':
            signals['has_config'] = True
        if name in _ADAPTER_HINT_FILENAMES:
            signals['has_adapter'] = True
    return signals


def _browse_folder_tags(signals: Dict[str, bool]) -> List[str]:
    tags: List[str] = []
    if bool(signals.get('has_gguf')):
        tags.append('GGUF')
    if bool(signals.get('has_adapter')):
        tags.append('Adapter')
    if bool(signals.get('has_safetensors')):
        tags.append('Safetensors')
    if bool(signals.get('has_config')):
        tags.append('Config')
    return tags


def _browse_entry_payload(directory: Path, *, source: str = 'directory') -> Dict[str, Any]:
    signals = _browse_folder_signals(directory)
    return {
        'name': directory.name or str(directory),
        'path': str(directory),
        'source': source,
        'looks_like_model_dir': any(bool(value) for value in signals.values()),
        'model_file_count_hint': _count_model_file_hints(directory),
        'folder_signals': signals,
        'folder_tags': _browse_folder_tags(signals),
    }


def _split_family_key(name: str) -> str:
    raw_name = Path(name).name
    stem = raw_name[:-5] if raw_name.lower().endswith('.gguf') else raw_name
    stem = stem.lower()
    match = _SPLIT_GGUF_RE.match(raw_name)
    if match:
        stem = match.group('base').lower()
    suffix_re = re.compile(r'-(q\d+(_k|_\d+)?(_[a-z])?|f16|fp16|bf16|q4|q5|q6|q8|merged|instruct|chat)$')
    while True:
        updated = suffix_re.sub('', stem)
        if updated == stem:
            break
        stem = updated
    stem = stem.replace('mmproj-', '')
    stem = stem.replace('projector-', '')
    return re.sub(r'[^a-z0-9]+', '-', stem).strip('-')


def _slugify_candidate_id(name: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-') or 'model'


def _display_name_from_path(path: Path) -> str:
    raw_name = path.name
    stem = raw_name[:-5] if raw_name.lower().endswith('.gguf') else raw_name
    return stem.replace('_', ' ').replace('-', ' ').strip() or raw_name


def _is_mmproj_artifact(path: Path) -> bool:
    name = path.name.lower()
    return 'mmproj' in name or 'projector' in name


def _looks_like_vision_model(path: Path) -> bool:
    stem = path.stem.lower()
    return bool(re.search(r'(^|[-_])vl([_-]|$)', stem)) or 'vision' in stem


def _match_mmproj_candidates(model_path: Path, mmproj_files: List[Path]) -> List[Path]:
    if not mmproj_files:
        return []
    model_key = _split_family_key(model_path.name)
    exact_matches = [candidate for candidate in mmproj_files if _split_family_key(candidate.name) == model_key]
    if exact_matches:
        return exact_matches
    loose_matches = [
        candidate
        for candidate in mmproj_files
        if model_key and (_split_family_key(candidate.name) in model_key or model_key in _split_family_key(candidate.name))
    ]
    if loose_matches:
        return loose_matches
    if len(mmproj_files) == 1:
        return list(mmproj_files)
    return []


def _split_group_payload(shards: List[Path]) -> Dict[str, Any]:
    ordered = sorted(shards, key=lambda item: item.name.lower())
    match = _SPLIT_GGUF_RE.match(ordered[0].name)
    total = int(match.group('total')) if match else len(ordered)
    base_name = match.group('base') if match else ordered[0].stem
    family_key = _split_family_key(base_name)
    present_indices = {
        int(_SPLIT_GGUF_RE.match(item.name).group('index'))  # type: ignore[union-attr]
        for item in ordered
        if _SPLIT_GGUF_RE.match(item.name)
    }
    return {
        'family_key': family_key,
        'display_name': _display_name_from_path(Path(base_name)),
        'primary_path': str(ordered[0]),
        'shards': [str(item) for item in ordered],
        'complete': len(ordered) == total and present_indices == set(range(1, total + 1)),
        'total': total,
    }


def _preview_entry_payload(
    *,
    candidate_id: str,
    display_name: str,
    kind: str,
    runtime_type: str,
    status: str,
    status_reason: str,
    user_selectable: bool,
    resolved_source: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        'candidate_id': candidate_id,
        'display_name': display_name,
        'kind': kind,
        'runtime_type': runtime_type,
        'status': status,
        'status_reason': status_reason,
        'user_selectable': user_selectable,
        'resolved_source': resolved_source,
    }


def _check_scan_limits(
    *,
    started_at: float,
    files_seen: int,
    max_files: int,
    max_duration_seconds: float,
    cancel_event: Optional[threading.Event] = None,
) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise RuntimeModelScanCancelled()
    if files_seen > max_files:
        raise RuntimeModelScanLimitExceeded('max_files_exceeded')
    if time.monotonic() - started_at > max_duration_seconds:
        raise RuntimeModelScanLimitExceeded('max_duration_exceeded')


def _iter_scan_files(
    source_path: Path,
    *,
    show_hidden: bool = False,
    max_depth: int = DEFAULT_SCAN_MAX_DEPTH,
    max_files: int = DEFAULT_SCAN_MAX_FILES,
    max_duration_seconds: float = DEFAULT_SCAN_MAX_DURATION_SECONDS,
    cancel_event: Optional[threading.Event] = None,
    progress: Optional[Dict[str, Any]] = None,
) -> List[Path]:
    started_at = time.monotonic()
    files: List[Path] = []
    stack: List[tuple[Path, int]] = [(source_path, 0)]
    visited_dirs: set[str] = set()
    progress_payload = progress if isinstance(progress, dict) else {}
    progress_payload.setdefault('files_seen', 0)
    progress_payload.setdefault('directories_seen', 0)

    while stack:
        current_dir, depth = stack.pop()
        _check_scan_limits(
            started_at=started_at,
            files_seen=len(files),
            max_files=max_files,
            max_duration_seconds=max_duration_seconds,
            cancel_event=cancel_event,
        )
        try:
            resolved_dir = current_dir.resolve()
        except OSError:
            continue
        if str(resolved_dir) in visited_dirs:
            continue
        if not _path_is_within(resolved_dir, source_path):
            continue
        visited_dirs.add(str(resolved_dir))
        progress_payload['directories_seen'] = int(progress_payload.get('directories_seen') or 0) + 1

        try:
            children = sorted(current_dir.iterdir(), key=lambda item: item.name.lower())
        except OSError:
            continue
        for child in children:
            _check_scan_limits(
                started_at=started_at,
                files_seen=len(files),
                max_files=max_files,
                max_duration_seconds=max_duration_seconds,
                cancel_event=cancel_event,
            )
            if not show_hidden and child.name.startswith('.'):
                continue
            try:
                resolved_child = child.resolve()
            except OSError:
                continue
            if not _path_is_within(resolved_child, source_path):
                continue
            try:
                if child.is_dir():
                    if depth < max_depth:
                        stack.append((child, depth + 1))
                    continue
                if not child.is_file():
                    continue
            except OSError:
                continue
            files.append(resolved_child)
            progress_payload['files_seen'] = len(files)

    return files


def _preview_model_directory(
    request: Request,
    path_str: str,
    *,
    cancel_event: Optional[threading.Event] = None,
    progress: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    source_path = _assert_browse_allowed(request, Path(path_str))
    warnings_payload: List[Dict[str, str]] = []
    entries: List[Dict[str, Any]] = []

    try:
        files = _iter_scan_files(source_path, cancel_event=cancel_event, progress=progress)
    except RuntimeModelScanCancelled:
        raise
    except RuntimeModelScanLimitExceeded as exc:
        raise RuntimeModelProxyError(422, {'status': 'scan_limit_exceeded', 'reason': exc.reason}) from exc

    adapter_artifacts = [item for item in files if item.name.lower() in _ADAPTER_HINT_FILENAMES]
    if adapter_artifacts:
        entries.append(
            _preview_entry_payload(
                candidate_id=_slugify_candidate_id(f'{source_path.name}-adapter'),
                display_name=f'{source_path.name} adapter',
                kind='adapter',
                runtime_type='transformers-adapter',
                status=_MODEL_CATALOG_STATUS_UNSUPPORTED,
                status_reason='adapter_followup_slice',
                user_selectable=False,
                resolved_source={'adapter_path': str(source_path)},
            )
        )

    gguf_files = [item for item in files if item.suffix.lower() == '.gguf']
    mmproj_files = [item for item in gguf_files if _is_mmproj_artifact(item)]
    candidate_gguf_files = [item for item in gguf_files if not _is_mmproj_artifact(item)]

    split_groups: Dict[str, List[Path]] = {}
    standalone_gguf: List[Path] = []
    for item in candidate_gguf_files:
        match = _SPLIT_GGUF_RE.match(item.name)
        if match:
            family_key = _split_family_key(match.group('base'))
            split_groups.setdefault(family_key, []).append(item)
            continue
        standalone_gguf.append(item)

    preferred_family_keys: set[str] = set()
    for model_path in sorted(standalone_gguf, key=lambda item: item.name.lower()):
        family_key = _split_family_key(model_path.name)
        preferred_family_keys.add(family_key)
        display_name = _display_name_from_path(model_path)
        if _looks_like_vision_model(model_path):
            mmproj_candidates = _match_mmproj_candidates(model_path, mmproj_files)
            if len(mmproj_candidates) > 1:
                entries.append(
                    _preview_entry_payload(
                        candidate_id=_slugify_candidate_id(family_key or model_path.stem),
                        display_name=display_name,
                        kind='vision',
                        runtime_type='gguf-vl',
                        status=_MODEL_CATALOG_STATUS_AMBIGUOUS,
                        status_reason='multiple_mmproj_candidates',
                        user_selectable=False,
                        resolved_source={
                            'gguf_path': str(model_path),
                            'mmproj_candidates': [str(item) for item in mmproj_candidates],
                        },
                    )
                )
                continue
            if not mmproj_candidates:
                entries.append(
                    _preview_entry_payload(
                        candidate_id=_slugify_candidate_id(family_key or model_path.stem),
                        display_name=display_name,
                        kind='vision',
                        runtime_type='gguf-vl',
                        status=_MODEL_CATALOG_STATUS_INCOMPLETE,
                        status_reason='missing_mmproj_path',
                        user_selectable=False,
                        resolved_source={'gguf_path': str(model_path)},
                    )
                )
                continue
            entries.append(
                _preview_entry_payload(
                    candidate_id=_slugify_candidate_id(family_key or model_path.stem),
                    display_name=display_name,
                    kind='vision',
                    runtime_type='gguf-vl',
                    status=_MODEL_CATALOG_STATUS_READY,
                    status_reason='configured',
                    user_selectable=True,
                    resolved_source={'gguf_path': str(model_path), 'mmproj_path': str(mmproj_candidates[0])},
                )
            )
            continue
        entries.append(
            _preview_entry_payload(
                candidate_id=_slugify_candidate_id(family_key or model_path.stem),
                display_name=display_name,
                kind='llm',
                runtime_type='gguf',
                status=_MODEL_CATALOG_STATUS_READY,
                status_reason='configured',
                user_selectable=True,
                resolved_source={'gguf_path': str(model_path)},
            )
        )

    for family_key, shards in sorted(split_groups.items(), key=lambda item: item[0]):
        group = _split_group_payload(shards)
        if family_key in preferred_family_keys:
            warnings_payload.append(
                {
                    'code': 'split_candidate_omitted',
                    'message': f"Split GGUF for {group['display_name']} omitted because merged artifact is preferred",
                }
            )
            continue
        entries.append(
            _preview_entry_payload(
                candidate_id=_slugify_candidate_id(group['family_key']),
                display_name=str(group['display_name']),
                kind='llm',
                runtime_type='gguf',
                status=_MODEL_CATALOG_STATUS_READY if bool(group['complete']) else _MODEL_CATALOG_STATUS_INCOMPLETE,
                status_reason='configured' if bool(group['complete']) else 'missing_split_shards',
                user_selectable=bool(group['complete']),
                resolved_source={'primary_path': str(group['primary_path']), 'shards': list(group['shards'])},
            )
        )

    if not entries and (source_path / 'config.json').exists():
        entries.append(
            _preview_entry_payload(
                candidate_id=_slugify_candidate_id(source_path.name),
                display_name=source_path.name,
                kind='embedding',
                runtime_type='st',
                status=_MODEL_CATALOG_STATUS_UNSUPPORTED,
                status_reason='st_followup_slice',
                user_selectable=False,
                resolved_source={'directory_path': str(source_path)},
            )
        )

    return {
        'source_path': str(source_path),
        'entries': entries,
        'warnings': warnings_payload,
    }


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
    if path:
        current_path = _assert_browse_allowed(request, Path(path))
        allowed_roots = _browse_allowlist_roots(request)
        try:
            raw_children = sorted(current_path.iterdir(), key=lambda item: item.name.lower())
        except OSError as exc:
            raise RuntimeModelProxyError(422, f'Failed to read directory: {exc}') from exc
        children: List[Path] = []
        for child in raw_children:
            if not show_hidden and child.name.startswith('.'):
                continue
            try:
                resolved_child = child.resolve()
                if not child.is_dir():
                    continue
            except OSError:
                continue
            if not any(_path_is_within(resolved_child, root) for root in allowed_roots):
                continue
            children.append(child)
        parent_path = current_path.parent
        parent_allowed = any(_path_is_within(parent_path, root) for root in allowed_roots)
        return {
            'current_path': str(current_path),
            'parent_path': str(parent_path) if parent_allowed else None,
            'entries': [_browse_entry_payload(child) for child in children],
        }

    roots = _browse_allowlist_roots(request)
    return {
        'current_path': None,
        'parent_path': None,
        'entries': [_browse_entry_payload(root, source='allowlist_root') for root in roots],
    }


async def list_scan_folders(request: Request) -> Dict[str, Any]:
    assert_enabled(request)
    return {'folders': _get_saved_scan_folders(request)}


async def add_scan_folder(request: Request, path: str) -> Dict[str, Any]:
    assert_enabled(request)
    resolved_path = _normalize_existing_path(path)
    if not resolved_path.is_dir():
        raise RuntimeModelProxyError(422, f'Directory expected: {resolved_path}')
    folders = _get_saved_scan_folders(request)
    normalized_entry = _normalize_scan_folder_entry(resolved_path)
    for existing in folders:
        if str(existing.get('id') or '') == normalized_entry['id']:
            return existing
    folders.append(normalized_entry)
    _set_saved_scan_folders(request, folders)
    return normalized_entry


async def delete_scan_folder(request: Request, folder_id: str) -> Dict[str, Any]:
    assert_enabled(request)
    normalized_id = str(folder_id or '').strip()
    folders = _get_saved_scan_folders(request)
    filtered = [folder for folder in folders if str(folder.get('id') or '') != normalized_id]
    if len(filtered) == len(folders):
        raise RuntimeModelProxyError(404, f'Scan folder {normalized_id} not found')
    _set_saved_scan_folders(request, filtered)
    return {'status': 'success', 'folder_id': normalized_id}


async def preview_path(request: Request, path: str) -> Dict[str, Any]:
    assert_enabled(request)
    return await asyncio.to_thread(_preview_model_directory, request, path)


def _scan_job_payload(job: Dict[str, Any]) -> Dict[str, Any]:
    payload = copy.deepcopy(job)
    payload['status'] = payload.get('state')
    return payload


def _get_scan_job_or_404(job_id: str) -> Dict[str, Any]:
    normalized_job_id = str(job_id or '').strip()
    job = _SCAN_JOBS.get(normalized_job_id)
    if not job:
        raise RuntimeModelProxyError(404, f'Scan job {normalized_job_id} not found')
    return job


async def _run_scan_job(job_id: str, request: Request, path: str) -> None:
    job = _SCAN_JOBS[job_id]
    cancel_event = _SCAN_CANCEL_FLAGS[job_id]
    job['state'] = 'running'
    job['started_at'] = int(time.time())
    job['updated_at'] = int(time.time())
    try:
        result = await asyncio.to_thread(
            _preview_model_directory,
            request,
            path,
            cancel_event=cancel_event,
            progress=job['progress'],
        )
    except RuntimeModelScanCancelled:
        job['state'] = 'cancelled'
        job['cancelled_at'] = int(time.time())
    except RuntimeModelProxyError as exc:
        job['state'] = 'failed'
        job['error'] = exc.detail
    except Exception as exc:
        job['state'] = 'failed'
        job['error'] = str(exc)
    else:
        job['state'] = 'completed'
        job['result'] = result
        job['completed_at'] = int(time.time())
    finally:
        job['updated_at'] = int(time.time())
        _SCAN_CANCEL_FLAGS.pop(job_id, None)


async def create_scan_job(request: Request, path: str) -> Dict[str, Any]:
    assert_enabled(request)
    source_path = _assert_browse_allowed(request, Path(path))
    job_id = uuid.uuid4().hex
    now = int(time.time())
    _SCAN_JOBS[job_id] = {
        'job_id': job_id,
        'state': 'queued',
        'path': str(source_path),
        'created_at': now,
        'updated_at': now,
        'progress': {'files_seen': 0, 'directories_seen': 0},
        'result': None,
        'error': None,
        'cancel_requested': False,
    }
    _SCAN_CANCEL_FLAGS[job_id] = threading.Event()
    asyncio.create_task(_run_scan_job(job_id, request, str(source_path)))
    return _scan_job_payload(_SCAN_JOBS[job_id])


async def get_scan_job(request: Request, job_id: str) -> Dict[str, Any]:
    assert_enabled(request)
    return _scan_job_payload(_get_scan_job_or_404(job_id))


async def cancel_scan_job(request: Request, job_id: str) -> Dict[str, Any]:
    assert_enabled(request)
    job = _get_scan_job_or_404(job_id)
    if str(job.get('state') or '') in _SCAN_TERMINAL_STATES:
        return _scan_job_payload(job)
    job['cancel_requested'] = True
    job['updated_at'] = int(time.time())
    cancel_event = _SCAN_CANCEL_FLAGS.get(str(job.get('job_id') or ''))
    if cancel_event is not None:
        cancel_event.set()
    return _scan_job_payload(job)


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


async def stop_model(request: Request, model_id: str) -> Dict[str, Any]:
    assert_enabled(request)
    encoded_model_id = quote(str(model_id or '').strip(), safe='')
    return await _request_json('POST', f'/models/{encoded_model_id}/stop', payload={})


async def get_load_job(request: Request, job_id: str) -> Dict[str, Any]:
    assert_enabled(request)
    encoded_job_id = quote(str(job_id or '').strip(), safe='')
    return await _request_json('GET', f'/model-load-jobs/{encoded_job_id}')


async def cancel_load_job(request: Request, job_id: str) -> Dict[str, Any]:
    assert_enabled(request)
    encoded_job_id = quote(str(job_id or '').strip(), safe='')
    return await _request_json('POST', f'/model-load-jobs/{encoded_job_id}/cancel', payload={})
