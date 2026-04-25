import ast
import asyncio
import html
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi import HTTPException, status
from starlette.testclient import TestClient


stub_auth = types.ModuleType('open_webui.utils.auth')
stub_auth.get_verified_user = lambda: SimpleNamespace(id='user-1', role='user')
sys.modules['open_webui.utils.auth'] = stub_auth

from open_webui.routers.deep_jobs import router
from open_webui.services import deep_jobs as deep_jobs_service
from open_webui.utils.long_running_tools import (
    annotate_body_with_session_rag_handoff,
    detect_unconfirmed_long_running_output,
    should_enable_session_rag_handoff,
)
from open_webui.utils.misc import convert_output_to_messages


def _load_middleware_function_from_source(function_name: str):
    source_path = Path(__file__).resolve().parents[4] / 'utils' / 'middleware.py'
    module_ast = ast.parse(source_path.read_text(encoding='utf-8'))
    serialize_node = next(
        node
        for node in module_ast.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name
    )
    extracted_module = ast.Module(body=[serialize_node], type_ignores=[])
    ast.fix_missing_locations(extracted_module)
    namespace = {
        'html': html,
        'json': json,
        '_OPENAI_TOOL_DISPLAY_NAMES': {},
        'split_content_and_whitespace': lambda content: (content, ''),
        'is_opening_code_block': lambda content: False,
        'detect_unconfirmed_long_running_output': detect_unconfirmed_long_running_output,
        'should_enable_session_rag_handoff': should_enable_session_rag_handoff,
        'annotate_body_with_session_rag_handoff': annotate_body_with_session_rag_handoff,
        'Request': Any,
        'UserModel': Any,
    }
    exec(compile(extracted_module, str(source_path), 'exec'), namespace)
    return namespace[function_name]


def _load_files_router_function_from_source(function_name: str):
    source_path = Path(__file__).resolve().parents[4] / 'routers' / 'files.py'
    module_ast = ast.parse(source_path.read_text(encoding='utf-8'))
    router_nodes = [
        node
        for node in module_ast.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name
    ]
    router_node = router_nodes[-1]
    extracted_module = ast.Module(body=[router_node], type_ignores=[])
    ast.fix_missing_locations(extracted_module)
    namespace = {
        'router': SimpleNamespace(get=lambda *_args, **_kwargs: (lambda func: func)),
        'quote': lambda value: value,
        'Path': Path,
        'StreamingResponse': StreamingResponse,
        'FileResponse': FileResponse,
        'HTTPException': HTTPException,
        'status': status,
        'ERROR_MESSAGES': SimpleNamespace(NOT_FOUND='not_found'),
        'Files': SimpleNamespace(get_file_by_id=lambda *_args, **_kwargs: None),
        'Storage': SimpleNamespace(get_file=lambda path: path),
        'has_access_to_file': lambda *_args, **_kwargs: False,
        'Depends': lambda dependency=None: None,
        'Query': lambda default=None, **_kwargs: default,
        'get_verified_user': lambda: None,
        'get_async_session': lambda: None,
        'AsyncSession': Any,
        'get_session': lambda: None,
        'Session': Any,
    }
    exec(compile(extracted_module, str(source_path), 'exec'), namespace)
    return namespace[function_name], namespace


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
            'current_stage': 'stage:indexing',
            'submitted_at': '2026-04-16T12:00:00Z',
            'status_text': 'Индексирование 2/4',
            'progress': {'fraction': 0.5, 'phase': 'indexing'},
            'status_history': [
                {
                    'key': 'stage:indexing',
                    'title': 'Индексация',
                    'content': 'Индексирование 2/4',
                },
                {
                    'key': 'stage:analysis',
                    'title': 'Анализ',
                    'content': 'Собираем итоговый вывод.',
                }
            ],
            'result_message_id': 'msg-9',
        },
        chat_id='chat-1',
    )

    assert snapshot['job_id'] == 'job-1'
    assert snapshot['chat_id'] == 'chat-1'
    assert snapshot['state'] == 'running'
    assert snapshot['tool_label'] is None
    assert snapshot['cancel_requested'] is True
    assert snapshot['phase'] == 'Индексация'
    assert snapshot['summary'] == 'Индексирование 2/4'
    assert snapshot['progress'] == {'current': 50, 'total': 100, 'unit': 'percent'}
    assert snapshot['steps'][0]['phase'] == 'Индексация'
    assert snapshot['steps'][0]['text'] == 'Индексирование 2/4'
    assert snapshot['steps'][1]['phase'] == 'Анализ'
    assert snapshot['steps'][1]['text'] == 'Собираем итоговый вывод.'
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
            'tool_label': 'Глубокий анализ оборудования',
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
            'tool_label': 'Глубокий анализ оборудования',
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
                'title': 'Long-running tool',
                'tool_label': 'Глубокий анализ документа',
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
    assert 'title="Long-running tool"' in rendered
    assert 'tool_label="Глубокий анализ документа"' in rendered
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
  "tool_label": "Глубокий анализ документа",
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
        'title': 'Long-running tool',
        'tool_label': 'Глубокий анализ документа',
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
            'Принят в работу: Глубокий анализ оборудования.\n'
            'job_id: job-plain-9\n'
            'status_url: /tool-server/tool-jobs/job-plain-9'
        ),
    )

    assert output_item == {
        'type': 'open_webui:deep_job',
        'tool_call_id': 'call-9',
        'job_id': 'job-plain-9',
        'title': 'Long-running tool',
        'tool_label': None,
        'summary': 'Принят в работу: Глубокий анализ оборудования.',
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
                'output': [
                    {
                        'type': 'input_text',
                        'text': '{"status": "accepted", "job_id": "job-123", "status_url": "/tool-server/tool-jobs/job-123"}',
                    }
                ],
                'status': 'completed',
            },
            {
                'type': 'open_webui:deep_job',
                'tool_call_id': 'call-7',
                'job_id': 'job-123',
                'title': 'Long-running tool',
                'tool_label': 'Глубокий анализ документа',
                'summary': 'Задача принята',
                'state': 'queued',
            },
        ]
    )

    assert 'type="deep_job"' in rendered
    assert 'job_id="job-123"' in rendered
    assert 'type="tool_calls"' not in rendered


def test_serialize_output_rewrites_unconfirmed_long_running_tool_result():
    serialize_output = _load_serialize_output_from_source()

    rendered = serialize_output(
        [
            {
                'type': 'function_call',
                'call_id': 'call-long-1',
                'name': 'analyze_document_deep',
                'arguments': '{}',
            },
            {
                'type': 'function_call_output',
                'call_id': 'call-long-1',
                'output': '',
            },
        ]
    )

    assert 'Не удалось запустить инструмент глубокого анализа документа' in rendered


def test_get_file_content_by_id_handles_none_inline_content_without_encode_error():
    get_file_content_by_id, namespace = _load_files_router_function_from_source('get_file_content_by_id')

    async def _get_file_by_id(*_args, **_kwargs):
        return SimpleNamespace(
            user_id='user-1',
            path=None,
            meta={'name': 'contract.pdf'},
            filename='contract.pdf',
            data={'content': None},
        )

    namespace['Files'] = SimpleNamespace(
        get_file_by_id=_get_file_by_id,
    )

    async def _invoke():
        response = await get_file_content_by_id(
            'file-1',
            user=SimpleNamespace(id='user-1', role='user'),
            db=None,
        )
        payload = b''
        async for chunk in response.body_iterator:
            payload += chunk
        return response, payload

    response, payload = asyncio.run(_invoke())

    assert isinstance(response, StreamingResponse)
    assert response.media_type == 'text/plain'
    assert payload == b''


def test_chat_completion_files_handler_skips_local_rag_for_session_handoff(monkeypatch):
    monkeypatch.setenv('OPENWEBUI_SESSION_RAG_HANDOFF', 'preferred')
    chat_completion_files_handler = _load_middleware_function_from_source('chat_completion_files_handler')
    body = {
        'model': 'llm-tools-platform',
        'metadata': {
            'chat_id': 'chat-1',
            'message_id': 'msg-1',
            'files': [
                {
                    'id': 'file-1',
                    'name': 'contract.pdf',
                    'type': 'text',
                    'content': 'Штраф 10 процентов',
                }
            ],
        },
    }

    patched_body, flags = asyncio.run(
        chat_completion_files_handler(None, body, {'__event_emitter__': None}, None)
    )

    assert flags == {'sources': []}
    assert patched_body['metadata']['llm_tools_platform_session_rag_handoff']['enabled'] is True


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
                'title': 'Long-running tool',
                'tool_label': 'Глубокий анализ документа',
                'summary': 'Идёт индексирование',
                'state': 'running',
            },
        ]
    )

    assert messages == [{'role': 'assistant', 'content': 'Финальный ответ'}]
