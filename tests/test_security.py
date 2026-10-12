import asyncio
import json
import logging
import os
from pathlib import Path
import socket
import subprocess
import sys
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from src.config import Settings, settings
from src import api
from src.models import OCRResult
from src import formatter_llm, formatter_local

MARKER = 'fixture-private-content-never-log'


@pytest.mark.parametrize('token', ['', ' ', 'test', 'TEST', 'your-secure-token-here', '<redacted>', '<from-keychain>'])
def test_token_requires_explicit_nondefault_value(monkeypatch, token):
    monkeypatch.setenv('AUTH_TOKEN', token)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_missing_token_fails(monkeypatch):
    monkeypatch.delenv('AUTH_TOKEN')
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_settings_error_and_repr_do_not_expose_inputs():
    value = Settings(_env_file=None, auth_token=MARKER, llm_api_key=MARKER, llm_base_url=MARKER)
    assert MARKER not in repr(value) and value.auth_token.get_secret_value() == MARKER
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, auth_token=MARKER, port=MARKER)
    assert MARKER not in str(error.value)


def test_startup_error_does_not_echo_invalid_env(tmp_path):
    env = {'PATH': '/usr/bin:/bin', 'AUTH_TOKEN': 'fixture-configured', 'PORT': MARKER,
           'PYTHONPATH': str(Path(__file__).resolve().parents[1]),
           'PYTHONDONTWRITEBYTECODE': '1'}
    run = subprocess.run([sys.executable, '-c', 'import src.config'], cwd=tmp_path,
                         env=env, capture_output=True, text=True, timeout=10)
    assert run.returncode != 0 and MARKER not in run.stdout + run.stderr
    assert 'Invalid OCR configuration' in run.stderr


async def request(method, path, **kwargs):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app, raise_app_exceptions=False),
                                 base_url='http://fixture.invalid') as client:
        return await client.request(method, path, **kwargs)


@pytest.mark.parametrize('header,accepted', [(None,False),('Bearer wrong-fixture',False),('Bearer fixture-ocr-auth-token',True)])
def test_bearer_boundary_and_query_token_is_not_auth(header,accepted):
    headers={} if header is None else {'Authorization':header}
    response=asyncio.run(request('GET','/stats?token=fixture-ocr-auth-token',headers=headers))
    assert (response.status_code == 200) is accepted
    if not accepted: assert response.status_code in (401,403)


def test_validation_payload_query_and_unknown_path_never_logged(caplog):
    caplog.set_level(logging.DEBUG)
    response=asyncio.run(request('POST','/predict?token='+MARKER,
        headers={'Authorization':'Bearer fixture-ocr-auth-token'},json={'image_base64':MARKER}))
    assert response.status_code==422 and MARKER not in response.text
    asyncio.run(request('GET','/'+MARKER+'?token='+MARKER))
    app_logs = '\n'.join(r.getMessage() for r in caplog.records if r.name.startswith('src.'))
    assert MARKER not in app_logs
    assert 'status=422' in caplog.text and 'route=/predict' in caplog.text
    assert 'route=<unmatched>' in caplog.text


@pytest.mark.parametrize('route', ['/predict','/predict-format'])
@pytest.mark.parametrize('error,status', [(ValueError,400),(RuntimeError,500),(Exception,500)])
def test_ocr_errors_redacted_on_both_routes(monkeypatch,caplog,route,error,status):
    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(api.ocr_service,'process_image',AsyncMock(side_effect=error(MARKER)))
    response=asyncio.run(request('POST',route,headers={'Authorization':'Bearer fixture-ocr-auth-token'},
                                json={'image_base64':'aGVsbG8='}))
    assert response.status_code==status
    assert MARKER not in caplog.text + response.text


def test_general_error_is_fixed_even_with_debug_setting(monkeypatch,caplog):
    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(api.ocr_service,'get_stats',lambda: (_ for _ in ()).throw(Exception(MARKER)))
    response=asyncio.run(request('GET','/stats',headers={'Authorization':'Bearer fixture-ocr-auth-token'}))
    assert response.status_code==500 and MARKER not in caplog.text + response.text
    assert api.app.debug is False


@pytest.mark.parametrize('dependency',['uvicorn.access','httpx','httpcore.connection'])
def test_dependency_url_logging_is_suppressed(tmp_path,dependency):
    # pytest intentionally attaches capture handlers to non-propagating loggers.
    # Verify real process sinks instead of treating its intercepted records as output.
    code = """
import asyncio,logging,httpx
from src import api
logging.getLogger(DEPENDENCY).error(MARKER)
async def probe():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app),base_url='http://fixture.invalid') as c:
        r=await c.get('/'+MARKER+'?secret='+MARKER)
        assert r.status_code==404
asyncio.run(probe())
api.ocr_service.executor.shutdown(wait=True)
""".replace('DEPENDENCY',repr(dependency)).replace('MARKER',repr(MARKER))
    env={'PATH':'/usr/bin:/bin','AUTH_TOKEN':'fixture-configured',
         'PYTHONPATH':str(Path(__file__).resolve().parents[1]),'PYTHONDONTWRITEBYTECODE':'1'}
    run=subprocess.run([sys.executable,'-c',code],cwd=tmp_path,env=env,capture_output=True,text=True,timeout=15)
    assert run.returncode==0 and MARKER not in run.stdout+run.stderr


@pytest.mark.parametrize('status',[401,403,429,503])
def test_llm_error_body_and_url_redacted(monkeypatch,caplog,status):
    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(settings,'llm_base_url','https://fixture.invalid/v1?secret='+MARKER)
    monkeypatch.setattr(settings,'llm_api_key',MARKER)
    async def fake_post(*args,**kwargs):
        return httpx.Response(status,text=MARKER,request=httpx.Request('POST','https://fixture.invalid/'+MARKER))
    monkeypatch.setattr(httpx.AsyncClient,'post',fake_post)
    result=asyncio.run(formatter_llm.format_with_llm([OCRResult(dt_boxes=[],rec_txt=MARKER,score=1)]))
    assert not result.success and str(status) in result.error
    assert MARKER not in result.error + caplog.text


@pytest.mark.parametrize('fault',[httpx.TimeoutException,RuntimeError])
def test_llm_transport_errors_redacted(monkeypatch,caplog,fault):
    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(settings,'llm_base_url','https://fixture.invalid/v1')
    monkeypatch.setattr(settings,'llm_api_key',MARKER)
    async def fake_post(*args,**kwargs): raise fault(MARKER)
    monkeypatch.setattr(httpx.AsyncClient,'post',fake_post)
    result=asyncio.run(formatter_llm.format_with_llm([OCRResult(dt_boxes=[],rec_txt=MARKER,score=1)]))
    assert not result.success and MARKER not in result.error + caplog.text


def test_llm_success_preserves_text_without_logging(monkeypatch,caplog):
    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(settings,'llm_base_url','https://fixture.invalid/v1')
    monkeypatch.setattr(settings,'llm_api_key','fixture-key')
    async def fake_post(*args,**kwargs):
        return httpx.Response(200,json={'choices':[{'message':{'content':MARKER}}]},
                              request=httpx.Request('POST','https://fixture.invalid/v1/chat/completions'))
    monkeypatch.setattr(httpx.AsyncClient,'post',fake_post)
    result=asyncio.run(formatter_llm.format_with_llm([OCRResult(dt_boxes=[],rec_txt=MARKER,score=1)]))
    assert result.success and result.markdown==MARKER and MARKER not in caplog.text


def test_native_sandbox_denies_network_and_outside_write(tmp_path):
    if not os.environ.get('OCR_QA_OUTSIDE_WRITE_PATH'):
        pytest.skip('explicit native sandbox verification only')
    with pytest.raises(PermissionError): socket.create_connection(('127.0.0.1',9),timeout=1)
    with pytest.raises(PermissionError): Path(os.environ['OCR_QA_OUTSIDE_WRITE_PATH']).write_text('fixture')


@pytest.mark.parametrize('traceback', [False, True])
def test_uvicorn_server_error_record_redacted(caplog, traceback):
    caplog.set_level(logging.DEBUG)
    try:
        raise RuntimeError(MARKER)
    except RuntimeError:
        logging.getLogger('uvicorn.error').error('ASGI failure %s', MARKER, exc_info=traceback)
    assert MARKER not in caplog.text and 'ASGI server error' in caplog.text
    assert all(not r.exc_info and not r.exc_text for r in caplog.records if r.name=='uvicorn.error')


def test_local_formatter_exception_redacted(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    def fail(*args, **kwargs): raise RuntimeError(MARKER)
    monkeypatch.setattr(formatter_local, '_merge_paragraphs', fail)
    result = formatter_local.format_locally([OCRResult(dt_boxes=[[0,0],[1,0],[1,1],[0,1]], rec_txt=MARKER, score=1)], image_size=(100,100))
    assert not result.success and MARKER not in result.error + caplog.text
