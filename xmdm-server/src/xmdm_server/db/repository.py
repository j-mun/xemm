"""SQLite connection management and storage schema migrations."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import math
from pathlib import Path
import sqlite3
from typing import Generator

CURRENT_SCHEMA_VERSION = 5
DEFAULT_BUSY_TIMEOUT = 5.0
MAX_BUSY_TIMEOUT = 30.0

_MIGRATIONS = {
  1: (
    """
    CREATE TABLE materials (
      id TEXT PRIMARY KEY CHECK (length(trim(id)) > 0),
      name TEXT NOT NULL CHECK (length(trim(name)) > 0),
      normalized_id TEXT NOT NULL UNIQUE
        CHECK (length(trim(normalized_id)) > 0),
      normalized_name TEXT NOT NULL
        CHECK (length(trim(normalized_name)) > 0),
      created_at TEXT NOT NULL CHECK (length(trim(created_at)) > 0)
    )
    """,
    """
    CREATE TABLE material_aliases (
      material_id TEXT NOT NULL REFERENCES materials(id),
      alias TEXT NOT NULL CHECK (length(trim(alias)) > 0),
      normalized_alias TEXT NOT NULL
        CHECK (length(trim(normalized_alias)) > 0),
      PRIMARY KEY (material_id, normalized_alias)
    )
    """,
    """
    CREATE TABLE records (
      id TEXT PRIMARY KEY CHECK (length(trim(id)) > 0),
      material_id TEXT NOT NULL REFERENCES materials(id),
      current_revision INTEGER NOT NULL CHECK (current_revision >= 1),
      created_at TEXT NOT NULL CHECK (length(trim(created_at)) > 0),
      FOREIGN KEY (id, current_revision)
        REFERENCES record_revisions(record_id, revision)
        DEFERRABLE INITIALLY DEFERRED
    )
    """,
    """
    CREATE TABLE record_revisions (
      record_id TEXT NOT NULL REFERENCES records(id),
      revision INTEGER NOT NULL CHECK (revision >= 1),
      name TEXT NOT NULL CHECK (length(trim(name)) > 0),
      normalized_name TEXT NOT NULL
        CHECK (length(trim(normalized_name)) > 0),
      physics TEXT NOT NULL CHECK (length(trim(physics)) > 0),
      model TEXT NOT NULL CHECK (length(trim(model)) > 0),
      schema_version TEXT NOT NULL CHECK (length(trim(schema_version)) > 0),
      data_json TEXT NOT NULL
        CHECK (json_valid(data_json) AND json_type(data_json) = 'object'),
      metadata_json TEXT NOT NULL
        CHECK (json_valid(metadata_json) AND json_type(metadata_json) = 'object'),
      payload_sha256 TEXT NOT NULL CHECK (length(payload_sha256) = 64),
      created_at TEXT NOT NULL CHECK (length(trim(created_at)) > 0),
      PRIMARY KEY (record_id, revision)
    )
    """,
    """
    CREATE TABLE record_derivations (
      record_id TEXT NOT NULL,
      revision INTEGER NOT NULL,
      source_record_id TEXT NOT NULL,
      source_revision INTEGER NOT NULL,
      operation TEXT NOT NULL CHECK (length(trim(operation)) > 0),
      parameters_json TEXT NOT NULL
        CHECK (
          json_valid(parameters_json)
          AND json_type(parameters_json) = 'object'
        ),
      PRIMARY KEY (record_id, revision),
      FOREIGN KEY (record_id, revision)
        REFERENCES record_revisions(record_id, revision),
      FOREIGN KEY (source_record_id, source_revision)
        REFERENCES record_revisions(record_id, revision)
    )
    """,
    """
    CREATE TABLE import_records (
      import_key TEXT PRIMARY KEY CHECK (length(trim(import_key)) > 0),
      source_record_id TEXT NOT NULL
        CHECK (length(trim(source_record_id)) > 0),
      source_material_id TEXT NOT NULL
        CHECK (length(trim(source_material_id)) > 0),
      record_id TEXT NOT NULL REFERENCES records(id),
      source_sha256 TEXT NOT NULL CHECK (length(source_sha256) = 64)
    )
    """,
    'CREATE INDEX materials_normalized_name_idx '
    'ON materials(normalized_name)',
    'CREATE INDEX material_aliases_normalized_alias_idx '
    'ON material_aliases(normalized_alias)',
    'CREATE INDEX record_revisions_normalized_name_idx '
    'ON record_revisions(normalized_name)',
    'CREATE INDEX record_revisions_physics_model_idx '
    'ON record_revisions(physics, model)',
  ),
  2: (
    """
    CREATE TABLE api_tokens (
      token_id TEXT PRIMARY KEY CHECK (length(trim(token_id)) > 0),
      token_hash TEXT NOT NULL UNIQUE CHECK (length(token_hash) = 64),
      name TEXT NOT NULL CHECK (length(trim(name)) > 0),
      scopes_json TEXT NOT NULL
        CHECK (json_valid(scopes_json) AND json_type(scopes_json) = 'array'),
      created_at TEXT NOT NULL CHECK (length(trim(created_at)) > 0),
      expires_at TEXT,
      revoked_at TEXT
    )
    """,
    """
    CREATE TABLE audit_events (
      event_id INTEGER PRIMARY KEY,
      actor_token_id TEXT REFERENCES api_tokens(token_id),
      action TEXT NOT NULL CHECK (length(trim(action)) > 0),
      object_type TEXT NOT NULL CHECK (length(trim(object_type)) > 0),
      object_id TEXT NOT NULL CHECK (length(trim(object_id)) > 0),
      details_json TEXT NOT NULL
        CHECK (json_valid(details_json) AND json_type(details_json) = 'object'),
      created_at TEXT NOT NULL CHECK (length(trim(created_at)) > 0)
    )
    """,
    'CREATE INDEX audit_events_created_at_idx '
    'ON audit_events(created_at)',
    """
    CREATE TRIGGER record_revisions_no_update
    BEFORE UPDATE ON record_revisions
    BEGIN
      SELECT RAISE(ABORT, 'record revisions are immutable');
    END
    """,
    """
    CREATE TRIGGER record_revisions_no_delete
    BEFORE DELETE ON record_revisions
    BEGIN
      SELECT RAISE(ABORT, 'record revisions are immutable');
    END
    """,
    """
    CREATE TRIGGER record_identity_immutable
    BEFORE UPDATE OF id, material_id ON records
    BEGIN
      SELECT RAISE(ABORT, 'record identity is immutable');
    END
    """,
    """
    CREATE TRIGGER record_revision_must_advance
    BEFORE UPDATE OF current_revision ON records
    WHEN NEW.current_revision <= OLD.current_revision
    BEGIN
      SELECT RAISE(ABORT, 'current revision must advance');
    END
    """,
    """
    CREATE TRIGGER audit_events_no_update
    BEFORE UPDATE ON audit_events
    BEGIN
      SELECT RAISE(ABORT, 'audit events are immutable');
    END
    """,
    """
    CREATE TRIGGER audit_events_no_delete
    BEFORE DELETE ON audit_events
    BEGIN
      SELECT RAISE(ABORT, 'audit events are immutable');
    END
    """,
  ),
  3: (
    """
    CREATE TABLE pending_submissions (
      submission_id TEXT PRIMARY KEY CHECK (length(trim(submission_id)) > 0),
      material_id TEXT NOT NULL REFERENCES materials(id),
      target_record_id TEXT REFERENCES records(id),
      expected_revision INTEGER,
      payload_json TEXT NOT NULL
        CHECK (json_valid(payload_json) AND json_type(payload_json) = 'object'),
      derivation_json TEXT
        CHECK (
          derivation_json IS NULL
          OR (
            json_valid(derivation_json)
            AND json_type(derivation_json) = 'object'
          )
        ),
      submitted_by_token_id TEXT NOT NULL REFERENCES api_tokens(token_id),
      submitted_at TEXT NOT NULL CHECK (length(trim(submitted_at)) > 0),
      status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'accepted', 'rejected')),
      reviewed_by_token_id TEXT REFERENCES api_tokens(token_id),
      reviewed_at TEXT,
      review_note TEXT,
      accepted_record_id TEXT,
      accepted_revision INTEGER,
      CHECK (
        (target_record_id IS NULL AND expected_revision IS NULL)
        OR (target_record_id IS NOT NULL AND expected_revision >= 1)
      ),
      CHECK (
        (status = 'pending' AND reviewed_at IS NULL)
        OR (status IN ('accepted', 'rejected') AND reviewed_at IS NOT NULL)
      )
    )
    """,
    'CREATE INDEX pending_submissions_status_idx '
    'ON pending_submissions(status, submitted_at)',
  ),
  4: (
    'ALTER TABLE records ADD COLUMN deleted_at TEXT',
    'CREATE INDEX records_deleted_at_idx ON records(deleted_at)',
  ),
  5: (
    'ALTER TABLE pending_submissions RENAME TO old_pending_submissions',
    'DROP INDEX pending_submissions_status_idx',
    """
    CREATE TABLE pending_submissions (
      submission_id TEXT PRIMARY KEY CHECK (length(trim(submission_id)) > 0),
      material_id TEXT REFERENCES materials(id),
      new_material_json TEXT
        CHECK (
          new_material_json IS NULL
          OR (json_valid(new_material_json) AND json_type(new_material_json) = 'object')
        ),
      target_record_id TEXT REFERENCES records(id),
      expected_revision INTEGER,
      payload_json TEXT NOT NULL
        CHECK (json_valid(payload_json) AND json_type(payload_json) = 'object'),
      derivation_json TEXT
        CHECK (
          derivation_json IS NULL
          OR (json_valid(derivation_json) AND json_type(derivation_json) = 'object')
        ),
      submitted_by_token_id TEXT NOT NULL REFERENCES api_tokens(token_id),
      submitted_at TEXT NOT NULL CHECK (length(trim(submitted_at)) > 0),
      status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'accepted', 'rejected')),
      reviewed_by_token_id TEXT REFERENCES api_tokens(token_id),
      reviewed_at TEXT,
      review_note TEXT,
      accepted_record_id TEXT,
      accepted_revision INTEGER,
      CHECK ((material_id IS NULL) != (new_material_json IS NULL)),
      CHECK (
        (target_record_id IS NULL AND expected_revision IS NULL)
        OR (target_record_id IS NOT NULL AND expected_revision >= 1
            AND material_id IS NOT NULL)
      ),
      CHECK (
        (status = 'pending' AND reviewed_at IS NULL)
        OR (status IN ('accepted', 'rejected') AND reviewed_at IS NOT NULL)
      )
    )
    """,
    """
    INSERT INTO pending_submissions (
      submission_id, material_id, target_record_id, expected_revision,
      payload_json, derivation_json, submitted_by_token_id, submitted_at,
      status, reviewed_by_token_id, reviewed_at, review_note,
      accepted_record_id, accepted_revision
    )
    SELECT submission_id, material_id, target_record_id, expected_revision,
      payload_json, derivation_json, submitted_by_token_id, submitted_at,
      status, reviewed_by_token_id, reviewed_at, review_note,
      accepted_record_id, accepted_revision FROM old_pending_submissions
    """,
    'DROP TABLE old_pending_submissions',
    'CREATE INDEX pending_submissions_status_idx '
    'ON pending_submissions(status, submitted_at)',
  ),
}


class DatabaseSchemaError(RuntimeError):
  """The SQLite file is not a supported XMDM server database."""


def _validate_timeout(timeout: float) -> None:
  if (
    isinstance(timeout, bool)
    or not isinstance(timeout, (int, float))
    or not math.isfinite(timeout)
    or not 0 < timeout <= MAX_BUSY_TIMEOUT
  ):
    raise ValueError(
      f'timeout must be a finite number in the range 0..{MAX_BUSY_TIMEOUT}',
    )


class SQLiteRepository:
  """Open an existing SQLite database without creating or migrating it."""

  def __init__(
      self,
      path: str | Path,
      *,
      timeout: float = DEFAULT_BUSY_TIMEOUT,
  ):
    _validate_timeout(timeout)
    self.path = Path(path).expanduser()
    self.timeout = float(timeout)

  @contextmanager
  def connection(self) -> Generator[sqlite3.Connection, None, None]:
    """Yield a connection with foreign-key enforcement enabled."""
    if not self.path.is_file():
      raise FileNotFoundError(f'SQLite database does not exist: {self.path}')

    uri = f'{self.path.resolve().as_uri()}?mode=rw'
    connection = sqlite3.connect(
      uri,
      uri=True,
      timeout=self.timeout,
      isolation_level=None,
    )
    try:
      connection.row_factory = sqlite3.Row
      connection.execute('PRAGMA foreign_keys = ON')
      connection.execute(f'PRAGMA busy_timeout = {int(self.timeout * 1000)}')
      yield connection
    finally:
      connection.close()

  @contextmanager
  def transaction(self) -> Generator[sqlite3.Connection, None, None]:
    """Run a bounded write transaction and roll it back if it fails."""
    with self.connection() as connection:
      connection.execute('BEGIN IMMEDIATE')
      try:
        yield connection
        connection.commit()
      except Exception:
        connection.rollback()
        raise


def _table_names(connection: sqlite3.Connection) -> set[str]:
  return {
    row['name']
    for row in connection.execute(
      "SELECT name FROM sqlite_master "
      "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'",
    )
  }


def _migrate_connection(connection: sqlite3.Connection) -> None:
  connection.execute('BEGIN IMMEDIATE')
  tables = _table_names(connection)

  if 'schema_migrations' not in tables:
    if tables:
      raise DatabaseSchemaError(
        'SQLite file contains tables but no XMDM migration history',
      )
    connection.execute(
      """
      CREATE TABLE schema_migrations (
        version INTEGER PRIMARY KEY CHECK (version >= 1),
        applied_at TEXT NOT NULL CHECK (length(trim(applied_at)) > 0)
      )
      """,
    )
    current_version = 0
  else:
    rows = connection.execute(
      'SELECT version FROM schema_migrations ORDER BY version',
    ).fetchall()
    if not rows:
      if tables - {'schema_migrations'}:
        raise DatabaseSchemaError(
          'SQLite migration history is empty but application tables exist',
        )
      current_version = 0
    else:
      versions = [row['version'] for row in rows]
      current_version = max(versions)
      if current_version > CURRENT_SCHEMA_VERSION:
        raise DatabaseSchemaError(
          f'SQLite schema version {current_version} is newer than supported '
          f'version {CURRENT_SCHEMA_VERSION}',
        )
      if versions != list(range(1, current_version + 1)):
        raise DatabaseSchemaError('SQLite migration history is inconsistent')

  for version in range(current_version + 1, CURRENT_SCHEMA_VERSION + 1):
    for statement in _MIGRATIONS[version]:
      connection.execute(statement)
    connection.execute(
      'INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)',
      (version, datetime.now(UTC).isoformat()),
    )
  connection.commit()


def initialize_database(
    path: str | Path,
    *,
    timeout: float = DEFAULT_BUSY_TIMEOUT,
) -> SQLiteRepository:
  """Create and initialize a new SQLite file; never overwrite an existing one."""
  _validate_timeout(timeout)
  database_path = Path(path).expanduser()
  with database_path.open('xb'):
    pass

  repository = SQLiteRepository(database_path, timeout=timeout)
  try:
    with repository.connection() as connection:
      connection.execute('PRAGMA journal_mode = WAL')
      _migrate_connection(connection)
  except Exception:
    database_path.unlink(missing_ok=True)
    raise
  return repository


def migrate_database(
    path: str | Path,
    *,
    timeout: float = DEFAULT_BUSY_TIMEOUT,
) -> SQLiteRepository:
  """Apply pending migrations to an existing SQLite file."""
  repository = SQLiteRepository(path, timeout=timeout)
  with repository.connection() as connection:
    _migrate_connection(connection)
  return repository
