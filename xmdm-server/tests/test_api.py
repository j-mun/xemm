from pathlib import Path
import json

from fastapi.testclient import TestClient
import numpy as np
import pytest

from xmdm_server.api import create_app
from xmdm_server.db import SQLiteCatalog, initialize_database
from xmdm_server.services import DatabaseService


CUSTOM_DB = Path(__file__).resolve().parents[2] / 'xmdm' / 'tests' / 'custom-db'


def test_api_catalog_record_and_evaluation():
  client = TestClient(create_app(DatabaseService(CUSTOM_DB)))

  assert client.get('/api/v1/health').json() == {
    'service': 'xmdm-server', 'status': 'ok', 'read_only': True,
    'web_ui': True, 'mcp_http': False,
  }
  materials = client.get('/api/v1/materials').json()
  assert materials['total'] == 1
  assert materials['items'][0]['id'] == 'Example'
  assert client.get('/api/v1/materials/demo').json()['name'] == (
    'Synthetic optical material'
  )
  assert client.get('/api/v1/records?model=tabulated').json()['total'] == 1
  assert client.get(
    '/api/v1/records/Example/linear?model=tabulated',
  ).json()['name'] == 'linear'

  response = client.post('/api/v1/evaluate', json={
    'material_id': 'Example',
    'record_name': 'linear',
    'model': 'tabulated',
    'coordinates': [450, 550],
    'unit': 'nm',
    'parameter': 'n',
    'interpolation': 'linear',
  })
  assert response.status_code == 200
  np.testing.assert_allclose(
    [[value['real'], value['imag']] for value in response.json()['values']],
    [[2.5, 0.15], [3.5, 0.25]],
  )


def test_api_errors_have_stable_status_codes():
  client = TestClient(create_app(DatabaseService(CUSTOM_DB)))

  assert client.get('/api/v1/materials/missing').status_code == 404
  assert client.get('/api/v1/records/Example/missing').status_code == 404
  assert client.get('/api/v1/records?model=unknown').status_code == 400
  assert client.get('/api/v1/materials?limit=0').status_code == 422
  assert client.post('/api/v1/evaluate', json={
    'material_id': 'Example',
    'record_name': 'linear',
    'model': 'tabulated',
    'coordinates': [True],
    'unit': 'nm',
    'parameter': 'n',
  }).status_code == 422


def test_database_failure_is_logged_without_leaking_its_path(tmp_path, caplog):
  import shutil

  copied_database = tmp_path / 'database'
  shutil.copytree(CUSTOM_DB, copied_database)
  client = TestClient(create_app(DatabaseService(copied_database)))
  (copied_database / 'index.json').write_text(
    json.dumps({'schema_version': '1'}), encoding='utf-8',
  )

  response = client.get('/api/v1/materials')

  assert response.status_code == 503
  assert str(copied_database) not in response.text
  assert 'Configured material database is unavailable' in caplog.text


def test_bundled_database_is_exposed_by_http_api():
  client = TestClient(create_app(DatabaseService()))

  response = client.get('/api/v1/materials?limit=1')

  assert response.status_code == 200
  assert response.json()['total'] > 0
  assert len(response.json()['items']) == 1


@pytest.mark.parametrize('backend', ['json', 'sqlite'])
def test_nlo_http_evaluation_resampling_and_export(tmp_path, backend):
  from xmdm import database_directory

  if backend == 'sqlite':
    path = tmp_path / 'nonlinear.sqlite'
    catalog = SQLiteCatalog(initialize_database(path))
    catalog.import_json(database_directory())
    service = DatabaseService(path)
  else:
    service = DatabaseService()
  client = TestClient(create_app(service))
  record = service.get_record('ZnSe', 'Matteo-200ps', 'tabulated')
  assert record['physics'] == 'nlo'
  record_id = record['id']
  request = {
    'record_id': record_id,
    'coordinates': [10.6],
    'unit': 'um',
    'parameter': 'n2',
  }

  assert client.get('/api/v1/records?physics=nlo').json()['total'] == 207
  assert client.get('/api/v1/records?physics=optics').json()['total'] == 1265
  response = client.post('/api/v1/evaluate', json=request)
  assert response.status_code == 200
  np.testing.assert_allclose(
    response.json()['values'][0]['real'], 1.2e-18, rtol=1e-6,
  )
  human_request = {
    key: value for key, value in request.items() if key != 'record_id'
  }
  human_request.update({
    'material_id': 'ZnSe',
    'record_name': 'Matteo-200ps',
    'model': 'tabulated',
  })
  assert client.post('/api/v1/evaluate', json=human_request).status_code == 200
  resampled = client.post(
    f'/api/v1/records/{record_id}/resample',
    json={key: value for key, value in request.items() if key != 'record_id'},
  )
  assert resampled.status_code == 200
  assert resampled.json()['record']['physics'] == 'nlo'
  exported = client.get(f'/api/v1/records/{record_id}/export?format=json')
  assert exported.status_code == 200
  assert exported.json()['physics'] == 'nlo'
  invalid = client.post('/api/v1/evaluate', json={**request, 'parameter': 'n'})
  assert invalid.status_code == 400


def test_health_reports_database_unavailability_without_leaking_path(
    tmp_path, caplog,
):
  import shutil

  copied_database = tmp_path / 'database'
  shutil.copytree(CUSTOM_DB, copied_database)
  client = TestClient(create_app(DatabaseService(copied_database)))
  (copied_database / 'index.json').unlink()

  response = client.get('/api/v1/health')

  assert response.status_code == 503
  assert str(copied_database) not in response.text
  assert 'Configured material database is unavailable' in caplog.text


def test_uuid_revision_resample_and_spectrum_ui_routes():
  client = TestClient(create_app(DatabaseService(CUSTOM_DB)))
  record_id = '0a8c1393-f8da-4a29-a4bf-100aeb510f3e'

  record = client.get(f'/api/v1/records/{record_id}')
  assert record.status_code == 200
  assert record.json()['revision'] == 1
  assert client.get(f'/api/v1/records/{record_id}/data').json()['unit'] == 'nm'
  assert client.get(f'/api/v1/records/{record_id}/revisions').json()['items'][0]['revision'] == 1
  spectrum = client.post('/api/v1/evaluate', json={
    'record_id': record_id,
    'coordinates': [600, 400, 600],
    'unit': 'nm',
    'parameter': 'n',
  })
  assert spectrum.status_code == 200
  assert spectrum.json()['coordinates'] == [600, 400, 600]
  derived = client.post(f'/api/v1/records/{record_id}/resample', json={
    'coordinates': [600, 400, 600],
    'unit': 'nm',
    'parameter': 'e',
    'range_policy': 'error',
  })
  assert derived.status_code == 200
  assert derived.json()['record']['data']['f'] == [600, 400, 600]
  assert derived.json()['record']['data']['type'] == 'e'
  assert client.get(f'/api/v1/records/{record_id}/export?format=csv').status_code == 200

  assert client.get('/', follow_redirects=False).status_code == 307
  page = client.get('/data')
  assert page.status_code == 200
  assert 'Explore material spectra' in page.text
  assert 'Submit for review' not in page.text
  assert 'Preview and submit material data' not in page.text
  assert 'aria-current="page"' in page.text
  assert client.get('/upload').status_code == 200
  assert client.get('/admin').status_code == 200
  assert client.get('/status').status_code == 200
  assert client.get('/static/app.js').status_code == 200


def test_sqlite_record_writes_require_scoped_tokens_and_revision_etags(tmp_path):
  db_path = tmp_path / 'database.sqlite'
  catalog = SQLiteCatalog(initialize_database(db_path))
  catalog.import_json(CUSTOM_DB)
  service = DatabaseService(db_path)
  reader = service.create_token('reader', ['tokens:admin'])
  writer = service.create_token('writer', ['records:write'])
  client = TestClient(create_app(service))
  payload = service.get_record('Example', 'linear', 'tabulated')
  payload['name'] = 'client-submitted'
  payload.pop('id')
  request = {'material_id': 'Example', 'payload': payload}

  assert client.post('/api/v1/submissions', json=request).status_code == 401
  assert client.post(
    '/api/v1/submissions', json=request,
    headers={'Authorization': f'Bearer {reader["token"]}'},
  ).status_code == 403
  staged = client.post(
    '/api/v1/submissions', json=request,
    headers={'Authorization': f'Bearer {writer["token"]}'},
  )
  assert staged.status_code == 202
  assert staged.json()['status'] == 'pending'
  submission_id = staged.json()['submission_id']
  assert client.get(
    '/api/v1/admin/submissions',
    headers={'Authorization': f'Bearer {writer["token"]}'},
  ).status_code == 403
  pending = client.get(
    '/api/v1/admin/submissions',
    headers={'Authorization': f'Bearer {reader["token"]}'},
  )
  assert pending.status_code == 200
  assert pending.json()['items'][0]['submission_id'] == submission_id
  accepted = client.post(
    f'/api/v1/admin/submissions/{submission_id}/approve',
    headers={'Authorization': f'Bearer {reader["token"]}'},
  )
  assert accepted.status_code == 200
  record_id = accepted.json()['record_id']
  assert accepted.json()['revision'] == 1
  assert client.get(f'/api/v1/records/{record_id}').json()['record']['name'] == (
    'client-submitted'
  )

  replacement = dict(payload)
  replacement['name'] = 'client-submitted-revised'
  headers = {
    'Authorization': f'Bearer {writer["token"]}',
    'If-Match': '"1"',
  }
  revised = client.put(
    f'/api/v1/records/{record_id}',
    json={'payload': replacement},
    headers=headers,
  )
  assert revised.status_code == 202
  assert revised.json()['status'] == 'pending'
  revision_submission_id = revised.json()['submission_id']
  accepted_revision = client.post(
    f'/api/v1/admin/submissions/{revision_submission_id}/approve',
    headers={'Authorization': f'Bearer {reader["token"]}'},
  )
  assert accepted_revision.status_code == 200
  assert accepted_revision.json()['revision'] == 2
  stale = client.put(
    f'/api/v1/records/{record_id}',
    json={'payload': payload},
    headers=headers,
  )
  assert stale.status_code == 412
  assert client.get(
    f'/api/v1/records/{record_id}?revision=1',
  ).json()['record']['name'] == 'client-submitted'
  assert client.get(
    f'/api/v1/records/{record_id}?revision=2',
  ).json()['record']['name'] == 'client-submitted-revised'
  assert client.get(
    '/api/v1/admin/tokens',
    headers={'Authorization': f'Bearer {reader["token"]}'},
  ).status_code == 200

  with service.repository.connection() as connection:
    assert connection.execute('SELECT count(*) FROM audit_events').fetchone()[0] == 8


def test_submission_verification_and_admin_rejection(tmp_path):
  db_path = tmp_path / 'database.sqlite'
  catalog = SQLiteCatalog(initialize_database(db_path))
  catalog.import_json(CUSTOM_DB)
  service = DatabaseService(db_path)
  writer = service.create_token('writer', ['records:write'])
  admin = service.create_token('admin', ['tokens:admin'])
  client = TestClient(create_app(service))
  payload = service.get_record('Example', 'linear', 'tabulated')
  payload['name'] = 'rejected-upload'
  headers = {'Authorization': f'Bearer {writer["token"]}'}

  invalid = dict(payload)
  invalid['data'] = dict(payload['data'], re=[1.0])
  rejected_upload = client.post('/api/v1/submissions', json={
    'material_id': 'Example',
    'payload': invalid,
  }, headers=headers)
  assert rejected_upload.status_code == 400
  assert service.list_submissions() == []

  staged = client.post('/api/v1/submissions', json={
    'material_id': 'Example',
    'payload': payload,
  }, headers=headers)
  assert staged.status_code == 202
  result = client.post(
    f'/api/v1/admin/submissions/{staged.json()["submission_id"]}/reject',
    json={'note': 'Source metadata needs clarification'},
    headers={'Authorization': f'Bearer {admin["token"]}'},
  )
  assert result.status_code == 200
  assert result.json()['status'] == 'rejected'
  assert service.list_submissions() == []


def test_new_material_submission_is_created_only_upon_approval(tmp_path):
  service = DatabaseService(initialize_database(tmp_path / 'new.sqlite').path)
  writer = service.create_token('writer', ['records:write'])
  admin = service.create_token('admin', ['tokens:admin'])
  client = TestClient(create_app(service))
  payload = DatabaseService(CUSTOM_DB).get_record('Example', 'linear', 'tabulated')
  upload = {'material_id': 'NewAlloy', 'material_name': 'New alloy', 'payload': payload}
  headers = {'Authorization': 'Bearer ' + writer['token']}
  review_headers = {'Authorization': 'Bearer ' + admin['token']}

  assert client.post('/api/v1/submissions', json=upload).status_code == 401
  for invalid in [
    dict(upload, material_id='../unsafe'),
    dict(upload, material_id=' '),
    dict(upload, material_name=' '),
    dict(upload, payload=dict(payload, data=dict(payload['data'], re=[1]))),
  ]:
    assert client.post('/api/v1/submissions', json=invalid, headers=headers).status_code == 400
  assert service.list_submissions() == []
  assert service.list_materials()['total'] == 0

  staged = client.post('/api/v1/submissions', json=upload, headers=headers)
  assert staged.status_code == 202
  assert service.list_materials()['total'] == service.list_records()['total'] == 0
  pending = client.get('/api/v1/admin/submissions', headers=review_headers).json()['items']
  assert pending[0]['new_material'] is True
  assert pending[0]['material_id'] == 'NewAlloy'
  assert pending[0]['material_name'] == 'New alloy'
  rejected = client.post(
    f'/api/v1/admin/submissions/{staged.json()["submission_id"]}/reject',
    json={'note': 'Retry'}, headers=review_headers,
  )
  assert rejected.status_code == 200
  assert service.list_materials()['total'] == 0

  staged = client.post('/api/v1/submissions', json=upload, headers=headers)
  second_payload = dict(payload, name='second spectrum')
  second = client.post(
    '/api/v1/submissions', json=dict(upload, payload=second_payload), headers=headers,
  )
  assert staged.status_code == second.status_code == 202
  for submission in [staged, second]:
    accepted = client.post(
      f'/api/v1/admin/submissions/{submission.json()["submission_id"]}/approve',
      headers=review_headers,
    )
    assert accepted.status_code == 200
    assert client.get(
      f'/api/v1/records/{accepted.json()["record_id"]}',
    ).json()['record']['name'] in ('linear', 'second spectrum')
    assert accepted.json()['record_id'] in {
      record['id'] for record in service.list_records(material_id='NewAlloy')['items']
    }
  assert service.list_materials()['total'] == 1
  assert service.list_records()['total'] == 2
  assert client.post('/api/v1/submissions', json=upload, headers=headers).status_code == 400
  assert client.post(
    '/api/v1/submissions', json=dict(upload, material_id='DifferentID'), headers=headers,
  ).status_code == 400
  assert service.verify()['valid'] is True


def test_conflicting_new_material_approval_leaves_submission_pending(tmp_path):
  service = DatabaseService(initialize_database(tmp_path / 'conflict.sqlite').path)
  writer = service.create_token('writer', ['records:write'])
  admin = service.create_token('admin', ['tokens:admin'])
  client = TestClient(create_app(service))
  payload = DatabaseService(CUSTOM_DB).get_record('Example', 'linear', 'tabulated')
  upload = {'material_id': 'NewMaterial', 'material_name': 'First name', 'payload': payload}
  writer_headers = {'Authorization': 'Bearer ' + writer['token']}
  admin_headers = {'Authorization': 'Bearer ' + admin['token']}
  first = client.post('/api/v1/submissions', json=upload, headers=writer_headers)
  second = client.post(
    '/api/v1/submissions',
    json=dict(upload, material_name='Conflicting name', payload=dict(payload, name='second')),
    headers=writer_headers,
  )
  assert first.status_code == second.status_code == 202
  assert client.post(
    f'/api/v1/admin/submissions/{first.json()["submission_id"]}/approve',
    headers=admin_headers,
  ).status_code == 200
  assert client.post(
    f'/api/v1/admin/submissions/{second.json()["submission_id"]}/approve',
    headers=admin_headers,
  ).status_code == 412
  assert service.get_material('NewMaterial')['name'] == 'First name'
  assert service.list_records()['total'] == 1
  assert service.list_submissions()[0]['submission_id'] == second.json()['submission_id']


def test_token_admin_api_audits_creation_and_revocation(tmp_path):
  db_path = tmp_path / 'database.sqlite'
  catalog = SQLiteCatalog(initialize_database(db_path))
  catalog.import_json(CUSTOM_DB)
  service = DatabaseService(db_path)
  admin = service.create_token('root', ['tokens:admin'])
  client = TestClient(create_app(service))
  headers = {'Authorization': f'Bearer {admin["token"]}'}

  assert client.get('/api/v1/admin/tokens', headers=headers).status_code == 200
  created = client.post('/api/v1/admin/tokens', json={
    'name': 'temporary-writer',
    'scopes': ['records:write'],
  }, headers=headers)
  assert created.status_code == 201
  assert created.headers['Cache-Control'] == 'no-store'
  token = created.json()
  assert 'token_hash' not in token
  assert token['token'].startswith('xmdm_')
  events = client.get('/api/v1/admin/audit', headers=headers).json()['items']
  assert events[0]['action'] == 'token.create'
  assert events[0]['actor_token_id'] == admin['token_id']

  revoked = client.delete(
    f'/api/v1/admin/tokens/{token["token_id"]}', headers=headers,
  )
  assert revoked.status_code == 204
  assert client.post(
    '/api/v1/submissions',
    json={'material_id': 'Example', 'payload': {}},
    headers={'Authorization': f'Bearer {token["token"]}'},
  ).status_code == 401


def test_admin_record_archive_hides_and_restores_without_deleting_history(tmp_path):
  db_path = tmp_path / 'database.sqlite'
  catalog = SQLiteCatalog(initialize_database(db_path))
  catalog.import_json(CUSTOM_DB)
  service = DatabaseService(db_path)
  admin = service.create_token('admin', ['tokens:admin'])
  headers = {'Authorization': 'Bearer ' + admin['token']}
  client = TestClient(create_app(service))
  record_id = '0a8c1393-f8da-4a29-a4bf-100aeb510f3e'
  duplicate = service.get_record('Example', 'linear', 'tabulated')
  duplicate.pop('id')

  assert client.delete(
    f'/api/v1/admin/records/{record_id}',
  ).status_code == 401
  archived = client.delete(
    f'/api/v1/admin/records/{record_id}', headers=headers,
  )
  assert archived.status_code == 200
  assert archived.json()['record_id'] == record_id
  assert client.get(f'/api/v1/records/{record_id}').status_code == 404
  assert client.get('/api/v1/records').json()['total'] == 1
  admin_records = client.get(
    '/api/v1/admin/records', headers=headers,
  ).json()['items']
  archived_record = next(item for item in admin_records if item['id'] == record_id)
  assert archived_record['deleted_at'] is not None

  restored = client.post(
    f'/api/v1/admin/records/{record_id}/restore', headers=headers,
  )
  assert restored.status_code == 200
  assert client.get(f'/api/v1/records/{record_id}').status_code == 200

  assert client.delete(
    f'/api/v1/admin/records/{record_id}', headers=headers,
  ).status_code == 200
  service.create_record('Example', duplicate)
  conflict = client.post(
    f'/api/v1/admin/records/{record_id}/restore', headers=headers,
  )
  assert conflict.status_code == 400
  assert client.get(f'/api/v1/records/{record_id}').status_code == 404

  events = client.get('/api/v1/admin/audit', headers=headers).json()['items']
  assert [event['action'] for event in events[:3]] == [
    'record.create', 'record.archive', 'record.restore',
  ]
  assert events[3]['action'] == 'record.archive'
  assert events[3]['actor_token_id'] == admin['token_id']


def test_http_mcp_reads_are_public_and_submission_requires_request_token(
    tmp_path, monkeypatch,
):
  import asyncio
  import httpx

  pytest.importorskip('mcp')
  from mcp import ClientSession
  from mcp.client.streamable_http import streamable_http_client

  db_path = tmp_path / 'database.sqlite'
  catalog = SQLiteCatalog(initialize_database(db_path))
  catalog.import_json(CUSTOM_DB)
  service = DatabaseService(db_path)
  writer = service.create_token('writer', ['records:write'])
  monkeypatch.setenv(
    'XMDM_MCP_ALLOWED_HOSTS', 'materials.example.test:8000',
  )
  app = create_app(service, mcp_http=True, mcp_host='0.0.0.0')
  payload = service.get_record('Example', 'linear', 'tabulated')
  payload['name'] = 'mcp-http-submission'
  payload.pop('id')

  async def call_tool(headers, name, arguments):
    async with httpx.AsyncClient(
      transport=httpx.ASGITransport(app=app),
      base_url='http://localhost:8000',
      headers={'Host': 'materials.example.test:8000', **headers},
    ) as client:
      async with streamable_http_client(
        'http://localhost:8000/mcp/', http_client=client,
      ) as (read, write, _):
        async with ClientSession(read, write) as session:
          await session.initialize()
          return await session.call_tool(name, arguments)

  async def run():
    async with app.router.lifespan_context(app):
      listed = await call_tool({}, 'list_records', {})
      assert not listed.isError
      anonymous = await call_tool({}, 'submit_record', {
        'material_id': 'Example',
        'payload': payload,
      })
      assert anonymous.isError
      authenticated = await call_tool(
        {'Authorization': f'Bearer {writer["token"]}'},
        'submit_record',
        {'material_id': 'Example', 'payload': payload},
      )
      assert not authenticated.isError

      async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url='http://localhost:8000',
        headers={'Host': 'untrusted.example.test:8000'},
      ) as client:
        blocked = await client.get('/mcp/')
        assert blocked.status_code == 421

  asyncio.run(asyncio.wait_for(run(), timeout=20))
  pending = catalog.list_submissions()
  assert len(pending) == 1
  assert pending[0]['payload']['name'] == 'mcp-http-submission'
