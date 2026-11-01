"""Catalog, revision, import, and token operations over SQLite."""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from functools import wraps
import hashlib
import io
import json
import math
import os
from pathlib import Path
import sqlite3
import tempfile
import unicodedata
import uuid
from typing import Any, ParamSpec, TypeVar

import numpy as np
from xmdm import (
  Cauchy,
  Drude,
  Lorentz,
  Material,
  RefractiveIndexFormula,
  Sellmeier,
  __version__ as _XMDM_VERSION,
  load_index,
  load_record,
  validate_record_data,
)
from xmdm._src._tabulated import _convert_unit

from ..errors import (
  AmbiguousRecord,
  DatabaseUnavailable,
  InvalidQuery,
  RecordNotFound,
  RevisionConflict,
)
from .repository import SQLiteRepository
from .repository import CURRENT_SCHEMA_VERSION

_RECORD_SCHEMA_VERSION = '1'
_SUPPORTED_MODELS = (
  'tabulated', 'drude', 'lorentz', 'sellmeier', 'cauchy', 'rii_formula',
)
_SUPPORTED_UNITS = ('m', 'nm', 'um', 'Hz', 'GHz', 'THz', 'cm-1', 'eV')
_ALLOWED_SCOPES = frozenset(('records:write', 'tokens:admin'))


from collections.abc import Callable

_P = ParamSpec('_P')
_R = TypeVar('_R')


def _database_errors(
    function: Callable[_P, _R],
) -> Callable[_P, _R]:
  @wraps(function)
  def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _R:
    try:
      return function(*args, **kwargs)
    except sqlite3.Error as error:
      raise DatabaseUnavailable(
        'the configured SQLite database is unavailable',
      ) from error
  return wrapped


def _normalized(value: str) -> str:
  return ''.join(
    character
    for character in unicodedata.normalize('NFKD', value).casefold()
    if not unicodedata.combining(character)
  )


def _canonical_json(value: Any) -> str:
  return json.dumps(
    value,
    allow_nan=False,
    ensure_ascii=False,
    sort_keys=True,
    separators=(',', ':'),
  )


def _sha256(value: Any) -> str:
  return hashlib.sha256(_canonical_json(value).encode('utf-8')).hexdigest()


def _utc_now() -> str:
  return datetime.now(UTC).isoformat()


def _safe_material_id(material_id: str) -> bool:
  return (
    bool(material_id)
    and material_id not in ('.', '..')
    and '/' not in material_id
    and '\\' not in material_id
  )


def _validate_payload(payload: dict[str, Any]) -> dict[str, Any]:
  if not isinstance(payload, dict):
    raise InvalidQuery('record payload must be a JSON object')
  if payload.get('schema_version') != _RECORD_SCHEMA_VERSION:
    raise InvalidQuery('unsupported record schema_version')
  physics = payload.get('physics')
  model = payload.get('model')
  name = payload.get('name')
  data = payload.get('data')
  metadata = payload.get('metadata', {})
  if not isinstance(physics, str) or not physics.strip():
    raise InvalidQuery('record physics must be a non-empty string')
  if model not in _SUPPORTED_MODELS:
    raise InvalidQuery(f'unsupported model: {model!r}')
  if not isinstance(name, str) or not name.strip():
    raise InvalidQuery('record name must be a non-empty string')
  if not isinstance(data, dict) or not isinstance(metadata, dict):
    raise InvalidQuery('record data and metadata must be JSON objects')
  validated = {
    'schema_version': _RECORD_SCHEMA_VERSION,
    'physics': physics,
    'model': model,
    'name': name,
    'data': data,
    'metadata': metadata,
  }
  try:
    validate_record_data(validated)
    _canonical_json(validated)
  except (KeyError, TypeError, ValueError, OverflowError) as error:
    raise InvalidQuery(f'invalid record payload: {error}') from error
  return validated


def _payload_from_row(row: sqlite3.Row) -> dict[str, Any]:
  return {
    'schema_version': row['schema_version'],
    'physics': row['physics'],
    'model': row['model'],
    'name': row['name'],
    'id': row['record_id'],
    'data': json.loads(row['data_json']),
    'metadata': json.loads(row['metadata_json']),
  }


def _validate_evaluation_physics(record: dict[str, Any], parameter: str) -> None:
  if record.get('physics') == 'nlo':
    if (
      record['model'] != 'tabulated'
      or record['data'].get('type') != 'n2'
      or parameter != 'n2'
    ):
      raise InvalidQuery(
        "nonlinear optics evaluation requires tabulated n2 data and parameter 'n2'",
      )
  elif record.get('physics') != 'optics':
    raise InvalidQuery(
      'only optics and tabulated nonlinear optics records can be evaluated',
    )


def _evaluate_payload(
    record: dict[str, Any],
    coordinates: list[int | float],
    unit: str,
    parameter: str,
    interpolation: str,
    *,
    range_policy: str = 'clip',
) -> list[complex]:
  if not coordinates:
    raise InvalidQuery('coordinates must be a non-empty array')
  if len(coordinates) > 10000:
    raise InvalidQuery('coordinates may contain at most 10000 values')
  if any(
    isinstance(value, bool)
    or not isinstance(value, (int, float))
    or not math.isfinite(value)
    for value in coordinates
  ):
    raise InvalidQuery('coordinates must contain finite numeric values')
  if unit not in _SUPPORTED_UNITS:
    raise InvalidQuery(f'unsupported spectral unit: {unit!r}')
  if parameter not in ('n', 'e', 'k', 'n2'):
    raise InvalidQuery("parameter must be 'n', 'e', 'k', or 'n2'")
  if interpolation not in ('linear', 'cubic'):
    raise InvalidQuery(f'unsupported interpolation: {interpolation!r}')
  if range_policy not in ('clip', 'error', 'extrapolate'):
    raise InvalidQuery(f'unsupported range_policy: {range_policy!r}')
  validate_record_data(record)
  _validate_evaluation_physics(record, parameter)
  data = record['data']
  model = record['model']
  inputs = np.asarray(coordinates, dtype=float)
  extrapolate = range_policy == 'extrapolate'

  if model == 'tabulated':
    if parameter == 'n2' and data.get('type') != 'n2':
      raise InvalidQuery("parameter 'n2' requires tabulated n2 data")
    if parameter == 'k' and data.get('type') not in ('n', 'nk', 'k'):
      raise InvalidQuery("parameter 'k' requires tabulated refractive-index data")
    source_unit = data['unit']
    if range_policy == 'error':
      lower, upper = sorted((
        float(_convert_unit(np.asarray(data['f'], dtype=float), source_unit, unit).min()),
        float(_convert_unit(np.asarray(data['f'], dtype=float), source_unit, unit).max()),
      ))
      if np.any(inputs < lower) or np.any(inputs > upper):
        raise InvalidQuery('coordinates fall outside the tabulated data range')
    material = Material(
      f=np.asarray(data['f'], dtype=float),
      re=np.asarray(data['re'], dtype=float),
      im=np.asarray(data['im'], dtype=float),
      unit=source_unit,
      kind=data['type'],
      name=record['name'],
    )
    values = material.interp(
      inputs, unit=unit, kind=parameter, interp=interpolation,
      extrap=extrapolate,
    )
  else:
    if parameter == 'n2':
      raise InvalidQuery("parameter 'n2' requires tabulated n2 data")
    if interpolation != 'linear':
      raise InvalidQuery(
        'interpolation is only configurable for tabulated records',
      )
    models = {
      'drude': lambda: Drude.from_params(
        data['eps_inf'], data['omega_p'], data['gamma'],
      ),
      'lorentz': lambda: Lorentz.from_params(
        data['eps_inf'], data['omega_p'], data['gamma'], data['omega_0'],
        data['f'],
      ),
      'sellmeier': lambda: Sellmeier.from_params(
        data['B'], data['C'], data.get('unit', 'um'),
      ),
      'cauchy': lambda: Cauchy.from_params(
        data['A'], data['B'], data['C'], data.get('unit', 'um'),
      ),
      'rii_formula': lambda: RefractiveIndexFormula.from_params(
        data['formula'], data['coefficients'], data.get('unit', 'um'),
        tuple(data['wavelength_range'])
        if data.get('wavelength_range') is not None else None,
      ),
    }
    dispersion = models[model]()
    if model == 'rii_formula' and data.get('wavelength_range') is not None:
      wavelength_range = np.asarray(data['wavelength_range'], dtype=float)
      converted = np.asarray(
        _convert_unit(inputs, unit, data.get('unit', 'um')), dtype=float,
      )
      outside = (
        np.any(converted < wavelength_range[0])
        or np.any(converted > wavelength_range[1])
      )
      if range_policy == 'error' and outside:
        raise InvalidQuery('coordinates fall outside the formula wavelength range')
      if range_policy == 'clip':
        clipped = np.clip(converted, *wavelength_range)
        inputs = np.asarray(
          _convert_unit(clipped, data.get('unit', 'um'), unit), dtype=float,
        )
    evaluate = dispersion.n if parameter in ('n', 'k') else dispersion.eps
    values = evaluate(inputs, unit=unit)
    if parameter == 'k':
      values = np.imag(values)

  result = np.asarray(values).reshape(-1)
  if result.size != len(coordinates) or not np.all(np.isfinite(result)):
    raise InvalidQuery('evaluation produced non-finite values')
  return [complex(value) for value in result]


def _range_warnings(
    record: dict[str, Any],
    coordinates: list[int | float],
    unit: str,
    range_policy: str,
) -> list[str]:
  if record['model'] not in ('tabulated', 'rii_formula'):
    return []
  data = record['data']
  if record['model'] == 'tabulated':
    converted = np.asarray(
      _convert_unit(np.asarray(data['f'], dtype=float), data['unit'], unit),
      dtype=float,
    )
    lower = float(converted.min())
    upper = float(converted.max())
  elif data.get('wavelength_range') is not None:
    converted = np.asarray(
      _convert_unit(
        np.asarray(data['wavelength_range'], dtype=float),
        data.get('unit', 'um'),
        unit,
      ),
      dtype=float,
    )
    lower, upper = sorted((float(converted[0]), float(converted[1])))
  else:
    return []
  values = np.asarray(coordinates, dtype=float)
  if np.any(values < lower) or np.any(values > upper):
    if range_policy == 'clip':
      return ['out-of-range coordinates were clipped to source endpoints']
    if range_policy == 'extrapolate':
      return ['out-of-range coordinates were extrapolated']
  return []


class SQLiteCatalog:
  """Service-facing operations for an initialized SQLite database."""

  def __init__(self, repository: SQLiteRepository):
    self.repository = repository

  @_database_errors
  def check_database(self) -> None:
    with self.repository.connection() as connection:
      version = connection.execute(
        'SELECT max(version) AS version FROM schema_migrations',
      ).fetchone()['version']
      if version != CURRENT_SCHEMA_VERSION:
        raise ValueError(f'unsupported SQLite schema version: {version!r}')
      if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
        raise ValueError('SQLite database integrity check failed')

  def _material_matches(
      self, connection: sqlite3.Connection, query: str,
  ) -> list[sqlite3.Row]:
    needle = _normalized(query)
    return connection.execute(
      """
      SELECT DISTINCT m.*
      FROM materials AS m
      LEFT JOIN material_aliases AS a ON a.material_id = m.id
      WHERE m.normalized_id = ? OR m.normalized_name = ?
         OR a.normalized_alias = ?
      ORDER BY m.id COLLATE NOCASE
      """,
      (needle, needle, needle),
    ).fetchall()

  def _resolve_material(
      self, connection: sqlite3.Connection, query: str,
  ) -> sqlite3.Row:
    matches = self._material_matches(connection, query)
    if not matches:
      raise RecordNotFound(f'material {query!r} not found')
    if len(matches) > 1:
      raise AmbiguousRecord(f'material {query!r} is ambiguous')
    return matches[0]

  def _current_records(
      self, connection: sqlite3.Connection,
  ) -> list[sqlite3.Row]:
    return connection.execute(
      """
      SELECT r.id AS record_id, r.material_id, r.current_revision,
             m.name AS material_name, rv.name, rv.normalized_name,
             rv.physics, rv.model, rv.schema_version, rv.data_json,
             rv.metadata_json, rv.payload_sha256, rv.created_at
      FROM records AS r
      JOIN materials AS m ON m.id = r.material_id
      JOIN record_revisions AS rv
        ON rv.record_id = r.id AND rv.revision = r.current_revision
      WHERE r.deleted_at IS NULL
      """,
    ).fetchall()

  @_database_errors
  def material_catalog(self) -> dict[str, Any]:
    with self.repository.connection() as connection:
      materials = connection.execute(
        'SELECT id, name FROM materials ORDER BY id COLLATE NOCASE',
      ).fetchall()
      entries: dict[str, Any] = {}
      for material in materials:
        aliases = connection.execute(
          'SELECT alias FROM material_aliases '
          'WHERE material_id = ? ORDER BY normalized_alias',
          (material['id'],),
        ).fetchall()
        entries[material['id']] = {
          'name': material['name'],
          'aliases': [row['alias'] for row in aliases],
          'records': [],
        }
      for record in self._current_records(connection):
        entries[record['material_id']]['records'].append({
          'id': record['record_id'],
          'name': record['name'],
          'model': record['model'],
          'physics': record['physics'],
          'source': json.loads(record['metadata_json']).get('source'),
        })
      return entries

  @_database_errors
  def list_materials(
      self,
      query: str = '',
      limit: int = 100,
      offset: int = 0,
      physics: str | None = None,
      model: str | None = None,
  ) -> dict[str, Any]:
    needle = _normalized(query)
    with self.repository.connection() as connection:
      records = self._current_records(connection)
      materials = connection.execute(
        'SELECT id, name FROM materials ORDER BY id COLLATE NOCASE',
      ).fetchall()
      items = []
      for material in materials:
        aliases = [
          row['alias']
          for row in connection.execute(
            'SELECT alias FROM material_aliases WHERE material_id = ?',
            (material['id'],),
          )
        ]
        matching = [
          record for record in records
          if record['material_id'] == material['id']
          and (physics is None or record['physics'] == physics)
          and (model is None or record['model'] == model)
        ]
        searchable = _normalized(
          ' '.join((material['id'], material['name'], *aliases)),
        )
        if (not needle or needle in searchable) and (
          (physics is None and model is None) or matching
        ):
          items.append({
            'id': material['id'],
            'name': material['name'],
            'aliases': aliases,
          })
    return {
      'items': items[offset:offset + limit],
      'total': len(items),
      'limit': limit,
      'offset': offset,
    }

  @_database_errors
  def get_material(self, material_id: str) -> dict[str, Any]:
    with self.repository.connection() as connection:
      material = self._resolve_material(connection, material_id)
      aliases = [
        row['alias']
        for row in connection.execute(
          'SELECT alias FROM material_aliases WHERE material_id = ? '
          'ORDER BY normalized_alias',
          (material['id'],),
        )
      ]
      records = connection.execute(
        """
        SELECT r.id, rv.name, rv.model,
               json_extract(rv.metadata_json, '$.source') AS source
        FROM records AS r
        JOIN record_revisions AS rv
          ON rv.record_id = r.id AND rv.revision = r.current_revision
        WHERE r.material_id = ?
          AND r.deleted_at IS NULL
        ORDER BY rv.normalized_name, rv.model
        """,
        (material['id'],),
      ).fetchall()
    return {
      'id': material['id'],
      'name': material['name'],
      'aliases': aliases,
      'records': [dict(row) for row in records],
    }

  @_database_errors
  def list_records(
      self,
      query: str = '',
      model: str | None = None,
      material_id: str | None = None,
      limit: int = 100,
      offset: int = 0,
      physics: str | None = None,
  ) -> dict[str, Any]:
    needle = _normalized(query)
    with self.repository.connection() as connection:
      material = (
        self._resolve_material(connection, material_id)
        if material_id is not None else None
      )
      records = self._current_records(connection)
      materials = {
        row['id']: row['name']
        for row in connection.execute('SELECT id, name FROM materials')
      }
      aliases: dict[str, list[str]] = {}
      for row in connection.execute(
        'SELECT material_id, alias FROM material_aliases',
      ):
        aliases.setdefault(row['material_id'], []).append(row['alias'])
    items = []
    for record in records:
      if material is not None and record['material_id'] != material['id']:
        continue
      if model is not None and record['model'] != model:
        continue
      if physics is not None and record['physics'] != physics:
        continue
      metadata = json.loads(record['metadata_json'])
      searchable = _normalized(' '.join((
        record['material_id'],
        materials[record['material_id']],
        *aliases.get(record['material_id'], []),
        record['name'],
        record['model'],
        record['physics'],
        str(metadata.get('source') or ''),
      )))
      if needle and needle not in searchable:
        continue
      items.append({
        'material_id': record['material_id'],
        'material_name': materials[record['material_id']],
        'id': record['record_id'],
        'name': record['name'],
        'model': record['model'],
        'physics': record['physics'],
        'source': metadata.get('source'),
      })
    items.sort(key=lambda item: (
      item['material_id'].casefold(), item['name'].casefold(), item['model'],
    ))
    return {
      'items': items[offset:offset + limit],
      'total': len(items),
      'limit': limit,
      'offset': offset,
    }

  @_database_errors
  def list_admin_records(
      self, query: str = '', limit: int = 100,
  ) -> list[dict[str, Any]]:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
      raise InvalidQuery('record limit must be in the range 1..1000')
    needle = _normalized(query)
    with self.repository.connection() as connection:
      rows = connection.execute(
        """
        SELECT r.id, r.material_id, r.current_revision, r.created_at,
               r.deleted_at, m.name AS material_name, rv.name, rv.model,
               rv.physics, rv.metadata_json
        FROM records AS r
        JOIN materials AS m ON m.id = r.material_id
        JOIN record_revisions AS rv
          ON rv.record_id = r.id AND rv.revision = r.current_revision
        ORDER BY r.deleted_at IS NOT NULL, rv.normalized_name, r.id
        """,
      ).fetchall()
    items = []
    for row in rows:
      metadata = json.loads(row['metadata_json'])
      searchable = _normalized(' '.join((
        row['material_id'], row['material_name'], row['name'],
        row['model'], row['physics'], str(metadata.get('source') or ''),
      )))
      if needle and needle not in searchable:
        continue
      items.append({
        'id': row['id'],
        'material_id': row['material_id'],
        'material_name': row['material_name'],
        'name': row['name'],
        'model': row['model'],
        'physics': row['physics'],
        'source': metadata.get('source'),
        'revision': row['current_revision'],
        'created_at': row['created_at'],
        'deleted_at': row['deleted_at'],
      })
    return items[:limit]

  @_database_errors
  def soft_delete_record(
      self, record_id: str, *, actor_token_id: str,
  ) -> dict[str, Any]:
    try:
      canonical_id = str(uuid.UUID(record_id))
    except (ValueError, AttributeError) as error:
      raise InvalidQuery('record_id must be a UUID') from error
    deleted_at = _utc_now()
    with self.repository.transaction() as connection:
      record = connection.execute(
        'SELECT deleted_at FROM records WHERE id = ?', (canonical_id,),
      ).fetchone()
      if record is None:
        raise RecordNotFound(f'record {canonical_id!r} not found')
      if record['deleted_at'] is not None:
        raise RevisionConflict(f'record {canonical_id!r} is already archived')
      connection.execute(
        'UPDATE records SET deleted_at = ? WHERE id = ?',
        (deleted_at, canonical_id),
      )
      self._audit(
        connection, actor_token_id, 'record.archive', 'record',
        canonical_id, {'deleted_at': deleted_at},
      )
    return {'record_id': canonical_id, 'deleted_at': deleted_at}

  @_database_errors
  def restore_record(
      self, record_id: str, *, actor_token_id: str,
  ) -> dict[str, Any]:
    try:
      canonical_id = str(uuid.UUID(record_id))
    except (ValueError, AttributeError) as error:
      raise InvalidQuery('record_id must be a UUID') from error
    with self.repository.transaction() as connection:
      record = connection.execute(
        """
        SELECT r.deleted_at, r.material_id, rv.name, rv.physics, rv.model
        FROM records AS r
        JOIN record_revisions AS rv
          ON rv.record_id = r.id AND rv.revision = r.current_revision
        WHERE r.id = ?
        """,
        (canonical_id,),
      ).fetchone()
      if record is None:
        raise RecordNotFound(f'record {canonical_id!r} not found')
      if record['deleted_at'] is None:
        raise RevisionConflict(f'record {canonical_id!r} is not archived')
      self._check_selector_unique(
        connection,
        record['material_id'],
        {
          'name': record['name'],
          'physics': record['physics'],
          'model': record['model'],
        },
      )
      connection.execute(
        'UPDATE records SET deleted_at = NULL WHERE id = ?',
        (canonical_id,),
      )
      self._audit(
        connection, actor_token_id, 'record.restore', 'record',
        canonical_id, {},
      )
    return {'record_id': canonical_id, 'restored': True}

  def _revision_row(
      self,
      connection: sqlite3.Connection,
      record_id: str,
      revision: int | None = None,
  ) -> tuple[sqlite3.Row, sqlite3.Row]:
    try:
      canonical_id = str(uuid.UUID(record_id))
    except (ValueError, AttributeError) as error:
      raise InvalidQuery('record_id must be a UUID') from error
    record = connection.execute(
      'SELECT * FROM records WHERE id = ? AND deleted_at IS NULL',
      (canonical_id,),
    ).fetchone()
    if record is None:
      raise RecordNotFound(f'record {canonical_id!r} not found')
    selected_revision = record['current_revision'] if revision is None else revision
    if (
      isinstance(selected_revision, bool)
      or not isinstance(selected_revision, int)
      or selected_revision < 1
    ):
      raise InvalidQuery('revision must be a positive integer')
    row = connection.execute(
      """
      SELECT record_id, revision, name, normalized_name, physics, model,
             schema_version, data_json, metadata_json, payload_sha256,
             created_at
      FROM record_revisions WHERE record_id = ? AND revision = ?
      """,
      (canonical_id, selected_revision),
    ).fetchone()
    if row is None:
      raise RecordNotFound(
        f'revision {selected_revision} for record {canonical_id!r} not found',
      )
    return record, row

  @_database_errors
  def get_record(
      self,
      material_id: str,
      record_name: str,
      model: str | None = None,
      physics: str | None = None,
  ) -> dict[str, Any]:
    with self.repository.connection() as connection:
      material = self._resolve_material(connection, material_id)
      matches = connection.execute(
        """
        SELECT r.id AS record_id, r.current_revision, rv.*
        FROM records AS r
        JOIN record_revisions AS rv
          ON rv.record_id = r.id AND rv.revision = r.current_revision
        WHERE r.material_id = ? AND rv.normalized_name = ?
          AND r.deleted_at IS NULL
          AND (? IS NULL OR rv.model = ?)
          AND (? IS NULL OR rv.physics = ?)
        """,
        (
          material['id'], _normalized(record_name), model, model, physics,
          physics,
        ),
      ).fetchall()
      if not matches:
        raise RecordNotFound(
          f'record {material["id"]}/{record_name} not found',
        )
      if len(matches) > 1:
        raise AmbiguousRecord(
          f'record {material["id"]}/{record_name} is ambiguous; '
          'specify a model',
        )
      row = matches[0]
      return _payload_from_row(row)

  @_database_errors
  def get_record_by_id(
      self, record_id: str, revision: int | None = None,
  ) -> dict[str, Any]:
    with self.repository.connection() as connection:
      _, row = self._revision_row(connection, record_id, revision)
      return _payload_from_row(row)

  @_database_errors
  def get_record_envelope(
      self, record_id: str, revision: int | None = None,
  ) -> dict[str, Any]:
    with self.repository.connection() as connection:
      record, row = self._revision_row(connection, record_id, revision)
      return {
        'record': _payload_from_row(row),
        'revision': row['revision'],
        'current_revision': record['current_revision'],
        'created_at': row['created_at'],
        'payload_sha256': row['payload_sha256'],
      }

  @_database_errors
  def get_provenance(
      self, record_id: str, revision: int | None = None,
  ) -> dict[str, Any]:
    with self.repository.connection() as connection:
      record, row = self._revision_row(connection, record_id, revision)
      imported = connection.execute(
        """
        SELECT source_record_id, source_material_id, source_sha256
        FROM import_records WHERE record_id = ?
        ORDER BY import_key LIMIT 1
        """,
        (record['id'],),
      ).fetchone()
      derivation = connection.execute(
        """
        SELECT source_record_id, source_revision, operation, parameters_json
        FROM record_derivations WHERE record_id = ? AND revision = ?
        """,
        (record['id'], row['revision']),
      ).fetchone()
    return {
      'record_id': record['id'],
      'revision': row['revision'],
      'payload_sha256': row['payload_sha256'],
      'import': None if imported is None else dict(imported),
      'derivation': None if derivation is None else {
        'source_record_id': derivation['source_record_id'],
        'source_revision': derivation['source_revision'],
        'operation': derivation['operation'],
        'parameters': json.loads(derivation['parameters_json']),
      },
    }

  @_database_errors
  def get_revisions(self, record_id: str) -> list[dict[str, Any]]:
    with self.repository.connection() as connection:
      record, _ = self._revision_row(connection, record_id)
      rows = connection.execute(
        """
        SELECT revision, name, physics, model, payload_sha256, created_at
        FROM record_revisions WHERE record_id = ? ORDER BY revision DESC
        """,
        (record['id'],),
      ).fetchall()
    return [dict(row) for row in rows]

  def evaluate_record(
      self,
      material_id: str,
      record_name: str,
      model: str,
      coordinates: list[int | float],
      unit: str,
      parameter: str,
      interpolation: str = 'linear',
  ) -> dict[str, Any]:
    record = self.get_record(material_id, record_name, model)
    values = _evaluate_payload(
      record, coordinates, unit, parameter, interpolation,
    )
    return {
      'material_id': self.get_material(material_id)['id'],
      'record_name': record['name'],
      'model': record['model'],
      'parameter': parameter,
      'unit': unit,
      'coordinates': [float(value) for value in coordinates],
      'values': [
        {'real': value.real, 'imag': value.imag} for value in values
      ],
    }

  def evaluate_record_by_id(
      self,
      record_id: str,
      coordinates: list[int | float],
      unit: str,
      parameter: str,
      interpolation: str = 'linear',
      revision: int | None = None,
  ) -> dict[str, Any]:
    record = self.get_record_by_id(record_id, revision)
    values = _evaluate_payload(
      record, coordinates, unit, parameter, interpolation,
    )
    return {
      'record_id': record['id'],
      'revision': revision or self.get_record_envelope(record_id)['revision'],
      'record_name': record['name'],
      'model': record['model'],
      'parameter': parameter,
      'unit': unit,
      'coordinates': [float(value) for value in coordinates],
      'values': [
        {'real': value.real, 'imag': value.imag} for value in values
      ],
    }

  def resample_record(
      self,
      record_id: str,
      coordinates: list[int | float],
      unit: str,
      parameter: str,
      interpolation: str = 'linear',
      range_policy: str = 'clip',
      revision: int | None = None,
  ) -> dict[str, Any]:
    envelope = self.get_record_envelope(record_id, revision)
    source = envelope['record']
    values = _evaluate_payload(
      source, coordinates, unit, parameter, interpolation,
      range_policy=range_policy,
    )
    identifier = str(uuid.uuid4())
    record = {
      'schema_version': _RECORD_SCHEMA_VERSION,
      'physics': 'nlo' if parameter == 'n2' else source['physics'],
      'model': 'tabulated',
      'name': f'{source["name"]} (resampled)',
      'id': identifier,
      'data': {
        'unit': unit,
        'type': parameter,
        'f': [float(value) for value in coordinates],
        're': [value.real for value in values],
        'im': [value.imag for value in values],
      },
      'metadata': {
        'derivation': {
          'source_record_id': source['id'],
          'source_revision': envelope['revision'],
        },
      },
    }
    return {
      'record': record,
      'source': {
        'record_id': source['id'],
        'revision': envelope['revision'],
        'payload_sha256': envelope['payload_sha256'],
      },
      'operation': {
        'unit': unit,
        'parameter': parameter,
        'interpolation': interpolation,
        'range_policy': range_policy,
        'coordinates': [float(value) for value in coordinates],
        'xmdm_version': _XMDM_VERSION,
        'warnings': _range_warnings(
          source, coordinates, unit, range_policy,
        ),
      },
    }

  def validate_record(
      self, record_id: str, revision: int | None = None,
  ) -> dict[str, Any]:
    try:
      record = self.get_record_by_id(record_id, revision)
      validate_record_data(record)
      _canonical_json(record)
    except (InvalidQuery, RecordNotFound):
      raise
    except (KeyError, TypeError, ValueError, OverflowError) as error:
      return {'valid': False, 'errors': [str(error)], 'warnings': []}
    return {'valid': True, 'errors': [], 'warnings': []}

  def _check_selector_unique(
      self,
      connection: sqlite3.Connection,
      material_id: str,
      payload: dict[str, Any],
      *,
      exclude_record_id: str | None = None,
  ) -> None:
    duplicate = connection.execute(
      """
      SELECT r.id
      FROM records AS r
      JOIN record_revisions AS rv
        ON rv.record_id = r.id AND rv.revision = r.current_revision
      WHERE r.material_id = ? AND rv.normalized_name = ?
        AND r.deleted_at IS NULL
        AND rv.physics = ? AND rv.model = ?
        AND (? IS NULL OR r.id != ?)
      LIMIT 1
      """,
      (
        material_id, _normalized(payload['name']), payload['physics'],
        payload['model'], exclude_record_id, exclude_record_id,
      ),
    ).fetchone()
    if duplicate is not None:
      raise InvalidQuery(
        'a current record with the same material, name, physics, and model '
        'already exists',
      )

  def _insert_revision(
      self,
      connection: sqlite3.Connection,
      record_id: str,
      revision: int,
      payload: dict[str, Any],
      *,
      derivation: dict[str, Any] | None = None,
  ) -> str:
    stored = {**payload, 'id': record_id}
    digest = _sha256(stored)
    now = _utc_now()
    connection.execute(
      """
      INSERT INTO record_revisions (
        record_id, revision, name, normalized_name, physics, model,
        schema_version, data_json, metadata_json, payload_sha256, created_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      """,
      (
        record_id, revision, payload['name'], _normalized(payload['name']),
        payload['physics'], payload['model'], payload['schema_version'],
        _canonical_json(payload['data']), _canonical_json(payload['metadata']),
        digest, now,
      ),
    )
    if derivation is not None:
      source_id = str(uuid.UUID(derivation['source_record_id']))
      source_revision = derivation['source_revision']
      connection.execute(
        """
        INSERT INTO record_derivations (
          record_id, revision, source_record_id, source_revision,
          operation, parameters_json
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
          record_id, revision, source_id, source_revision,
          derivation['operation'], _canonical_json(derivation['parameters']),
        ),
      )
    return digest

  def _check_derivation(
      self, connection: sqlite3.Connection, derivation: dict[str, Any] | None,
  ) -> None:
    if derivation is None:
      return
    if not isinstance(derivation, dict):
      raise InvalidQuery('derivation must be an object')
    try:
      source_id = str(uuid.UUID(derivation['source_record_id']))
      source_revision = derivation['source_revision']
      operation = derivation['operation']
      parameters = derivation['parameters']
    except (KeyError, TypeError, ValueError, AttributeError) as error:
      raise InvalidQuery('invalid derivation information') from error
    if (
      isinstance(source_revision, bool)
      or not isinstance(source_revision, int)
      or source_revision < 1
      or not isinstance(operation, str)
      or not operation.strip()
      or not isinstance(parameters, dict)
    ):
      raise InvalidQuery('invalid derivation information')
    if connection.execute(
      'SELECT 1 FROM record_revisions WHERE record_id = ? AND revision = ?',
      (source_id, source_revision),
    ).fetchone() is None:
      raise RecordNotFound('derivation source revision was not found')
    try:
      _canonical_json(parameters)
    except (TypeError, ValueError, OverflowError) as error:
      raise InvalidQuery('derivation parameters must be finite JSON data') from error
    derivation.update({
      'source_record_id': source_id,
      'source_revision': source_revision,
      'operation': operation,
      'parameters': parameters,
    })

  @_database_errors
  def create_record(
      self,
      material_id: str,
      payload: dict[str, Any],
      *,
      derivation: dict[str, Any] | None = None,
      actor_token_id: str | None = None,
  ) -> dict[str, Any]:
    payload = _validate_payload(payload)
    record_id = str(uuid.uuid4())
    now = _utc_now()
    with self.repository.transaction() as connection:
      material = self._resolve_material(connection, material_id)
      self._check_selector_unique(connection, material['id'], payload)
      self._check_derivation(connection, derivation)
      connection.execute(
        """
        INSERT INTO records (id, material_id, current_revision, created_at)
        VALUES (?, ?, 1, ?)
        """,
        (record_id, material['id'], now),
      )
      digest = self._insert_revision(
        connection, record_id, 1, payload, derivation=derivation,
      )
      self._audit(
        connection, actor_token_id, 'record.create', 'record', record_id,
        {'revision': 1, 'payload_sha256': digest},
      )
    return {
      'record_id': record_id,
      'revision': 1,
      'payload_sha256': digest,
    }

  @_database_errors
  def replace_record(
      self,
      record_id: str,
      payload: dict[str, Any],
      expected_revision: int,
      *,
      derivation: dict[str, Any] | None = None,
      actor_token_id: str | None = None,
  ) -> dict[str, Any]:
    payload = _validate_payload(payload)
    try:
      canonical_id = str(uuid.UUID(record_id))
    except (ValueError, AttributeError) as error:
      raise InvalidQuery('record_id must be a UUID') from error
    if (
      isinstance(expected_revision, bool)
      or not isinstance(expected_revision, int)
      or expected_revision < 1
    ):
      raise InvalidQuery('expected_revision must be a positive integer')
    with self.repository.transaction() as connection:
      record = connection.execute(
        'SELECT * FROM records WHERE id = ?', (canonical_id,),
      ).fetchone()
      if record is None:
        raise RecordNotFound(f'record {canonical_id!r} not found')
      if record['current_revision'] != expected_revision:
        raise RevisionConflict(
          f'current revision is {record["current_revision"]}, not '
          f'{expected_revision}',
        )
      self._check_selector_unique(
        connection, record['material_id'], payload,
        exclude_record_id=canonical_id,
      )
      self._check_derivation(connection, derivation)
      revision = expected_revision + 1
      digest = self._insert_revision(
        connection, canonical_id, revision, payload, derivation=derivation,
      )
      connection.execute(
        'UPDATE records SET current_revision = ? WHERE id = ?',
        (revision, canonical_id),
      )
      self._audit(
        connection, actor_token_id, 'record.revise', 'record', canonical_id,
        {'revision': revision, 'payload_sha256': digest},
      )
    return {
      'record_id': canonical_id,
      'revision': revision,
      'payload_sha256': digest,
    }

  @_database_errors
  def stage_submission(
      self,
      material_id: str | None,
      payload: dict[str, Any],
      *,
      actor_token_id: str,
      material_name: str | None = None,
      derivation: dict[str, Any] | None = None,
      target_record_id: str | None = None,
      expected_revision: int | None = None,
  ) -> dict[str, Any]:
    validated_payload = _validate_payload(payload)
    new_material = None
    if material_name is not None:
      if target_record_id is not None:
        raise InvalidQuery('a revision cannot create a new material')
      if (
        not isinstance(material_id, str) or not material_id.strip()
        or material_id != material_id.strip() or not _safe_material_id(material_id)
      ):
        raise InvalidQuery('new material_id must be a safe directory name')
      if not isinstance(material_name, str) or not material_name.strip():
        raise InvalidQuery('material_name must be a non-empty string')
      new_material = {'id': material_id, 'name': material_name.strip()}
    if not isinstance(actor_token_id, str) or not actor_token_id:
      raise InvalidQuery('a submitting token is required')
    if (target_record_id is None) != (expected_revision is None):
      raise InvalidQuery(
        'target_record_id and expected_revision must be provided together',
      )
    canonical_target_id = None
    if target_record_id is not None:
      try:
        canonical_target_id = str(uuid.UUID(target_record_id))
      except (ValueError, AttributeError) as error:
        raise InvalidQuery('target_record_id must be a UUID') from error
      if (
        isinstance(expected_revision, bool)
        or not isinstance(expected_revision, int)
        or expected_revision < 1
      ):
        raise InvalidQuery('expected_revision must be a positive integer')
    validated_derivation = None
    if derivation is not None:
      if not isinstance(derivation, dict):
        raise InvalidQuery('derivation must be an object')
      validated_derivation = dict(derivation)

    submission_id = str(uuid.uuid4())
    submitted_at = _utc_now()
    with self.repository.transaction() as connection:
      if canonical_target_id is None:
        if material_id is None:
          raise InvalidQuery('material_id is required for a new submission')
        if new_material is not None:
          if self._material_matches(connection, material_id):
            raise InvalidQuery('material already exists; choose the existing material')
          if self._material_matches(connection, new_material['name']):
            raise InvalidQuery('material name already exists; choose the existing material')
          material = {'id': material_id}
        else:
          material = self._resolve_material(connection, material_id)
          self._check_selector_unique(connection, material['id'], validated_payload)
      else:
        target = connection.execute(
          'SELECT material_id, current_revision, deleted_at '
          'FROM records WHERE id = ?',
          (canonical_target_id,),
        ).fetchone()
        if target is None:
          raise RecordNotFound(f'record {canonical_target_id!r} not found')
        if target['deleted_at'] is not None:
          raise InvalidQuery('cannot submit a revision for an archived record')
        material = connection.execute(
          'SELECT id FROM materials WHERE id = ?', (target['material_id'],),
        ).fetchone()
        if material is None:
          raise ValueError('record refers to a missing material')
        if (
          material_id is not None
          and self._resolve_material(connection, material_id)['id'] != material['id']
        ):
          raise InvalidQuery('revision submission material cannot be changed')
        if target['current_revision'] != expected_revision:
          raise RevisionConflict(
            f'current revision is {target["current_revision"]}, not '
            f'{expected_revision}',
          )
        self._check_selector_unique(
          connection, material['id'], validated_payload,
          exclude_record_id=canonical_target_id,
        )
      if validated_derivation is not None:
        self._check_derivation(connection, validated_derivation)
      connection.execute(
        """
        INSERT INTO pending_submissions (
          submission_id, material_id, new_material_json, target_record_id, expected_revision,
          payload_json, derivation_json, submitted_by_token_id, submitted_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
          submission_id, material['id'] if new_material is None else None,
          None if new_material is None else _canonical_json(new_material), canonical_target_id,
          expected_revision, _canonical_json(validated_payload),
          None if validated_derivation is None
          else _canonical_json(validated_derivation),
          actor_token_id, submitted_at,
        ),
      )
      self._audit(
        connection, actor_token_id, 'submission.submit', 'submission',
        submission_id, {
          'material_id': material['id'],
          'target_record_id': canonical_target_id,
          'payload_sha256': _sha256(validated_payload),
        },
      )
    return {
      'submission_id': submission_id,
      'status': 'pending',
      'submitted_at': submitted_at,
      'payload_sha256': _sha256(validated_payload),
    }

  @_database_errors
  def list_submissions(
      self, status: str = 'pending', limit: int = 100,
  ) -> list[dict[str, Any]]:
    if status not in ('pending', 'accepted', 'rejected', 'all'):
      raise InvalidQuery('status must be pending, accepted, rejected, or all')
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
      raise InvalidQuery('submission limit must be in the range 1..1000')
    where = '' if status == 'all' else 'WHERE p.status = ?'
    parameters: tuple[Any, ...] = (limit,) if status == 'all' else (status, limit)
    with self.repository.connection() as connection:
      rows = connection.execute(
        f"""
        SELECT p.*, COALESCE(m.name, json_extract(p.new_material_json, '$.name')) AS material_name,
               submitter.name AS submitter_name,
               reviewer.name AS reviewer_name
        FROM pending_submissions AS p
        LEFT JOIN materials AS m ON m.id = p.material_id
        JOIN api_tokens AS submitter
          ON submitter.token_id = p.submitted_by_token_id
        LEFT JOIN api_tokens AS reviewer
          ON reviewer.token_id = p.reviewed_by_token_id
        {where}
        ORDER BY p.submitted_at DESC
        LIMIT ?
        """,
        parameters,
      ).fetchall()
    return [{
      'submission_id': row['submission_id'],
      'material_id': row['material_id'] or json.loads(row['new_material_json'])['id'],
      'material_name': row['material_name'],
      'new_material': row['new_material_json'] is not None,
      'target_record_id': row['target_record_id'],
      'expected_revision': row['expected_revision'],
      'payload': json.loads(row['payload_json']),
      'derivation': (
        None if row['derivation_json'] is None
        else json.loads(row['derivation_json'])
      ),
      'submitted_by_token_id': row['submitted_by_token_id'],
      'submitter_name': row['submitter_name'],
      'submitted_at': row['submitted_at'],
      'status': row['status'],
      'reviewed_by_token_id': row['reviewed_by_token_id'],
      'reviewer_name': row['reviewer_name'],
      'reviewed_at': row['reviewed_at'],
      'review_note': row['review_note'],
      'accepted_record_id': row['accepted_record_id'],
      'accepted_revision': row['accepted_revision'],
    } for row in rows]

  @_database_errors
  def review_submission(
      self,
      submission_id: str,
      decision: str,
      *,
      actor_token_id: str,
      note: str | None = None,
  ) -> dict[str, Any]:
    if decision not in ('approve', 'reject'):
      raise InvalidQuery("decision must be 'approve' or 'reject'")
    if note is not None and (not isinstance(note, str) or len(note) > 2000):
      raise InvalidQuery('review note must be a string of at most 2000 characters')
    try:
      canonical_id = str(uuid.UUID(submission_id))
    except (ValueError, AttributeError) as error:
      raise InvalidQuery('submission_id must be a UUID') from error

    reviewed_at = _utc_now()
    with self.repository.transaction() as connection:
      submission = connection.execute(
        'SELECT * FROM pending_submissions WHERE submission_id = ?',
        (canonical_id,),
      ).fetchone()
      if submission is None:
        raise RecordNotFound(f'submission {canonical_id!r} not found')
      if submission['status'] != 'pending':
        raise RevisionConflict(
          f'submission has already been {submission["status"]}',
        )

      accepted_record_id = None
      accepted_revision = None
      if decision == 'approve':
        payload = _validate_payload(json.loads(submission['payload_json']))
        derivation = (
          None if submission['derivation_json'] is None
          else json.loads(submission['derivation_json'])
        )
        if derivation is not None:
          self._check_derivation(connection, derivation)
        material_id = submission['material_id']
        if submission['new_material_json'] is not None:
          proposed = json.loads(submission['new_material_json'])
          matches = self._material_matches(connection, proposed['id'])
          if matches:
            if (
              len(matches) != 1 or matches[0]['id'] != proposed['id']
              or _normalized(matches[0]['name']) != _normalized(proposed['name'])
            ):
              raise RevisionConflict('new material conflicts with an existing material')
          else:
            if self._material_matches(connection, proposed['name']):
              raise RevisionConflict('new material name conflicts with an existing material')
            connection.execute(
              'INSERT INTO materials (id, name, normalized_id, normalized_name, created_at) '
              'VALUES (?, ?, ?, ?, ?)',
              (proposed['id'], proposed['name'], _normalized(proposed['id']),
               _normalized(proposed['name']), reviewed_at),
            )
            self._audit(
              connection, actor_token_id, 'material.create', 'material',
              proposed['id'], {'name': proposed['name']},
            )
          material_id = proposed['id']
        target_id = submission['target_record_id']
        if target_id is None:
          self._check_selector_unique(
            connection, material_id, payload,
          )
          accepted_record_id = str(uuid.uuid4())
          created_at = _utc_now()
          connection.execute(
            """
            INSERT INTO records (id, material_id, current_revision, created_at)
            VALUES (?, ?, 1, ?)
            """,
            (accepted_record_id, material_id, created_at),
          )
          accepted_revision = 1
        else:
          record = connection.execute(
            'SELECT material_id, current_revision, deleted_at '
            'FROM records WHERE id = ?',
            (target_id,),
          ).fetchone()
          if record is None:
            raise RecordNotFound(f'record {target_id!r} not found')
          if record['deleted_at'] is not None:
            raise RevisionConflict(
              'record was archived after this revision was submitted; '
              'the submission remains pending',
            )
          if record['current_revision'] != submission['expected_revision']:
            raise RevisionConflict(
              'record changed after this revision was submitted; '
              'the submission remains pending',
            )
          self._check_selector_unique(
            connection, record['material_id'], payload,
            exclude_record_id=target_id,
          )
          accepted_record_id = target_id
          accepted_revision = submission['expected_revision'] + 1

        digest = self._insert_revision(
          connection, accepted_record_id, accepted_revision, payload,
          derivation=derivation,
        )
        if submission['target_record_id'] is not None:
          connection.execute(
            'UPDATE records SET current_revision = ? WHERE id = ?',
            (accepted_revision, accepted_record_id),
          )
        self._audit(
          connection, actor_token_id,
          'record.create' if accepted_revision == 1 else 'record.revise',
          'record', accepted_record_id,
          {'revision': accepted_revision, 'payload_sha256': digest},
        )

      status = 'accepted' if decision == 'approve' else 'rejected'
      connection.execute(
        """
        UPDATE pending_submissions
        SET status = ?, reviewed_by_token_id = ?, reviewed_at = ?,
            review_note = ?, accepted_record_id = ?, accepted_revision = ?
        WHERE submission_id = ? AND status = 'pending'
        """,
        (
          status, actor_token_id, reviewed_at, note, accepted_record_id,
          accepted_revision, canonical_id,
        ),
      )
      self._audit(
        connection, actor_token_id, f'submission.{decision}', 'submission',
        canonical_id, {
          'accepted_record_id': accepted_record_id,
          'accepted_revision': accepted_revision,
          'note': note,
        },
      )
    return {
      'submission_id': canonical_id,
      'status': status,
      'reviewed_at': reviewed_at,
      'record_id': accepted_record_id,
      'revision': accepted_revision,
    }

  def _audit(
      self,
      connection: sqlite3.Connection,
      actor_token_id: str | None,
      action: str,
      object_type: str,
      object_id: str,
      details: dict[str, Any],
  ) -> None:
    connection.execute(
      """
      INSERT INTO audit_events (
        actor_token_id, action, object_type, object_id, details_json, created_at
      ) VALUES (?, ?, ?, ?, ?, ?)
      """,
      (
        actor_token_id, action, object_type, object_id,
        _canonical_json(details), _utc_now(),
      ),
    )

  @_database_errors
  def create_token(
      self,
      name: str,
      scopes: list[str],
      expires_at: str | None = None,
      *,
      actor_token_id: str | None = None,
  ) -> dict[str, Any]:
    if not isinstance(name, str) or not name.strip():
      raise InvalidQuery('token name must be non-empty')
    if not scopes or any(scope not in _ALLOWED_SCOPES for scope in scopes):
      raise InvalidQuery(
        'token scopes must contain records:write and/or tokens:admin',
      )
    token_id = str(uuid.uuid4())
    secret = f'xmdm_{os.urandom(32).hex()}'
    digest = hashlib.sha256(secret.encode('utf-8')).hexdigest()
    now = datetime.now(UTC)
    if expires_at is not None:
      try:
        expiry = datetime.fromisoformat(expires_at)
      except ValueError as error:
        raise InvalidQuery('expires_at must be an ISO 8601 timestamp') from error
      if expiry.tzinfo is None or expiry <= now:
        raise InvalidQuery('expires_at must be a future timezone-aware timestamp')
      expires_at = expiry.astimezone(UTC).isoformat()
    with self.repository.transaction() as connection:
      connection.execute(
        """
        INSERT INTO api_tokens (
          token_id, token_hash, name, scopes_json, created_at, expires_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (token_id, digest, name.strip(), _canonical_json(sorted(set(scopes))),
         now.isoformat(), expires_at),
      )
      self._audit(
        connection, actor_token_id, 'token.create', 'token', token_id,
        {'name': name.strip(), 'scopes': sorted(set(scopes)),
         'expires_at': expires_at},
      )
    return {
      'token_id': token_id,
      'name': name.strip(),
      'scopes': sorted(set(scopes)),
      'created_at': now.isoformat(),
      'expires_at': expires_at,
      'token': secret,
    }

  @_database_errors
  def authenticate_token(self, secret: str) -> dict[str, Any] | None:
    if not isinstance(secret, str) or not secret.startswith('xmdm_'):
      return None
    digest = hashlib.sha256(secret.encode('utf-8')).hexdigest()
    with self.repository.connection() as connection:
      row = connection.execute(
        """
        SELECT token_id, name, scopes_json, created_at, expires_at, revoked_at
        FROM api_tokens WHERE token_hash = ?
        """,
        (digest,),
      ).fetchone()
    if row is None or row['revoked_at'] is not None:
      return None
    if row['expires_at'] is not None and datetime.fromisoformat(
      row['expires_at'],
    ) <= datetime.now(UTC):
      return None
    return {
      'token_id': row['token_id'],
      'name': row['name'],
      'scopes': json.loads(row['scopes_json']),
      'created_at': row['created_at'],
      'expires_at': row['expires_at'],
    }

  @_database_errors
  def list_tokens(self) -> list[dict[str, Any]]:
    with self.repository.connection() as connection:
      rows = connection.execute(
        """
        SELECT token_id, name, scopes_json, created_at, expires_at, revoked_at
        FROM api_tokens ORDER BY created_at DESC
        """,
      ).fetchall()
    return [{
      'token_id': row['token_id'],
      'name': row['name'],
      'scopes': json.loads(row['scopes_json']),
      'created_at': row['created_at'],
      'expires_at': row['expires_at'],
      'revoked_at': row['revoked_at'],
    } for row in rows]

  @_database_errors
  def list_audit_events(self, limit: int = 100) -> list[dict[str, Any]]:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
      raise InvalidQuery('audit limit must be in the range 1..1000')
    with self.repository.connection() as connection:
      rows = connection.execute(
        """
        SELECT event_id, actor_token_id, action, object_type, object_id,
               details_json, created_at
        FROM audit_events ORDER BY event_id DESC LIMIT ?
        """,
        (limit,),
      ).fetchall()
    return [{
      'event_id': row['event_id'],
      'actor_token_id': row['actor_token_id'],
      'action': row['action'],
      'object_type': row['object_type'],
      'object_id': row['object_id'],
      'details': json.loads(row['details_json']),
      'created_at': row['created_at'],
    } for row in rows]

  @_database_errors
  def revoke_token(
      self, token_id: str, *, actor_token_id: str | None = None,
  ) -> None:
    try:
      canonical_id = str(uuid.UUID(token_id))
    except (ValueError, AttributeError) as error:
      raise InvalidQuery('token_id must be a UUID') from error
    with self.repository.transaction() as connection:
      cursor = connection.execute(
        'UPDATE api_tokens SET revoked_at = ? '
        'WHERE token_id = ? AND revoked_at IS NULL',
        (_utc_now(), canonical_id),
      )
      if cursor.rowcount == 0:
        raise RecordNotFound(f'active token {canonical_id!r} not found')
      self._audit(
        connection, actor_token_id, 'token.revoke', 'token', canonical_id, {},
      )

  @_database_errors
  def import_json(
      self,
      source: str | Path,
      *,
      namespace: str | None = None,
      on_change: str = 'error',
  ) -> dict[str, int]:
    if on_change not in ('error', 'new_revision'):
      raise InvalidQuery("on_change must be 'error' or 'new_revision'")
    root, index = load_index(source)
    import_namespace = namespace or str(root.resolve())
    staged: list[tuple[str, dict[str, Any], str, str]] = []
    for material_id, material in index['materials'].items():
      if not _safe_material_id(material_id):
        raise InvalidQuery(f'invalid material ID in import: {material_id!r}')
      for reference in material['records']:
        record, _ = load_record(
          f'{material_id}/{reference["name"]}', reference['model'], root,
        )
        validate_record_data(record)
        digest = _sha256(record)
        import_key = hashlib.sha256(
          f'{import_namespace}\0{material_id}\0{record["id"]}'.encode('utf-8'),
        ).hexdigest()
        staged.append((material_id, record, import_key, digest))

    created = revised = unchanged = 0
    with self.repository.transaction() as connection:
      for material_id, material in index['materials'].items():
        existing = connection.execute(
          'SELECT id, name FROM materials WHERE normalized_id = ?',
          (_normalized(material_id),),
        ).fetchone()
        if existing is None:
          connection.execute(
            """
            INSERT INTO materials
              (id, name, normalized_id, normalized_name, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
              material_id, material['name'], _normalized(material_id),
              _normalized(material['name']), _utc_now(),
            ),
          )
          canonical_material_id = material_id
        else:
          canonical_material_id = existing['id']
        for alias in material.get('aliases', []):
          if alias.strip():
            connection.execute(
              """
              INSERT OR IGNORE INTO material_aliases
                (material_id, alias, normalized_alias) VALUES (?, ?, ?)
              """,
              (canonical_material_id, alias, _normalized(alias)),
            )

      for material_id, original, import_key, source_hash in staged:
        mapping = connection.execute(
          'SELECT record_id, source_sha256 FROM import_records '
          'WHERE import_key = ?',
          (import_key,),
        ).fetchone()
        payload = _validate_payload(original)
        if mapping is not None:
          if mapping['source_sha256'] == source_hash:
            unchanged += 1
            continue
          if on_change != 'new_revision':
            raise InvalidQuery(
              'imported payload changed; choose on_change="new_revision" '
              'to append a revision',
            )
          server_id = mapping['record_id']
          current = connection.execute(
            'SELECT current_revision FROM records WHERE id = ?',
            (server_id,),
          ).fetchone()
          if current is None:
            raise ValueError('import mapping points to a missing record')
          self._check_selector_unique(
            connection,
            connection.execute(
              'SELECT material_id FROM records WHERE id = ?', (server_id,),
            ).fetchone()['material_id'],
            payload,
            exclude_record_id=server_id,
          )
          next_revision = current['current_revision'] + 1
          self._insert_revision(connection, server_id, next_revision, payload)
          connection.execute(
            'UPDATE records SET current_revision = ? WHERE id = ?',
            (next_revision, server_id),
          )
          connection.execute(
            'UPDATE import_records SET source_sha256 = ? WHERE import_key = ?',
            (source_hash, import_key),
          )
          revised += 1
          continue

        source_id = str(uuid.UUID(original['id']))
        collision = connection.execute(
          'SELECT id FROM records WHERE id = ?', (source_id,),
        ).fetchone()
        server_id = source_id if collision is None else str(uuid.uuid4())
        actual_material = connection.execute(
          'SELECT id FROM materials WHERE normalized_id = ?',
          (_normalized(material_id),),
        ).fetchone()['id']
        self._check_selector_unique(connection, actual_material, payload)
        connection.execute(
          """
          INSERT INTO records (id, material_id, current_revision, created_at)
          VALUES (?, ?, 1, ?)
          """,
          (server_id, actual_material, _utc_now()),
        )
        self._insert_revision(connection, server_id, 1, payload)
        connection.execute(
          """
          INSERT INTO import_records (
            import_key, source_record_id, source_material_id, record_id,
            source_sha256
          ) VALUES (?, ?, ?, ?, ?)
          """,
          (import_key, original['id'], material_id, server_id, source_hash),
        )
        created += 1
    return {'created': created, 'revised': revised, 'unchanged': unchanged}

  @_database_errors
  def export_json(self, destination: str | Path) -> Path:
    target = Path(destination).expanduser()
    if target.exists():
      raise FileExistsError(f'export destination already exists: {target}')
    if not target.parent.is_dir():
      raise FileNotFoundError(f'export parent directory does not exist: {target.parent}')
    with tempfile.TemporaryDirectory(
      dir=target.parent, prefix=f'.{target.name}.',
    ) as temporary:
      staging = Path(temporary) / 'database'
      staging.mkdir()
      with self.repository.connection() as connection:
        materials = connection.execute(
          'SELECT id, name FROM materials ORDER BY id COLLATE NOCASE',
        ).fetchall()
        entries: dict[str, Any] = {}
        for material in materials:
          aliases = [
            row['alias']
            for row in connection.execute(
              'SELECT alias FROM material_aliases WHERE material_id = ? '
              'ORDER BY normalized_alias',
              (material['id'],),
            )
          ]
          records = connection.execute(
            """
            SELECT r.id AS record_id, rv.*
            FROM records AS r JOIN record_revisions AS rv
              ON rv.record_id = r.id AND rv.revision = r.current_revision
            WHERE r.material_id = ? AND r.deleted_at IS NULL
            ORDER BY rv.normalized_name, rv.model
            """,
            (material['id'],),
          ).fetchall()
          references = []
          if not _safe_material_id(material['id']):
            raise ValueError(f'unsafe material ID in database: {material["id"]!r}')
          material_dir = staging / material['id']
          material_dir.mkdir()
          for row in records:
            payload = _payload_from_row(row)
            relative_path = f'{material["id"]}/{row["record_id"]}.json'
            (staging / relative_path).write_text(
              json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False)
              + '\n',
              encoding='utf-8',
            )
            references.append({
              'id': row['record_id'],
              'physics': row['physics'],
              'model': row['model'],
              'name': row['name'],
              'path': relative_path,
            })
          entries[material['id']] = {
            'name': material['name'],
            'aliases': aliases,
            'records': references,
          }
      (staging / 'index.json').write_text(
        json.dumps(
          {'schema_version': _RECORD_SCHEMA_VERSION, 'materials': entries},
          indent=2,
          ensure_ascii=False,
          allow_nan=False,
        ) + '\n',
        encoding='utf-8',
      )
      os.rename(staging, target)
    return target

  @_database_errors
  def verify(self) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    checked = 0
    with self.repository.connection() as connection:
      integrity = connection.execute('PRAGMA integrity_check').fetchone()[0]
      if integrity != 'ok':
        errors.append({'selector': '<database>', 'error': integrity})
      foreign_key_errors = connection.execute('PRAGMA foreign_key_check').fetchall()
      for error in foreign_key_errors:
        errors.append({
          'selector': '<database>',
          'error': f'foreign key violation in {error["table"]}',
        })
      records = connection.execute(
        """
        SELECT r.material_id, rv.*
        FROM records AS r
        JOIN record_revisions AS rv
          ON rv.record_id = r.id AND rv.revision = r.current_revision
        ORDER BY r.material_id, rv.normalized_name
        """,
      ).fetchall()
    for row in records:
      checked += 1
      selector = f'{row["material_id"]}/{row["name"]}'
      try:
        payload = _payload_from_row(row)
        validate_record_data(payload)
        if _sha256(payload) != row['payload_sha256']:
          raise ValueError('payload SHA-256 does not match stored record')
        _canonical_json(payload)
      except (KeyError, TypeError, ValueError, OverflowError) as error:
        errors.append({'selector': selector, 'error': str(error)})
    return {'valid': not errors, 'checked': checked, 'errors': errors}

  @_database_errors
  def backup(self, destination: str | Path) -> Path:
    target = Path(destination).expanduser()
    if target.exists():
      raise FileExistsError(f'backup destination already exists: {target}')
    if not target.parent.is_dir():
      raise FileNotFoundError(f'backup parent directory does not exist: {target.parent}')
    with target.open('xb'):
      pass
    try:
      with self.repository.connection() as source:
        with sqlite3.connect(target) as backup:
          source.backup(backup)
    except Exception:
      target.unlink(missing_ok=True)
      raise
    return target

  @_database_errors
  def export_record(
      self, record_id: str, revision: int | None, format_name: str,
  ) -> tuple[str, str]:
    record = self.get_record_by_id(record_id, revision)
    if format_name in ('json', 'yaml'):
      return _canonical_json(record) + '\n', (
        'application/json' if format_name == 'json' else 'application/yaml'
      )
    if format_name != 'csv':
      raise InvalidQuery(f'unsupported export format: {format_name!r}')
    if record['model'] != 'tabulated':
      raise InvalidQuery('CSV export is only available for tabulated records')
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow((
      f'coordinate ({record["data"]["unit"]})',
      f'real ({record["data"]["type"]})',
      f'imaginary ({record["data"]["type"]})',
    ))
    writer.writerows(zip(
      record['data']['f'], record['data']['re'], record['data']['im'],
    ))
    return output.getvalue(), 'text/csv; charset=utf-8'
