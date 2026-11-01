import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

import json
import pytest

from xmdm_server.cli import main
from xmdm_server.config import Settings


CUSTOM_DB = Path(__file__).resolve().parents[2] / 'xmdm' / 'tests' / 'custom-db'


def test_verify_command_uses_custom_database(capsys):
  assert main(['verify', '--db', str(CUSTOM_DB)]) == 0
  report = json.loads(capsys.readouterr().out)
  assert report == {'valid': True, 'checked': 2, 'errors': []}


def test_invalid_environment_port_is_reported(monkeypatch, capsys):
  monkeypatch.setenv('XMDM_PORT', 'invalid')
  assert main(['server']) == 1
  assert 'XMDM_PORT must be an integer' in capsys.readouterr().err


def test_command_line_settings_override_environment(monkeypatch):
  monkeypatch.setenv('XMDM_DB', '/environment/database')
  monkeypatch.setenv('XMDM_HOST', '0.0.0.0')
  monkeypatch.setenv('XMDM_PORT', '8080')

  settings = Settings.from_environment(
    db='/command/database', host='127.0.0.1', port=9000,
  )

  assert settings == Settings('/command/database', '127.0.0.1', 9000)


def test_sqlite_database_and_token_admin_commands(tmp_path, capsys):
  db_path = tmp_path / 'database.sqlite'
  assert main(['db', 'init', '--db', str(db_path), '--empty']) == 0
  assert json.loads(capsys.readouterr().out)['empty']
  assert main([
    'db', 'import', '--source', str(CUSTOM_DB), '--db', str(db_path),
  ]) == 0
  assert json.loads(capsys.readouterr().out)['created'] == 2
  assert main(['verify', '--db', str(db_path)]) == 0
  assert json.loads(capsys.readouterr().out)['valid']

  export = tmp_path / 'exported'
  assert main([
    'db', 'export', '--db', str(db_path), '--destination', str(export),
  ]) == 0
  assert (export / 'index.json').is_file()
  capsys.readouterr()
  backup = tmp_path / 'backup.sqlite'
  assert main([
    'db', 'backup', '--db', str(db_path), '--destination', str(backup),
  ]) == 0
  assert backup.is_file()
  capsys.readouterr()

  assert main([
    'admin', 'token', 'create', '--db', str(db_path),
    '--name', 'test-writer', '--scope', 'records:write',
  ]) == 0
  created = json.loads(capsys.readouterr().out)
  assert created['token'].startswith('xmdm_')
  assert main(['admin', 'token', 'list', '--db', str(db_path)]) == 0
  assert json.loads(capsys.readouterr().out)[0]['token_id'] == created['token_id']
  assert main([
    'admin', 'token', 'revoke', '--db', str(db_path), created['token_id'],
  ]) == 0
  assert json.loads(capsys.readouterr().out)['revoked'] == created['token_id']


def test_server_command_starts_http_api():
  pytest.importorskip('uvicorn')
  server_src = Path(__file__).resolve().parents[1] / 'src'
  xmdm_src = Path(__file__).resolve().parents[2] / 'xmdm' / 'src'
  env = {
    **os.environ,
    'PYTHONPATH': os.pathsep.join((str(server_src), str(xmdm_src))),
  }
  with socket.socket() as sock:
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
  process = subprocess.Popen(
    [
      sys.executable, '-m', 'xmdm_server', 'server',
      '--db', str(CUSTOM_DB), '--port', str(port),
    ],
    env=env,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
  )
  try:
    deadline = time.monotonic() + 15
    while True:
      if process.poll() is not None:
        pytest.fail(f'server exited before readiness: {process.communicate()}')
      try:
        with urlopen(f'http://127.0.0.1:{port}/api/v1/health', timeout=1) as response:
          assert json.load(response)['status'] == 'ok'
        break
      except URLError:
        if time.monotonic() >= deadline:
          raise
        time.sleep(0.1)
  finally:
    if process.poll() is None:
      process.send_signal(signal.SIGINT)
    try:
      process.communicate(timeout=10)
    except subprocess.TimeoutExpired:
      process.kill()
      process.communicate()
  assert process.returncode == 0
