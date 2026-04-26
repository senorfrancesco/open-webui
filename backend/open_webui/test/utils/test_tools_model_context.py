import ast
from pathlib import Path
from typing import Any, Dict, Tuple


FORWARD_SESSION_INFO_HEADER_MODEL_ID = 'X-OpenWebUI-Model-Id'


def _load_model_context_helper():
    source_path = Path(__file__).resolve().parents[2] / 'utils' / 'tools.py'
    module_ast = ast.parse(source_path.read_text(encoding='utf-8'))
    wanted_names = {
        '_is_llm_tools_platform_tool_server',
        '_normalize_forwarded_model_id',
        '_resolve_forwarded_model_id',
        '_apply_llm_tools_platform_model_context',
    }
    selected_nodes = []
    for node in module_ast.body:
        if isinstance(node, ast.Assign):
            names = {target.id for target in node.targets if isinstance(target, ast.Name)}
            if names & {'LLM_TOOLS_PLATFORM_BOOTSTRAP_ID', 'LLM_TOOLS_PLATFORM_TOOL_SERVER_NAME'}:
                selected_nodes.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in wanted_names:
            selected_nodes.append(node)

    extracted_module = ast.Module(body=selected_nodes, type_ignores=[])
    ast.fix_missing_locations(extracted_module)
    namespace = {
        'Any': Any,
        'Dict': Dict,
        'Tuple': Tuple,
        'FORWARD_SESSION_INFO_HEADER_MODEL_ID': FORWARD_SESSION_INFO_HEADER_MODEL_ID,
    }
    exec(compile(extracted_module, str(source_path), 'exec'), namespace)
    return namespace['_apply_llm_tools_platform_model_context']


_apply_llm_tools_platform_model_context = _load_model_context_helper()


def test_llm_tools_platform_tool_server_receives_current_model_context():
    headers, params = _apply_llm_tools_platform_model_context(
        headers={'Content-Type': 'application/json'},
        params={
            'equipment_query': 'Проверь оборудование',
            'user_inputs': {'rag_scope': 'session'},
        },
        server_data={'info': {'title': 'llm-tools-platform OpenAPI Tool Server'}},
        connection={
            'path': '/tool-server/openapi.json',
            'config': {'bootstrap_id': 'llm_tools_platform_openapi_tool_server'},
        },
        metadata={'model_id': 'qwen-14b-llm'},
    )

    assert headers[FORWARD_SESSION_INFO_HEADER_MODEL_ID] == 'qwen-14b-llm'
    assert params['equipment_query'] == 'Проверь оборудование'
    assert params['user_inputs'] == {
        'rag_scope': 'session',
        'current_model_id': 'qwen-14b-llm',
    }


def test_llm_tools_platform_tool_server_prefers_selected_model_id():
    headers, params = _apply_llm_tools_platform_model_context(
        headers={},
        params={'user_inputs': {'current_model_id': 'stale-model'}},
        server_data={'info': {'title': 'llm-tools-platform OpenAPI Tool Server'}},
        connection={'path': '/tool-server/openapi.json'},
        metadata={'model_id': 'qwen-14b-llm', 'selected_model_id': 'qwen-vl-8b'},
    )

    assert headers[FORWARD_SESSION_INFO_HEADER_MODEL_ID] == 'qwen-vl-8b'
    assert params['user_inputs']['current_model_id'] == 'qwen-vl-8b'


def test_llm_tools_platform_tool_server_ignores_agent_wrapper_model():
    headers, params = _apply_llm_tools_platform_model_context(
        headers={'Content-Type': 'application/json'},
        params={'user_inputs': {'rag_scope': 'session'}},
        server_data={'info': {'title': 'llm-tools-platform OpenAPI Tool Server'}},
        connection={'path': '/tool-server/openapi.json'},
        metadata={'model_id': 'llm-tools-platform'},
    )

    assert headers == {'Content-Type': 'application/json'}
    assert params == {'user_inputs': {'rag_scope': 'session'}}


def test_non_platform_tool_server_does_not_receive_model_context():
    headers, params = _apply_llm_tools_platform_model_context(
        headers={'Content-Type': 'application/json'},
        params={'query': 'search', 'user_inputs': {'rag_scope': 'session'}},
        server_data={'info': {'title': 'External OpenAPI Tool Server'}},
        connection={'path': '/openapi.json', 'config': {'name': 'External OpenAPI Tool Server'}},
        metadata={'model_id': 'qwen-14b-llm'},
    )

    assert headers == {'Content-Type': 'application/json'}
    assert params == {'query': 'search', 'user_inputs': {'rag_scope': 'session'}}
