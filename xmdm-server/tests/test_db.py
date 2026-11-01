import json
import sqlite3
import shutil
from pathlib import Path

import pytest

from xmdm_server.db import (
  CURRENT_SCHEMA_VERSION,
  DatabaseSchemaError,
  SQLiteRepository,
  initialize_database,
  migrate_database,
)


def test_initialize_and_migrate_database(tmp_path):
  path = tmp_path / 'materials.sqlite'

  repository = initialize_database(path)

  assert path.is_file()
  with repository.connection() as connection:
    assert connection.execute('PRAGMA foreign_keys').fetchone()[0] == 1
    assert connection.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
    assert connection.execute(
      'SELECT max(version) FROM schema_migrations',
    ).fetchone()[0] == CURRENT_SCHEMA_VERSION
    tables = {
      row['name']
      for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'",
      )
    }
  assert {
    'materials',
    'material_aliases',
    'records',
    'record_revisions',
    'record_derivations',
    'import_records',
    'api_tokens',
    'audit_events',
    'pending_submissions',
  } <= tables

  migrate_database(path)
  with repository.connection() as connection:
    assert connection.execute(
      'SELECT max(version) FROM schema_migrations',
    ).fetchone()[0] == CURRENT_SCHEMA_VERSION


def test_initialize_refuses_to_overwrite_existing_file(tmp_path):
  path = tmp_path / 'existing.sqlite'
  path.write_bytes(b'preserve this file')

  with pytest.raises(FileExistsError):
    initialize_database(path)

  assert path.read_bytes() == b'preserve this file'


def test_migration_preserves_version_four_pending_submissions(tmp_path):
  from xmdm_server.db.repository import _MIGRATIONS

  path = tmp_path / 'version-four.sqlite'
  with sqlite3.connect(path) as connection:
    connection.execute(
      'CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)',
    )
    for version in range(1, 5):
      for statement in _MIGRATIONS[version]:
        connection.execute(statement)
      connection.execute('INSERT INTO schema_migrations VALUES (?, ?)', (version, 'before'))
    connection.execute("INSERT INTO materials VALUES ('Example', 'Example', 'example', 'example', 'before')")
    connection.execute(
      "INSERT INTO api_tokens (token_id, token_hash, name, scopes_json, created_at) "
      "VALUES ('writer', ?, 'writer', '[]', 'before')", ('a' * 64,),
    )
    connection.execute(
      "INSERT INTO pending_submissions "
      "(submission_id, material_id, payload_json, submitted_by_token_id, submitted_at) "
      "VALUES ('submission', 'Example', '{}', 'writer', 'before')",
    )
  repository = migrate_database(path)
  with repository.connection() as connection:
    row = connection.execute('SELECT * FROM pending_submissions').fetchone()
    assert row['submission_id'] == 'submission'
    assert row['material_id'] == 'Example'
    assert row['new_material_json'] is None
    assert row['status'] == 'pending'
    assert connection.execute('PRAGMA foreign_key_check').fetchall() == []


def test_repository_does_not_create_missing_database(tmp_path):
  path = tmp_path / 'missing.sqlite'

  with pytest.raises(FileNotFoundError):
    with SQLiteRepository(path).connection():
      pass

  assert not path.exists()
  with pytest.raises(FileNotFoundError):
    migrate_database(path)


def test_migration_rejects_unknown_existing_schema(tmp_path):
  path = tmp_path / 'unrelated.sqlite'
  with sqlite3.connect(path) as connection:
    connection.execute('CREATE TABLE unrelated (id INTEGER)')

  with pytest.raises(DatabaseSchemaError, match='no XMDM migration history'):
    migrate_database(path)


def test_migration_rejects_newer_schema_version(tmp_path):
  path = tmp_path / 'future.sqlite'
  with sqlite3.connect(path) as connection:
    connection.execute(
      'CREATE TABLE schema_migrations '
      '(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)',
    )
    connection.execute(
      'INSERT INTO schema_migrations VALUES (?, ?)',
      (999, '2026-01-01T00:00:00+00:00'),
    )

  with pytest.raises(DatabaseSchemaError, match='newer than supported'):
    migrate_database(path)


def test_record_revision_pointer_is_deferred_to_transaction_commit(tmp_path):
  repository = initialize_database(tmp_path / 'materials.sqlite')
  with repository.transaction() as connection:
    connection.execute(
      """
      INSERT INTO materials
        (id, name, normalized_id, normalized_name, created_at)
      VALUES ('Ag', 'Silver', 'ag', 'silver', '2026-01-01T00:00:00+00:00')
      """,
    )
    connection.execute(
      """
      INSERT INTO records (id, material_id, current_revision, created_at)
      VALUES (
        '00000000-0000-4000-8000-000000000001',
        'Ag',
        1,
        '2026-01-01T00:00:00+00:00'
      )
      """,
    )
    connection.execute(
      """
      INSERT INTO record_revisions (
        record_id, revision, name, normalized_name, physics, model,
        schema_version, data_json, metadata_json, payload_sha256, created_at
      ) VALUES (
        '00000000-0000-4000-8000-000000000001',
        1,
        'Johnson',
        'johnson',
        'optics',
        'tabulated',
        '1',
        '{}',
        '{}',
        '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef',
        '2026-01-01T00:00:00+00:00'
      )
      """,
    )

  with repository.connection() as connection:
    assert connection.execute(
      'SELECT current_revision FROM records',
    ).fetchone()[0] == 1


def test_write_transaction_rolls_back_on_error(tmp_path):
  repository = initialize_database(tmp_path / 'materials.sqlite')
  with pytest.raises(sqlite3.IntegrityError):
    with repository.transaction() as connection:
      connection.execute(
        """
        INSERT INTO materials
          (id, name, normalized_id, normalized_name, created_at)
        VALUES ('Ag', 'Silver', 'ag', 'silver', '2026-01-01T00:00:00+00:00')
        """,
      )
      connection.execute(
        """
        INSERT INTO materials
          (id, name, normalized_id, normalized_name, created_at)
        VALUES ('Au', 'Gold', 'ag', 'gold', '2026-01-01T00:00:00+00:00')
        """,
      )

  with repository.connection() as connection:
    assert connection.execute('SELECT count(*) FROM materials').fetchone()[0] == 0


CUSTOM_DB = Path(__file__).resolve().parents[2] / 'xmdm' / 'tests' / 'custom-db'


def test_json_import_is_idempotent_and_export_round_trips(tmp_path):
  from xmdm_server.db.catalog import SQLiteCatalog

  path = tmp_path / 'database.sqlite'
  catalog = SQLiteCatalog(initialize_database(path))
  assert catalog.import_json(CUSTOM_DB) == {
    'created': 2, 'revised': 0, 'unchanged': 0,
  }
  assert catalog.import_json(CUSTOM_DB) == {
    'created': 0, 'revised': 0, 'unchanged': 2,
  }
  assert catalog.verify() == {'valid': True, 'checked': 2, 'errors': []}

  export_path = catalog.export_json(tmp_path / 'exported')
  new_catalog = SQLiteCatalog(
    initialize_database(tmp_path / 'round-trip.sqlite'),
  )
  assert new_catalog.import_json(export_path) == {
    'created': 2, 'revised': 0, 'unchanged': 0,
  }
  assert new_catalog.list_records()['total'] == 2
  assert new_catalog.verify()['valid']


def test_import_changed_payload_requires_explicit_revision_policy(tmp_path):
  from xmdm_server.db.catalog import SQLiteCatalog

  source = tmp_path / 'source'
  shutil.copytree(CUSTOM_DB, source)
  catalog = SQLiteCatalog(initialize_database(tmp_path / 'database.sqlite'))
  catalog.import_json(source)
  record_path = source / 'Example' / '0a8c1393-f8da-4a29-a4bf-100aeb510f3e.json'
  record = json.loads(record_path.read_text(encoding='utf-8'))
  record['metadata']['source'] = 'Updated source'
  record_path.write_text(json.dumps(record), encoding='utf-8')

  with pytest.raises(ValueError, match='payload changed'):
    catalog.import_json(source)
  report = catalog.import_json(source, on_change='new_revision')

  assert report == {'created': 0, 'revised': 1, 'unchanged': 1}
  assert catalog.get_record_envelope(record['id'])['current_revision'] == 2
  assert catalog.verify()['valid']


def test_import_collision_allocates_new_global_id(tmp_path):
  from xmdm_server.db.catalog import SQLiteCatalog

  second = tmp_path / 'second'
  (second / 'Other').mkdir(parents=True)
  record_id = '0a8c1393-f8da-4a29-a4bf-100aeb510f3e'
  source_record = json.loads(
    (CUSTOM_DB / 'Example' / f'{record_id}.json').read_text(encoding='utf-8'),
  )
  source_record['name'] = 'second-material'
  (second / 'Other' / f'{record_id}.json').write_text(
    json.dumps(source_record), encoding='utf-8',
  )
  (second / 'index.json').write_text(json.dumps({
    'schema_version': '1',
    'materials': {
      'Other': {
        'name': 'Second material',
        'aliases': [],
        'records': [{
          'id': record_id,
          'physics': 'optics',
          'model': 'tabulated',
          'name': 'second-material',
          'path': f'Other/{record_id}.json',
        }],
      },
    },
  }), encoding='utf-8')
  catalog = SQLiteCatalog(initialize_database(tmp_path / 'database.sqlite'))
  catalog.import_json(CUSTOM_DB, namespace='first')
  catalog.import_json(second, namespace='second')

  imported = catalog.get_material('Other')['records'][0]
  assert imported['id'] != record_id
  assert catalog.get_provenance(imported['id'])['import']['source_record_id'] == record_id


def test_backup_uses_sqlite_backup_api(tmp_path):
  from xmdm_server.db.catalog import SQLiteCatalog

  catalog = SQLiteCatalog(initialize_database(tmp_path / 'database.sqlite'))
  catalog.import_json(CUSTOM_DB)
  backup = catalog.backup(tmp_path / 'backup.sqlite')

  assert SQLiteCatalog(SQLiteRepository(backup)).verify()['valid']
  with pytest.raises(FileExistsError):
    catalog.backup(backup)


def test_submission_verification_review_and_acceptance(tmp_path):
  from xmdm_server.db.catalog import SQLiteCatalog
  from xmdm_server.errors import InvalidQuery

  catalog = SQLiteCatalog(initialize_database(tmp_path / 'database.sqlite'))
  catalog.import_json(CUSTOM_DB)
  writer = catalog.create_token('writer', ['records:write'])
  admin = catalog.create_token('reviewer', ['tokens:admin'])
  payload = catalog.get_record('Example', 'linear', 'tabulated')
  payload['name'] = 'submitted-spectrum'

  invalid = dict(payload)
  invalid['data'] = dict(payload['data'], re=[1.0])
  with pytest.raises(InvalidQuery, match='invalid record payload'):
    catalog.stage_submission(
      'Example', invalid, actor_token_id=writer['token_id'],
    )
  assert catalog.list_submissions() == []

  rejected = catalog.stage_submission(
    'Example', payload, actor_token_id=writer['token_id'],
  )
  assert rejected['status'] == 'pending'
  assert len(catalog.list_submissions()) == 1
  result = catalog.review_submission(
    rejected['submission_id'], 'reject', actor_token_id=admin['token_id'],
    note='Need a complete citation',
  )
  assert result['status'] == 'rejected'
  assert catalog.list_submissions() == []

  payload['name'] = 'accepted-spectrum'
  staged = catalog.stage_submission(
    'Example', payload, actor_token_id=writer['token_id'],
  )
  accepted = catalog.review_submission(
    staged['submission_id'], 'approve', actor_token_id=admin['token_id'],
  )
  assert accepted['status'] == 'accepted'
  assert accepted['revision'] == 1
  assert catalog.get_record_by_id(accepted['record_id'])['name'] == (
    'accepted-spectrum'
  )
  assert catalog.list_submissions('accepted')[0]['submission_id'] == (
    staged['submission_id']
  )
  assert catalog.verify()['valid']
