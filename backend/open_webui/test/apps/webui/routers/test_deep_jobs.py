import ast
import html
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from starlette.testclient import TestClient


stub_auth = types.ModuleType('open_webui.utils.auth')
stub_auth.get_verified_user = lambda: SimpleNamespace(id='user-1', role='user')
sys.modules['open_webui.utils.auth'] = stub_auth

from open_webui.routers.deep_jobs import router
from open_webui.services import deep_jobs as deep_jobs_service
from open_webui.utils.misc import convert_output_to_messages


def _load_middleware_function_from_source(function_name: str):
    source_path = Path(__file__).resolve().parents[4] / 'utils' / 'middleware.py'
    module_ast = ast.parse(source_path.read_text(encoding='utf-8'))
    serialize_node = next(
        node for node in module_ast.body if isinstance(node, ast.FunctionDef) and node.name == function_name
    )
    extracted_module = ast.Module(body=[serialize_node], type_ignores=[])
    ast.fix_missing_locations(extracted_module)
    namespace = {
        'html': html,
        'json': json,
        'split_content_and_whitespace': lambda content: (content, ''),
        'is_opening_code_block': lambda content: False,
    }
    exec(compile(extracted_module, str(source_path), 'exec'), namespace)
    return namespace[function_name]


def _load_serialize_output_from_source():
    return _load_middleware_function_from_source('serialize_output')


def _build_app():
    app = FastAPI()
    app.state.config = SimpleNamespace(TOOL_SERVER_CONNECTIONS=[])
    app.include_router(router, prefix='/api/v1')
    return app


def test_normalize_tool_job_snapshot_maps_status_payload():
    snapshot = deep_jobs_service.normalize_tool_job_snapshot(
        {
            'job_id': 'job-1',
            'status': 'cancelling',
            'current_stage': 'indexing',
            'submitted_at': '2026-04-16T12:00:00Z',
            'status_text': 'Индексирование 2/4',
            'progress': {'fraction': 0.5, 'phase': 'indexing'},
            'status_history': [
                {
                    'key': 'indexing',
                    'title': 'Индексация',
                    'content': 'Индексирование 2/4',
                }
            ],
            'result_message_id': 'msg-9',
        },
        chat_id='chat-1',
    )

    assert snapshot['job_id'] == 'job-1'
    assert snapshot['chat_id'] == 'chat-1'
    assert snapshot['state'] == 'running'
    assert snapshot['cancel_requested'] is True
    assert snapshot['phase'] == 'indexing'
    assert snapshot['summary'] == 'Индексирование 2/4'
    assert snapshot['progress'] == {'current': 50, 'total': 100, 'unit': 'percent'}
    assert snapshot['steps'][0]['phase'] == 'indexing'
    assert snapshot['result_message_id'] == 'msg-9'


def test_resolve_tool_server_connection_prefers_bootstrap_connection():
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                config=SimpleNamespace(
                    TOOL_SERVER_CONNECTIONS=[
                        {
                            'url': 'http://127.0.0.1:9999',
                            'path': '/openapi.json',
                            'type': 'openapi',
                        },
                        {
                            'url': 'http://127.0.0.1:8000',
                            'path': '/tool-server/openapi.json',
                            'type': 'openapi',
                            'config': {'bootstrap_id': deep_jobs_service.BOOTSTRAP_CONNECTION_ID},
                        },
                    ]
                )
            )
        )
    )

    connection = deep_jobs_service.resolve_tool_server_connection(request)

    assert connection['url'] == 'http://127.0.0.1:8000'
    assert connection['path'] == '/tool-server/openapi.json'


def test_resolve_tool_server_connection_uses_local_fallback_when_config_missing(monkeypatch):
    monkeypatch.setenv('LLM_TOOLS_PLATFORM_TOOL_SERVER_BASE_URL', 'http://127.0.0.1:8010')
    monkeypatch.setenv('OPENAPI_TOOL_SERVER_TOKEN', 'fallback-token')

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                config=SimpleNamespace(
                    TOOL_SERVER_CONNECTIONS=[]
                )
            )
        )
    )

    connection = deep_jobs_service.resolve_tool_server_connection(request)

    assert connection['url'] == 'http://127.0.0.1:8010'
    assert connection['path'] == '/tool-server/openapi.json'
    assert connection['key'] == 'fallback-token'
    assert connection['config']['bootstrap_id'] == deep_jobs_service.BOOTSTRAP_CONNECTION_ID


def test_active_deep_job_route_returns_normalized_payload(monkeypatch):
    app = _build_app()

    async def fake_get_active(request, chat_id):
        return {
            'job_id': 'job-1',
            'chat_id': chat_id,
            'state': 'running',
            'phase': 'indexing',
            'summary': 'Идёт индексирование',
            'progress': None,
            'steps': [],
            'cancel_requested': False,
            'result_message_id': None,
            'error': None,
            'updated_at': '2026-04-16T12:00:00Z',
        }

    monkeypatch.setattr(deep_jobs_service, 'get_active_deep_job_snapshot', fake_get_active)

    client = TestClient(app)
    response = client.get('/api/v1/chats/chat-1/deep-jobs/active')

    assert response.status_code == 200
    assert response.json() == {
        'job': {
            'job_id': 'job-1',
            'chat_id': 'chat-1',
            'state': 'running',
            'phase': 'indexing',
            'summary': 'Идёт индексирование',
            'progress': None,
            'steps': [],
            'cancel_requested': False,
            'result_message_id': None,
            'error': None,
            'updated_at': '2026-04-16T12:00:00Z',
        }
    }


def test_cancel_deep_job_route_maps_proxy_error(monkeypatch):
    app = _build_app()

    async def fake_cancel(request, job_id):
        raise deep_jobs_service.DeepJobProxyError(404, f'unknown-tool-job:{job_id}')

    monkeypatch.setattr(deep_jobs_service, 'cancel_deep_job_snapshot', fake_cancel)

    client = TestClient(app)
    response = client.post('/api/v1/deep-jobs/job-missing/cancel')

    assert response.status_code == 404
    assert response.json()['detail'] == 'unknown-tool-job:job-missing'


def test_get_deep_job_result_route_returns_proxy_payload(monkeypatch):
    app = _build_app()

    async def fake_get_result(request, job_id):
        return {
            'status': 'completed',
            'tool_name': 'analyze_document_deep',
            'assistant_message': 'Финальный результат готов.',
            'structured_result': {'job_id': job_id},
            'sources': [{'title': 'Документ'}],
            'artifacts': [],
            'embeds': [],
            'available_actions': [],
            'execution_metadata': {'latency_ms': 1200},
        }

    monkeypatch.setattr(deep_jobs_service, 'get_deep_job_result_payload', fake_get_result)

    client = TestClient(app)
    response = client.get('/api/v1/deep-jobs/job-1/result')

    assert response.status_code == 200
    assert response.json() == {
        'status': 'completed',
        'tool_name': 'analyze_document_deep',
        'assistant_message': 'Финальный результат готов.',
        'structured_result': {'job_id': 'job-1'},
        'sources': [{'title': 'Документ'}],
        'artifacts': [],
        'embeds': [],
        'available_actions': [],
        'execution_metadata': {'latency_ms': 1200},
    }


def test_download_deep_job_artifact_route_streams_proxy_file(monkeypatch):
    app = _build_app()

    async def fake_download(request, job_id, artifact_id):
        assert job_id == 'job-1'
        assert artifact_id == 'Report_Test_123.pdf'
        return {
            'content': b'%PDF-1.4 test report',
            'content_type': 'application/pdf',
            'content_disposition': 'attachment; filename="Report_Test_123.pdf"',
            'filename': 'Report_Test_123.pdf',
        }

    monkeypatch.setattr(deep_jobs_service, 'download_deep_job_artifact', fake_download)

    client = TestClient(app)
    response = client.get('/api/v1/deep-jobs/job-1/artifacts/Report_Test_123.pdf/download')

    assert response.status_code == 200
    assert response.content == b'%PDF-1.4 test report'
    assert response.headers['content-type'] == 'application/pdf'
    assert response.headers['content-disposition'] == 'attachment; filename="Report_Test_123.pdf"'


def test_record_deep_job_delivery_route_returns_normalized_snapshot(monkeypatch):
    app = _build_app()

    async def fake_record_delivery(request, job_id, result_message_id, terminal_emitted_at=None):
        assert job_id == 'job-1'
        assert result_message_id == 'msg-9'
        assert terminal_emitted_at == '2026-04-16T12:05:00Z'
        return {
            'job_id': 'job-1',
            'chat_id': 'chat-1',
            'state': 'completed',
            'phase': 'synthesis',
            'summary': 'Ответ сохранён.',
            'progress': None,
            'steps': [],
            'cancel_requested': False,
            'result_message_id': 'msg-9',
            'error': None,
            'updated_at': '2026-04-16T12:05:00Z',
        }

    monkeypatch.setattr(deep_jobs_service, 'record_deep_job_delivery', fake_record_delivery)

    client = TestClient(app)
    response = client.post(
        '/api/v1/deep-jobs/job-1/delivery',
        json={
            'result_message_id': 'msg-9',
            'terminal_emitted_at': '2026-04-16T12:05:00Z',
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        'job_id': 'job-1',
        'chat_id': 'chat-1',
        'state': 'completed',
        'phase': 'synthesis',
        'summary': 'Ответ сохранён.',
        'progress': None,
        'steps': [],
        'cancel_requested': False,
        'result_message_id': 'msg-9',
        'error': None,
        'updated_at': '2026-04-16T12:05:00Z',
    }


def test_serialize_output_renders_openwebui_deep_job_anchor():
    serialize_output = _load_serialize_output_from_source()

    rendered = serialize_output(
        [
            {
                'type': 'open_webui:deep_job',
                'job_id': 'job-123',
                'title': 'Deep job',
                'summary': 'Идёт индексирование',
                'state': 'running',
                'result_message_id': 'msg-result-9',
            }
        ]
    )

    assert 'type="deep_job"' in rendered
    assert 'job_id="job-123"' in rendered
    assert 'state="running"' in rendered
    assert 'done="false"' in rendered
    assert 'title="Deep job"' in rendered
    assert 'result_message_id="msg-result-9"' in rendered
    assert '<summary>Идёт индексирование</summary>' in rendered


def test_build_deep_job_output_item_maps_accepted_tool_result():
    build_deep_job_output_item = _load_middleware_function_from_source('build_deep_job_output_item')

    output_item = build_deep_job_output_item(
        tool_function_name='analyze_document_deep',
        tool_call_id='call-7',
        tool_result='''{
  "status": "accepted",
  "tool_name": "analyze_document_deep",
  "job_id": "job-123",
  "status_url": "/tool-server/tool-jobs/job-123",
  "job_status": "queued",
  "status_text": "Задача принята",
  "result_preview": "Идёт подготовка ответа"
}''',
    )

    assert output_item == {
        'type': 'open_webui:deep_job',
        'tool_call_id': 'call-7',
        'job_id': 'job-123',
        'title': 'Deep job',
        'summary': 'Задача принята',
        'state': 'queued',
        'result_message_id': None,
    }


def test_build_deep_job_output_item_maps_plain_text_accepted_tool_result():
    build_deep_job_output_item = _load_middleware_function_from_source('build_deep_job_output_item')

    output_item = build_deep_job_output_item(
        tool_function_name='analyze_equipment_deep',
        tool_call_id='call-9',
        tool_result=(
            'Глубокий анализ оборудования принят как deep-job.\n'
            'job_id: job-plain-9\n'
            'status_url: /tool-server/tool-jobs/job-plain-9'
        ),
    )

    assert output_item == {
        'type': 'open_webui:deep_job',
        'tool_call_id': 'call-9',
        'job_id': 'job-plain-9',
        'title': 'Deep job',
        'summary': 'Глубокий анализ оборудования принят как deep-job.',
        'state': 'queued',
        'result_message_id': None,
    }


def test_serialize_output_hides_generic_tool_details_for_deep_job_calls():
    serialize_output = _load_serialize_output_from_source()

    rendered = serialize_output(
        [
            {
                'type': 'function_call',
                'call_id': 'call-7',
                'name': 'analyze_document_deep',
                'arguments': '{"document_id": "doc-1"}',
                'status': 'completed',
            },
            {
                'type': 'function_call_output',
                'call_id': 'call-7',
                'output': [{'type': 'input_text', 'text': '{"status": "accepted", "job_id": "job-123"}'}],
                'status': 'completed',
            },
            {
                'type': 'open_webui:deep_job',
                'tool_call_id': 'call-7',
                'job_id': 'job-123',
                'title': 'Deep job',
                'summary': 'Задача принята',
                'state': 'queued',
            },
        ]
    )

    assert 'type="deep_job"' in rendered
    assert 'job_id="job-123"' in rendered
    assert 'type="tool_calls"' not in rendered


def test_convert_output_to_messages_skips_openwebui_deep_job_extension_item():
    messages = convert_output_to_messages(
        [
            {
                'type': 'message',
                'content': [{'type': 'output_text', 'text': 'Финальный ответ'}],
            },
            {
                'type': 'open_webui:deep_job',
                'job_id': 'job-123',
                'title': 'Deep job',
                'summary': 'Идёт индексирование',
                'state': 'running',
            },
        ]
    )

    assert messages == [{'role': 'assistant', 'content': 'Финальный ответ'}]
