import asyncio

import pytest

from open_webui.utils.long_running_tools import (
    LONG_RUNNING_TOOL_LAUNCH_ERROR,
    annotate_body_with_session_rag_handoff,
    detect_unconfirmed_long_running_launch,
    detect_unconfirmed_long_running_output,
    prepare_openai_form_data_for_session_rag_handoff,
    run_openai_with_session_rag_handoff,
    should_enable_session_rag_handoff,
)


@pytest.mark.parametrize('tool_name', ['analyze_equipment_deep', 'analyze_document_deep'])
def test_detect_unconfirmed_long_running_launch_reports_empty_tool_result(tool_name: str):
    launch_state = detect_unconfirmed_long_running_launch(
        [
            {
                'role': 'assistant',
                'content': '',
                'tool_calls': [
                    {
                        'id': 'call-long-1',
                        'function': {'name': tool_name, 'arguments': '{}'},
                    }
                ],
            },
            {
                'role': 'tool',
                'tool_call_id': 'call-long-1',
                'content': '',
            },
        ]
    )

    assert launch_state is not None
    assert launch_state['call_id'] == 'call-long-1'
    assert launch_state['message'] == LONG_RUNNING_TOOL_LAUNCH_ERROR


@pytest.mark.parametrize('tool_name', ['analyze_equipment_deep', 'analyze_document_deep'])
def test_detect_unconfirmed_long_running_output_reports_empty_function_output(tool_name: str):
    launch_state = detect_unconfirmed_long_running_output(
        [
            {
                'type': 'function_call',
                'call_id': 'call-long-2',
                'name': tool_name,
                'arguments': '{}',
            },
            {
                'type': 'function_call_output',
                'call_id': 'call-long-2',
                'output': '',
            },
        ]
    )

    assert launch_state is not None
    assert launch_state['call_id'] == 'call-long-2'
    assert launch_state['message'] == LONG_RUNNING_TOOL_LAUNCH_ERROR


def test_session_rag_handoff_annotation_and_prepare(monkeypatch):
    monkeypatch.setenv('OPENWEBUI_SESSION_RAG_HANDOFF', 'preferred')
    body = {
        'model': 'raw.qwen-14b-llm',
        'metadata': {'chat_id': 'chat-1', 'message_id': 'msg-1'},
        'files': [{'id': 'file-1', 'name': 'contract.txt', 'type': 'text', 'content': 'Штраф 17 процентов'}],
    }

    assert should_enable_session_rag_handoff(body) is True

    annotated = annotate_body_with_session_rag_handoff(body)
    prepared = prepare_openai_form_data_for_session_rag_handoff(body)

    assert annotated['metadata']['llm_tools_platform_session_rag_handoff']['chat_id'] == 'chat-1'
    assert prepared['model'] == 'llm-tools-platform'
    assert prepared['thread_id'] == 'chat-1'
    assert prepared['session_id'] == 'chat-1'
    assert prepared['files'][0]['id'] == 'file-1'
    assert prepared['openwebui_session_rag_handoff']['original_model'] == 'raw.qwen-14b-llm'


def test_run_openai_with_session_rag_handoff_preferred_mode_falls_back(monkeypatch):
    monkeypatch.setenv('OPENWEBUI_SESSION_RAG_HANDOFF', 'preferred')
    models: list[str] = []

    async def invoke(payload):
        models.append(str(payload.get('model')))
        if payload.get('model') == 'llm-tools-platform':
            raise RuntimeError('wrapper unavailable')
        return {'ok': True, 'model': payload.get('model')}

    result = asyncio.run(
        run_openai_with_session_rag_handoff(
            {
                'model': 'raw.qwen-14b-llm',
                'metadata': {'chat_id': 'chat-3', 'message_id': 'msg-3'},
                'files': [{'id': 'file-3', 'name': 'contract.txt', 'type': 'text', 'content': 'Штраф 17 процентов'}],
            },
            invoke,
        )
    )

    assert result == {'ok': True, 'model': 'raw.qwen-14b-llm'}
    assert models == ['llm-tools-platform', 'raw.qwen-14b-llm']


def test_run_openai_with_session_rag_handoff_required_mode_does_not_fallback(monkeypatch):
    monkeypatch.setenv('OPENWEBUI_SESSION_RAG_HANDOFF', 'required')
    models: list[str] = []

    async def invoke(payload):
        models.append(str(payload.get('model')))
        raise RuntimeError('wrapper unavailable')

    with pytest.raises(RuntimeError, match='wrapper unavailable'):
        asyncio.run(
            run_openai_with_session_rag_handoff(
                {
                    'model': 'raw.qwen-14b-llm',
                    'metadata': {'chat_id': 'chat-4', 'message_id': 'msg-4'},
                    'files': [{'id': 'file-4', 'name': 'contract.txt', 'type': 'text', 'content': 'Штраф 17 процентов'}],
                },
                invoke,
            )
        )

    assert models == ['llm-tools-platform']
