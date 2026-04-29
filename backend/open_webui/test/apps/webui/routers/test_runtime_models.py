import sys
import types
import asyncio
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
from starlette.testclient import TestClient


stub_auth = types.ModuleType('open_webui.utils.auth')
stub_auth.get_admin_user = lambda: SimpleNamespace(id='admin-1', role='admin')
stub_auth.get_verified_user = lambda: SimpleNamespace(id='user-1', role='user')
sys.modules['open_webui.utils.auth'] = stub_auth

from open_webui.routers import runtime_models as runtime_models_router
from open_webui.services import runtime_models as runtime_models_service


def _build_app(enable_runtime_models=True):
    app = FastAPI()
    app.state.config = SimpleNamespace(
        ENABLE_AGENT_NAVIGATOR_RUNTIME_MODELS=enable_runtime_models,
        RUNTIME_MODEL_SCAN_FOLDERS=[],
    )
    app.include_router(runtime_models_router.router, prefix='/api/v1/runtime-models')
    return app


def test_browse_folders_route_forwards_query_params(monkeypatch):
    captured = {}

    async def fake_browse(request, path=None, show_hidden=False):
        captured['path'] = path
        captured['show_hidden'] = show_hidden
        return {'entries': [], 'current_path': path, 'parent_path': None}

    monkeypatch.setattr(runtime_models_service, 'browse_folders', fake_browse)

    client = TestClient(_build_app())
    response = client.get('/api/v1/runtime-models/browse-folders', params={'path': '/models', 'show_hidden': 'true'})

    assert response.status_code == 200
    assert response.json()['current_path'] == '/models'
    assert captured == {'path': '/models', 'show_hidden': True}


def test_runtime_models_routes_require_admin():
    app = _build_app()

    def deny_admin():
        raise HTTPException(status_code=403, detail='forbidden')

    app.dependency_overrides[runtime_models_router.get_admin_user] = deny_admin
    client = TestClient(app)

    response = client.get('/api/v1/runtime-models/scan-folders')

    assert response.status_code == 403
    assert response.json() == {'detail': 'forbidden'}


def test_runtime_models_status_reports_disabled_without_backend_probe():
    client = TestClient(_build_app(enable_runtime_models=False))

    response = client.get('/api/v1/runtime-models/status')

    assert response.status_code == 200
    assert response.json() == {
        'enabled': False,
        'available': False,
        'detail': 'runtime-models-disabled',
    }


def test_catalog_returns_empty_when_runtime_models_disabled():
    client = TestClient(_build_app(enable_runtime_models=False))

    response = client.get('/api/v1/runtime-models/catalog')

    assert response.status_code == 200
    assert response.json() == {
        'models': [],
        'active_model_id': None,
        'active_model_source': None,
    }


def test_mutating_route_rejects_when_runtime_models_disabled():
    client = TestClient(_build_app(enable_runtime_models=False))

    response = client.post('/api/v1/runtime-models/scan-folders', json={'path': '/models'})

    assert response.status_code == 404
    assert response.json() == {'detail': {'status': 'runtime-models-disabled'}}


def test_list_scan_folders_normalizes_ums_payload(monkeypatch):
    async def fake_list_scan_folders(request):
        return {'folders': [{'id': 'folder-1', 'path': '/models'}]}

    monkeypatch.setattr(runtime_models_service, 'list_scan_folders', fake_list_scan_folders)

    client = TestClient(_build_app())
    response = client.get('/api/v1/runtime-models/scan-folders')

    assert response.status_code == 200
    assert response.json() == {'folders': [{'id': 'folder-1', 'path': '/models'}]}


def test_preview_route_surfaces_backend_proxy_error(monkeypatch):
    async def fake_preview(request, path):
        raise runtime_models_service.RuntimeModelProxyError(
            422,
            {'status': 'preview_not_registerable', 'reason': 'missing_mmproj_path'},
        )

    monkeypatch.setattr(runtime_models_service, 'preview_path', fake_preview)

    client = TestClient(_build_app())
    response = client.post('/api/v1/runtime-models/preview-path', json={'path': '/models/qwen-vl'})

    assert response.status_code == 422
    assert response.json()['detail']['status'] == 'preview_not_registerable'
    assert response.json()['detail']['reason'] == 'missing_mmproj_path'


def test_scan_job_routes_forward_job_lifecycle(monkeypatch):
    calls = []

    async def fake_create(request, path):
        calls.append(('create', path))
        return {'job_id': 'job-1', 'state': 'queued', 'path': path}

    async def fake_get(request, job_id):
        calls.append(('get', job_id))
        return {'job_id': job_id, 'state': 'running'}

    async def fake_cancel(request, job_id):
        calls.append(('cancel', job_id))
        return {'job_id': job_id, 'state': 'cancelled'}

    monkeypatch.setattr(runtime_models_service, 'create_scan_job', fake_create)
    monkeypatch.setattr(runtime_models_service, 'get_scan_job', fake_get)
    monkeypatch.setattr(runtime_models_service, 'cancel_scan_job', fake_cancel)

    client = TestClient(_build_app())
    create_response = client.post('/api/v1/runtime-models/scan-jobs', json={'path': '/models/qwen'})
    get_response = client.get('/api/v1/runtime-models/scan-jobs/job-1')
    cancel_response = client.post('/api/v1/runtime-models/scan-jobs/job-1/cancel')

    assert create_response.status_code == 200
    assert get_response.json()['state'] == 'running'
    assert cancel_response.json()['state'] == 'cancelled'
    assert calls == [('create', '/models/qwen'), ('get', 'job-1'), ('cancel', 'job-1')]


def test_build_register_payload_maps_gguf_vl_preview_entry():
    payload = runtime_models_service.build_register_payload(
        '/models/qwen-vl',
        {
            'candidate_id': 'qwen-vl-8b-q4',
            'display_name': 'Qwen3 VL 8B',
            'kind': 'vision',
            'runtime_type': 'gguf-vl',
            'status': 'ready',
            'status_reason': 'configured',
            'user_selectable': True,
            'resolved_source': {
                'gguf_path': '/models/qwen-vl/model.gguf',
                'mmproj_path': '/models/qwen-vl/mmproj.gguf',
            },
        },
    )

    assert payload['model_id'] == 'qwen-vl-8b-q4'
    assert payload['type'] == 'gguf-vl'
    assert payload['path'] == '/models/qwen-vl/model.gguf'
    assert payload['mmproj'] == '/models/qwen-vl/mmproj.gguf'
    assert payload['source_path'] == '/models/qwen-vl'


def test_build_register_payload_maps_split_gguf_preview_entry():
    payload = runtime_models_service.build_register_payload(
        '/models/qwen-32b',
        {
            'candidate_id': 'qwen-32b-llm',
            'display_name': 'Qwen2.5 32B',
            'kind': 'llm',
            'runtime_type': 'gguf',
            'status': 'ready',
            'status_reason': 'configured',
            'user_selectable': True,
            'resolved_source': {
                'primary_path': '/models/qwen-32b/qwen-00001-of-00005.gguf',
                'shards': [
                    '/models/qwen-32b/qwen-00001-of-00005.gguf',
                    '/models/qwen-32b/qwen-00002-of-00005.gguf',
                ],
            },
        },
    )

    assert payload['type'] == 'gguf'
    assert payload['path'] == '/models/qwen-32b/qwen-00001-of-00005.gguf'
    assert payload['shards'] == [
        '/models/qwen-32b/qwen-00001-of-00005.gguf',
        '/models/qwen-32b/qwen-00002-of-00005.gguf',
    ]


def test_list_scan_folders_service_reads_openwebui_storage(tmp_path):
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                config=SimpleNamespace(
                    ENABLE_AGENT_NAVIGATOR_RUNTIME_MODELS=True,
                    RUNTIME_MODEL_SCAN_FOLDERS=[{'path': str(tmp_path)}],
                )
            )
        )
    )

    result = asyncio.run(runtime_models_service.list_scan_folders(request))

    assert result['folders'][0]['path'] == str(tmp_path.resolve())
    assert result['folders'][0]['id']


def test_browse_folders_service_lists_local_model_hints(tmp_path, monkeypatch):
    monkeypatch.setenv('OPENWEBUI_RUNTIME_MODEL_BROWSE_ALLOWLIST_ROOTS', str(tmp_path))
    model_dir = tmp_path / 'qwen-folder'
    model_dir.mkdir()
    (model_dir / 'qwen.gguf').write_text('stub', encoding='utf-8')
    plain_dir = tmp_path / 'plain-folder'
    plain_dir.mkdir()
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                config=SimpleNamespace(ENABLE_AGENT_NAVIGATOR_RUNTIME_MODELS=True, RUNTIME_MODEL_SCAN_FOLDERS=[])
            )
        )
    )

    result = asyncio.run(runtime_models_service.browse_folders(request, str(tmp_path)))

    entries = {entry['name']: entry for entry in result['entries']}
    assert entries['qwen-folder']['looks_like_model_dir'] is True
    assert entries['qwen-folder']['folder_tags'] == ['GGUF']
    assert entries['plain-folder']['looks_like_model_dir'] is False


def test_preview_path_service_detects_ready_gguf_candidate(tmp_path, monkeypatch):
    monkeypatch.setenv('OPENWEBUI_RUNTIME_MODEL_BROWSE_ALLOWLIST_ROOTS', str(tmp_path))
    model_dir = tmp_path / 'qwen-14b'
    model_dir.mkdir()
    model_path = model_dir / 'qwen-14b-q4.gguf'
    model_path.write_text('stub', encoding='utf-8')
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                config=SimpleNamespace(ENABLE_AGENT_NAVIGATOR_RUNTIME_MODELS=True, RUNTIME_MODEL_SCAN_FOLDERS=[])
            )
        )
    )

    result = asyncio.run(runtime_models_service.preview_path(request, str(model_dir)))

    assert result['source_path'] == str(model_dir.resolve())
    assert result['entries'][0]['runtime_type'] == 'gguf'
    assert result['entries'][0]['status'] == 'ready'
    assert result['entries'][0]['resolved_source']['gguf_path'] == str(model_path.resolve())


def test_cancel_scan_job_service_sets_cancel_flag():
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                config=SimpleNamespace(ENABLE_AGENT_NAVIGATOR_RUNTIME_MODELS=True, RUNTIME_MODEL_SCAN_FOLDERS=[])
            )
        )
    )
    event = runtime_models_service.threading.Event()
    runtime_models_service._SCAN_JOBS['job-cancel'] = {
        'job_id': 'job-cancel',
        'state': 'running',
        'path': '/models',
        'progress': {},
        'result': None,
        'error': None,
        'cancel_requested': False,
    }
    runtime_models_service._SCAN_CANCEL_FLAGS['job-cancel'] = event

    result = asyncio.run(runtime_models_service.cancel_scan_job(request, 'job-cancel'))

    assert result['state'] == 'running'
    assert result['cancel_requested'] is True
    assert event.is_set()
    runtime_models_service._SCAN_JOBS.pop('job-cancel', None)
    runtime_models_service._SCAN_CANCEL_FLAGS.pop('job-cancel', None)


def test_list_catalog_service_builds_runtime_badges(monkeypatch):
    async def fake_request_json(method, endpoint_path, **kwargs):
        assert method == 'GET'
        assert endpoint_path == '/models'
        return {
            'models': [
                {
                    'model_id': 'qwen-vl-8b',
                    'display_name': 'Qwen VL',
                    'runtime_type': 'gguf-vl',
                    'kind': 'vision',
                    'status': 'ready',
                    'catalog_origin': 'static',
                    'user_selectable': True,
                    'resolved_source': {'gguf_path': '/models/vl.gguf', 'mmproj_path': '/models/mmproj.gguf'},
                },
                {
                    'model_id': 'qwen-32b-llm',
                    'display_name': 'Qwen 32B',
                    'runtime_type': 'gguf',
                    'kind': 'llm',
                    'status': 'ready',
                    'catalog_origin': 'dynamic',
                    'user_selectable': True,
                    'resolved_source': {'shards': ['/models/a.gguf', '/models/b.gguf']},
                },
            ],
            'active_model_id': 'qwen-vl-8b',
            'active_model_source': 'runtime_state',
        }

    monkeypatch.setattr(runtime_models_service, '_request_json', fake_request_json)

    payload = runtime_models_service.list_catalog(SimpleNamespace())
    result = asyncio.run(payload)

    assert result['active_model_id'] == 'qwen-vl-8b'
    assert result['models'][0]['runtime_badges'] == ['GGUF', 'Vision']
    assert result['models'][1]['runtime_badges'] == ['GGUF', 'Split']


def test_resolve_ums_base_url_uses_rag_openai_url_without_v1(monkeypatch):
    monkeypatch.delenv('UMS_URL', raising=False)
    monkeypatch.delenv('AGENT_API_UMS_URL', raising=False)
    monkeypatch.setenv('RAG_OPENAI_API_BASE_URL', 'http://host.docker.internal:8090/v1')

    assert runtime_models_service._resolve_ums_base_url() == 'http://host.docker.internal:8090'


def test_catalog_route_is_available_for_verified_user(monkeypatch):
    async def fake_list_catalog(request):
        return {
            'models': [
                {
                    'model_id': 'qwen-14b-llm',
                    'display_name': 'Qwen2.5 14B',
                    'runtime_type': 'gguf',
                    'kind': 'llm',
                    'status': 'ready',
                    'catalog_origin': 'static',
                    'user_selectable': True,
                    'runtime_badges': ['GGUF'],
                }
            ],
            'active_model_id': 'qwen-14b-llm',
            'active_model_source': 'runtime_state',
        }

    monkeypatch.setattr(runtime_models_service, 'list_catalog', fake_list_catalog)

    client = TestClient(_build_app())
    response = client.get('/api/v1/runtime-models/catalog')

    assert response.status_code == 200
    payload = response.json()
    assert payload['active_model_id'] == 'qwen-14b-llm'
    assert payload['models'][0]['runtime_badges'] == ['GGUF']


def test_unregister_route_forwards_model_id(monkeypatch):
    captured = {}

    async def fake_unregister(request, model_id):
        captured['model_id'] = model_id
        return {'status': 'success', 'action': 'unregister', 'model_id': model_id}

    monkeypatch.setattr(runtime_models_service, 'unregister_model', fake_unregister)

    client = TestClient(_build_app())
    response = client.delete('/api/v1/runtime-models/qwen-32b-llm/registration')

    assert response.status_code == 200
    assert response.json() == {
        'status': 'success',
        'action': 'unregister',
        'model_id': 'qwen-32b-llm',
    }
    assert captured == {'model_id': 'qwen-32b-llm'}


def test_load_route_forwards_model_id_and_device_mode(monkeypatch):
    captured = {}

    async def fake_load(request, model_id, device_mode=None):
        captured['model_id'] = model_id
        captured['device_mode'] = device_mode
        return {
            'status': 'success',
            'action': 'load',
            'job_id': 'job-1',
            'job': {'job_id': 'job-1', 'state': 'queued'},
        }

    monkeypatch.setattr(runtime_models_service, 'load_model', fake_load)

    client = TestClient(_build_app())
    response = client.post('/api/v1/runtime-models/qwen-14b-llm/load', json={'device_mode': 'hybrid'})

    assert response.status_code == 200
    assert response.json()['job_id'] == 'job-1'
    assert captured == {'model_id': 'qwen-14b-llm', 'device_mode': 'hybrid'}


def test_stop_runtime_model_route_forwards_model_id(monkeypatch):
    captured = {}

    async def fake_stop(request, model_id):
        captured['model_id'] = model_id
        return {'status': 'success', 'action': 'stop', 'model': {'id': model_id}}

    monkeypatch.setattr(runtime_models_service, 'stop_model', fake_stop)

    client = TestClient(_build_app())
    response = client.post('/api/v1/runtime-models/qwen-14b-llm/stop')

    assert response.status_code == 200
    assert response.json()['action'] == 'stop'
    assert captured == {'model_id': 'qwen-14b-llm'}


def test_load_job_status_route_is_available_for_verified_user(monkeypatch):
    async def fake_get_load_job(request, job_id):
        return {'job_id': job_id, 'state': 'loading', 'percent': 42.5}

    monkeypatch.setattr(runtime_models_service, 'get_load_job', fake_get_load_job)

    client = TestClient(_build_app())
    response = client.get('/api/v1/runtime-models/load-jobs/job-1')

    assert response.status_code == 200
    assert response.json() == {'job_id': 'job-1', 'state': 'loading', 'percent': 42.5}


def test_cancel_load_job_route_forwards_job_id(monkeypatch):
    captured = {}

    async def fake_cancel_load_job(request, job_id):
        captured['job_id'] = job_id
        return {'status': 'success', 'action': 'cancel', 'job': {'job_id': job_id, 'state': 'cancelled'}}

    monkeypatch.setattr(runtime_models_service, 'cancel_load_job', fake_cancel_load_job)

    client = TestClient(_build_app())
    response = client.post('/api/v1/runtime-models/load-jobs/job-1/cancel')

    assert response.status_code == 200
    assert response.json()['job']['state'] == 'cancelled'
    assert captured == {'job_id': 'job-1'}


def test_load_job_service_forwards_to_ums(monkeypatch):
    calls = []

    async def fake_request_json(method, endpoint_path, **kwargs):
        calls.append({'method': method, 'endpoint_path': endpoint_path, **kwargs})
        return {'job_id': 'job-1', 'state': 'loading'}

    monkeypatch.setattr(runtime_models_service, '_request_json', fake_request_json)

    result = asyncio.run(runtime_models_service.get_load_job(SimpleNamespace(), 'job-1'))

    assert result == {'job_id': 'job-1', 'state': 'loading'}
    assert calls == [{'method': 'GET', 'endpoint_path': '/model-load-jobs/job-1'}]


def test_stop_model_service_forwards_to_ums(monkeypatch):
    calls = []

    async def fake_request_json(method, endpoint_path, **kwargs):
        calls.append({'method': method, 'endpoint_path': endpoint_path, **kwargs})
        return {'status': 'success', 'action': 'stop'}

    monkeypatch.setattr(runtime_models_service, '_request_json', fake_request_json)

    result = asyncio.run(runtime_models_service.stop_model(SimpleNamespace(), 'qwen-14b-llm'))

    assert result == {'status': 'success', 'action': 'stop'}
    assert calls == [{'method': 'POST', 'endpoint_path': '/models/qwen-14b-llm/stop', 'payload': {}}]
