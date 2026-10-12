"""Synthetic settings only: never read a developer's .env in this suite."""
import os
import sys
from pathlib import Path
os.environ['AUTH_TOKEN'] = 'fixture-ocr-auth-token'
os.environ['WORKERS'] = '1'
os.environ['LOG_FILE'] = ''
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def pytest_sessionfinish(session, exitstatus):
    module = sys.modules.get('src.ocr_service')
    if module:
        module.ocr_service.executor.shutdown(wait=True)
