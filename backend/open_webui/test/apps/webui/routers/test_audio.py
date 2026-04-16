import builtins
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
import types

import pytest

_TEST_DATA_DIR = tempfile.mkdtemp(prefix='openwebui-test-audio-')
os.environ.setdefault('DATA_DIR', _TEST_DATA_DIR)
os.environ.setdefault('ENABLE_DB_MIGRATIONS', 'false')

_TEST_CACHE_DIR = Path(tempfile.mkdtemp(prefix='openwebui-test-cache-'))

stub_auth = types.ModuleType('open_webui.utils.auth')
stub_auth.get_admin_user = lambda: None
stub_auth.get_verified_user = lambda: None
sys.modules['open_webui.utils.auth'] = stub_auth

stub_access_control = types.ModuleType('open_webui.utils.access_control')
stub_access_control.has_permission = lambda *args, **kwargs: True
sys.modules['open_webui.utils.access_control'] = stub_access_control

stub_headers = types.ModuleType('open_webui.utils.headers')
stub_headers.include_user_info_headers = lambda response, user: response
sys.modules['open_webui.utils.headers'] = stub_headers

stub_config = types.ModuleType('open_webui.config')
stub_config.WHISPER_MODEL_AUTO_UPDATE = False
stub_config.WHISPER_COMPUTE_TYPE = 'float32'
stub_config.WHISPER_MODEL_DIR = _TEST_CACHE_DIR / 'whisper'
stub_config.WHISPER_VAD_FILTER = False
stub_config.CACHE_DIR = _TEST_CACHE_DIR
stub_config.WHISPER_LANGUAGE = ''
stub_config.WHISPER_MULTILINGUAL = False
stub_config.ELEVENLABS_API_BASE_URL = 'https://api.elevenlabs.io'
sys.modules['open_webui.config'] = stub_config

from open_webui.routers.audio import load_speech_pipeline


def test_load_speech_pipeline_requires_datasets(monkeypatch):
    original_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == 'transformers':
            return SimpleNamespace(pipeline=lambda *args, **kwargs: None)
        if name == 'datasets':
            raise ImportError("No module named 'datasets'")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, '__import__', fake_import)

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                speech_synthesiser=None,
                speech_speaker_embeddings_dataset=None,
            )
        )
    )

    with pytest.raises(ImportError, match="Transformers TTS requires the 'datasets' package"):
        load_speech_pipeline(request)
