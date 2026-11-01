"""Transport-independent read-only operations over an XMDM database."""

from __future__ import annotations

import json
import hashlib
import math
import os
from pathlib import Path
import unicodedata
from typing import Any
import uuid

import numpy as np
from xmdm import (
  Cauchy,
  Drude,
  Lorentz,
  Material,
  RefractiveIndexFormula,
  Sellmeier,
  database_directory,
  load_index,
  load_record,
  validate_record_data,
)
from ..db import SQLiteRepository
from ..db.catalog import SQLiteCatalog, _validate_evaluation_physics
from ..errors import (
  AmbiguousRecord,
  DatabaseUnavailable,
  InvalidQuery,
  RecordNotFound,
)

MODELS = (
  'tabulated', 'drude', 'lorentz', 'sellmeier', 'cauchy', 'rii_formula',
)
UNITS = ('m', 'nm', 'um', 'Hz', 'GHz', 'THz', 'cm-1', 'eV')
MAX_PAGE_SIZE = 1000
MAX_EVALUATION_POINTS = 10000

_MODEL_TYPES = {
  'drude': Drude,
  'lorentz': Lorentz,
  'sellmeier': Sellmeier,
  'cauchy': Cauchy,
  'rii_formula': RefractiveIndexFormula,
}


def _normalized(value: str) -> str:
  return ''.join(
    character
    for character in unicodedata.normalize('NFKD', value).casefold()
    if not unicodedata.combining(character)
  )


def _validate_pagination(limit: int, offset: int) -> None:
  if not 1 <= limit <= MAX_PAGE_SIZE:
    raise InvalidQuery(f'limit must be in the range 1..{MAX_PAGE_SIZE}')
  if offset < 0:
    raise InvalidQuery('offset must be nonnegative')


def _is_finite_number(value: object) -> bool:
  if isinstance(value, bool) or not isinstance(value, (int, float)):
    return False
  try:
    return math.isfinite(value)
  except OverflowError:
    return False


class DatabaseService:
  """Read a configured XMDM database without exposing filesystem access."""

  def __init__(
      self,
      db: str | os.PathLike[str] | None = None,
      *,
      backend: str | None = None,
  ):
    if backend not in (None, 'json', 'sqlite'):
      raise ValueError("backend must be 'json' or 'sqlite'")
    path = None if db is None else Path(db).expanduser()
    sqlite_mode = backend == 'sqlite' or (
      backend is None and path is not None and path.is_file()
    )
    if sqlite_mode:
      if path is None:
        raise ValueError('a SQLite database file path is required')
      self.repository = SQLiteRepository(path)
      self.catalog = SQLiteCatalog(self.repository)
      self.root = None
      self.check_database()
      return
    if backend == 'json' and path is not None and path.is_file():
      raise ValueError('JSON database path must be a directory')
    self.repository = None
    self.catalog = None
    self.root = database_directory(db).resolve()
    load_index(self.root)

  def _catalog(self) -> dict[str, Any]:
    if self.catalog is not None:
      return self.catalog.material_catalog()
    try:
      _, index = load_index(self.root)
    except (OSError, ValueError) as error:
      raise DatabaseUnavailable(
        'the configured material database is unavailable',
      ) from error
    return index['materials']

  def check_database(self) -> None:
    if self.catalog is not None:
      try:
        self.catalog.check_database()
      except (OSError, ValueError, RuntimeError) as error:
        raise DatabaseUnavailable(
          'the configured material database is unavailable',
        ) from error
      return
    try:
      load_index(self.root)
    except (OSError, ValueError) as error:
      raise DatabaseUnavailable(
        'the configured material database is unavailable',
      ) from error

  def _resolve_material(
      self, materials: dict[str, Any], query: str,
  ) -> tuple[str, dict[str, Any]]:
    normalized_query = _normalized(query)
    matches = [
      (material_id, entry)
      for material_id, entry in materials.items()
      if _normalized(material_id) == normalized_query
      or _normalized(entry['name']) == normalized_query
      or any(
        _normalized(alias) == normalized_query
        for alias in entry.get('aliases', [])
      )
    ]
    if not matches:
      raise RecordNotFound(f'material {query!r} not found')
    if len(matches) > 1:
      raise AmbiguousRecord(f'material {query!r} is ambiguous')
    return matches[0]

  def list_materials(
      self,
      query: str = '',
      limit: int = 100,
      offset: int = 0,
      physics: str | None = None,
      model: str | None = None,
  ) -> dict[str, Any]:
    _validate_pagination(limit, offset)
    if model is not None and model not in MODELS:
      raise InvalidQuery(f'unsupported model: {model!r}')
    if self.catalog is not None:
      return self.catalog.list_materials(query, limit, offset, physics, model)
    needle = _normalized(query)
    materials = [
      {
        'id': material_id,
        'name': entry['name'],
        'aliases': entry.get('aliases', []),
      }
      for material_id, entry in sorted(
        self._catalog().items(), key=lambda item: item[0].casefold(),
      )
      if (
        (physics is None and model is None)
        or any(
          (physics is None or reference.get('physics', 'optics') == physics)
          and (model is None or reference['model'] == model)
          for reference in entry['records']
        )
      )
      if not needle or needle in _normalized(
        ' '.join((material_id, entry['name'], *entry.get('aliases', []))),
      )
    ]
    return {
      'items': materials[offset:offset + limit],
      'total': len(materials),
      'limit': limit,
      'offset': offset,
    }

  def get_material(self, material_id: str) -> dict[str, Any]:
    if self.catalog is not None:
      return self.catalog.get_material(material_id)
    canonical_id, entry = self._resolve_material(self._catalog(), material_id)
    records = [
      {
        'id': reference['id'],
        'name': reference['name'],
        'model': reference['model'],
        'physics': reference.get('physics', 'optics'),
        'source': reference.get('source'),
      }
      for reference in entry['records']
    ]
    records.sort(key=lambda item: (item['name'].casefold(), item['model']))
    return {
      'id': canonical_id,
      'name': entry['name'],
      'aliases': entry.get('aliases', []),
      'records': records,
    }

  def list_records(
      self,
      query: str = '',
      model: str | None = None,
      material_id: str | None = None,
      limit: int = 100,
      offset: int = 0,
      physics: str | None = None,
  ) -> dict[str, Any]:
    _validate_pagination(limit, offset)
    if model is not None and model not in MODELS:
      raise InvalidQuery(f'unsupported model: {model!r}')
    if physics is not None and (not isinstance(physics, str) or not physics):
      raise InvalidQuery('physics must be a non-empty string')
    if self.catalog is not None:
      return self.catalog.list_records(
        query, model, material_id, limit, offset, physics,
      )
    materials = self._catalog()
    if material_id is not None:
      canonical_id, entry = self._resolve_material(materials, material_id)
      materials = {canonical_id: entry}

    needle = _normalized(query)
    records = []
    for current_id, entry in materials.items():
      for reference in entry['records']:
        if model is not None and reference['model'] != model:
          continue
        if physics is not None and reference.get('physics', 'optics') != physics:
          continue
        item = {
          'material_id': current_id,
          'material_name': entry['name'],
          'id': reference['id'],
          'name': reference['name'],
          'model': reference['model'],
          'physics': reference.get('physics', 'optics'),
          'source': reference.get('source'),
        }
        searchable = ' '.join((
          current_id,
          entry['name'],
          *entry.get('aliases', []),
          reference['name'],
          reference['model'],
          str(reference.get('source') or ''),
        ))
        if not needle or needle in _normalized(searchable):
          records.append(item)
    records.sort(key=lambda item: (
      item['material_id'].casefold(), item['name'].casefold(), item['model'],
    ))
    return {
      'items': records[offset:offset + limit],
      'total': len(records),
      'limit': limit,
      'offset': offset,
    }

  def get_record(
      self,
      material_id: str,
      record_name: str,
      model: str | None = None,
      physics: str | None = None,
  ) -> dict[str, Any]:
    if self.catalog is not None:
      return self.catalog.get_record(material_id, record_name, model, physics)
    if model is not None and model not in MODELS:
      raise InvalidQuery(f'unsupported model: {model!r}')
    materials = self._catalog()
    canonical_id, entry = self._resolve_material(materials, material_id)
    normalized_name = _normalized(record_name)
    matches = [
      reference
      for reference in entry['records']
      if _normalized(reference['name']) == normalized_name
      and (model is None or reference['model'] == model)
      and (physics is None or reference.get('physics', 'optics') == physics)
    ]
    if not matches:
      raise RecordNotFound(
        f'record {canonical_id}/{record_name} not found',
      )
    if len(matches) > 1:
      raise AmbiguousRecord(
        f'record {canonical_id}/{record_name} is ambiguous; specify a model',
      )
    selected = matches[0]
    try:
      record, _ = load_record(
        f'{canonical_id}/{selected["name"]}', selected['model'], self.root,
      )
    except (OSError, ValueError) as error:
      raise DatabaseUnavailable(
        'the configured material database is unavailable',
      ) from error
    return record

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
    if self.catalog is not None:
      return self.catalog.evaluate_record(
        material_id, record_name, model, coordinates, unit, parameter,
        interpolation,
      )
    if not coordinates:
      raise InvalidQuery('coordinates must be a non-empty array')
    if len(coordinates) > MAX_EVALUATION_POINTS:
      raise InvalidQuery(
        f'coordinates may contain at most {MAX_EVALUATION_POINTS} values',
      )
    if any(not _is_finite_number(value) for value in coordinates):
      raise InvalidQuery('coordinates must contain finite numeric values')
    if unit not in UNITS:
      raise InvalidQuery(f'unsupported spectral unit: {unit!r}')
    if parameter not in ('n', 'e', 'k', 'n2'):
      raise InvalidQuery("parameter must be 'n', 'e', 'k', or 'n2'")
    if interpolation not in ('linear', 'cubic'):
      raise InvalidQuery(f'unsupported interpolation: {interpolation!r}')
    if model != 'tabulated' and interpolation != 'linear':
      raise InvalidQuery(
        'interpolation is only configurable for tabulated records',
      )

    record = self.get_record(material_id, record_name, model)
    _validate_evaluation_physics(record, parameter)
    selector = f'{material_id}/{record_name}'
    if model == 'tabulated':
      if parameter == 'n2' and record['data'].get('type') != 'n2':
        raise InvalidQuery("parameter 'n2' requires tabulated n2 data")
      if parameter == 'k' and record['data'].get('type') not in (
        'n', 'nk', 'k',
      ):
        raise InvalidQuery("parameter 'k' requires tabulated refractive-index data")
      if interpolation not in ('linear', 'cubic'):
        raise InvalidQuery(f'unsupported interpolation: {interpolation!r}')
      material = Material.from_db(
        selector, db=self.root, unit=unit, kind=parameter, verbose=False,
      )
      values = material.interp(
        np.asarray(coordinates, dtype=float),
        unit=unit,
        kind=parameter,
        interp=interpolation,
      )
    else:
      if parameter == 'n2':
        raise InvalidQuery("parameter 'n2' requires tabulated n2 data")
      dispersion_type = _MODEL_TYPES[model]
      dispersion = dispersion_type.from_db(selector, db=self.root)
      evaluate = dispersion.n if parameter in ('n', 'k') else dispersion.eps
      values = evaluate(np.asarray(coordinates, dtype=float), unit=unit)
      if parameter == 'k':
        values = np.imag(values)

    result = np.asarray(values)
    if not np.all(np.isfinite(result)):
      raise InvalidQuery('evaluation produced non-finite values')
    flat = result.reshape(-1)
    return {
      'material_id': self.get_material(material_id)['id'],
      'record_name': record_name,
      'model': model,
      'parameter': parameter,
      'unit': unit,
      'coordinates': [float(value) for value in coordinates],
      'values': [
        {'real': float(value.real), 'imag': float(value.imag)}
        for value in flat
      ],
    }

  def verify(self) -> dict[str, Any]:
    if self.catalog is not None:
      return self.catalog.verify()
    records = self.list_records(limit=MAX_PAGE_SIZE)
    targets = list(records['items'])
    offset = len(targets)
    while offset < records['total']:
      page = self.list_records(limit=MAX_PAGE_SIZE, offset=offset)
      targets.extend(page['items'])
      offset += len(page['items'])

    errors = []
    for reference in targets:
      selector = f'{reference["material_id"]}/{reference["name"]}'
      try:
        record = self.get_record(
          reference['material_id'], reference['name'], reference['model'],
        )
        validate_record_data(record)
        json.dumps(record, allow_nan=False)
      except (DatabaseUnavailable, ValueError, TypeError) as error:
        errors.append({
          'selector': selector,
          'model': reference['model'],
          'error': str(error).replace(str(self.root), '<database>'),
        })
    return {'valid': not errors, 'checked': len(targets), 'errors': errors}

  def get_record_by_id(
        self, record_id: str, revision: int | None = None,
  ) -> dict[str, Any]:
    if self.catalog is not None:
        return self.catalog.get_record_by_id(record_id, revision)
    if revision not in (None, 1):
        raise RecordNotFound(f'revision {revision} for record {record_id!r} not found')
    try:
        canonical_id = str(uuid.UUID(record_id))
    except (ValueError, AttributeError) as error:
        raise InvalidQuery('record_id must be a UUID') from error
    page = self.list_records(limit=MAX_PAGE_SIZE)
    references = page['items']
    offset = len(references)
    while offset < page['total']:
        next_page = self.list_records(limit=MAX_PAGE_SIZE, offset=offset)
        references.extend(next_page['items'])
        offset += len(next_page['items'])
    for reference in references:
        if reference['id'] == canonical_id:
          return self.get_record(
            reference['material_id'], reference['name'], reference['model'],
          )
    raise RecordNotFound(f'record {canonical_id!r} not found')

  def get_record_envelope(
        self, record_id: str, revision: int | None = None,
  ) -> dict[str, Any]:
    if self.catalog is not None:
        return self.catalog.get_record_envelope(record_id, revision)
    record = self.get_record_by_id(record_id, revision)
    digest = hashlib.sha256(json.dumps(
        record, sort_keys=True, ensure_ascii=False, allow_nan=False,
        separators=(',', ':'),
    ).encode('utf-8')).hexdigest()
    return {
        'record': record,
        'revision': 1,
        'current_revision': 1,
        'created_at': None,
        'payload_sha256': digest,
    }

  def get_provenance(
        self, record_id: str, revision: int | None = None,
  ) -> dict[str, Any]:
    if self.catalog is not None:
        return self.catalog.get_provenance(record_id, revision)
    envelope = self.get_record_envelope(record_id, revision)
    return {
        'record_id': envelope['record']['id'],
        'revision': 1,
        'payload_sha256': envelope['payload_sha256'],
        'import': None,
        'derivation': None,
    }

  def get_revisions(self, record_id: str) -> list[dict[str, Any]]:
    if self.catalog is not None:
        return self.catalog.get_revisions(record_id)
    envelope = self.get_record_envelope(record_id)
    record = envelope['record']
    return [{
        'revision': 1,
        'name': record['name'],
        'physics': record['physics'],
        'model': record['model'],
        'payload_sha256': envelope['payload_sha256'],
        'created_at': None,
    }]

  def evaluate_record_by_id(
        self,
        record_id: str,
        coordinates: list[int | float],
        unit: str,
        parameter: str,
        interpolation: str = 'linear',
        revision: int | None = None,
  ) -> dict[str, Any]:
    if self.catalog is not None:
        return self.catalog.evaluate_record_by_id(
          record_id, coordinates, unit, parameter, interpolation, revision,
        )
    record = self.get_record_by_id(record_id, revision)
    page = self.list_records(limit=MAX_PAGE_SIZE)
    references = page['items']
    offset = len(references)
    while offset < page['total']:
        next_page = self.list_records(limit=MAX_PAGE_SIZE, offset=offset)
        references.extend(next_page['items'])
        offset += len(next_page['items'])
    for reference in references:
        if reference['id'] == record['id']:
          result = self.evaluate_record(
            reference['material_id'], record['name'], record['model'],
            coordinates, unit, parameter, interpolation,
          )
          result.pop('material_id')
          return {**result, 'record_id': record['id'], 'revision': 1}
    raise RecordNotFound(f'record {record_id!r} not found')

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
    if self.catalog is not None:
        return self.catalog.resample_record(
          record_id, coordinates, unit, parameter, interpolation,
          range_policy, revision,
        )
    envelope = self.get_record_envelope(record_id, revision)
    source = envelope['record']
    from ..db.catalog import (
      _XMDM_VERSION,
      _evaluate_payload,
      _range_warnings,
    )
    values = _evaluate_payload(
        source, coordinates, unit, parameter, interpolation,
        range_policy=range_policy,
    )
    record = {
        'schema_version': '1',
        'physics': 'nlo' if parameter == 'n2' else source['physics'],
        'model': 'tabulated',
        'name': f'{source["name"]} (resampled)',
        'id': str(uuid.uuid4()),
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
          'warnings': _range_warnings(source, coordinates, unit, range_policy),
        },
    }

  def validate_record(
        self, record_id: str, revision: int | None = None,
  ) -> dict[str, Any]:
    if self.catalog is not None:
        return self.catalog.validate_record(record_id, revision)
    record = self.get_record_by_id(record_id, revision)
    try:
        validate_record_data(record)
        json.dumps(record, allow_nan=False)
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        return {'valid': False, 'errors': [str(error)], 'warnings': []}
    return {'valid': True, 'errors': [], 'warnings': []}

  def create_record(
        self,
        material_id: str,
        payload: dict[str, Any],
        *,
        derivation: dict[str, Any] | None = None,
        actor_token_id: str | None = None,
  ) -> dict[str, Any]:
    if self.catalog is None:
        raise InvalidQuery('record mutations require a SQLite database')
    return self.catalog.create_record(
        material_id, payload, derivation=derivation,
        actor_token_id=actor_token_id,
    )

  def replace_record(
        self,
        record_id: str,
        payload: dict[str, Any],
        expected_revision: int,
        *,
        derivation: dict[str, Any] | None = None,
        actor_token_id: str | None = None,
  ) -> dict[str, Any]:
    if self.catalog is None:
        raise InvalidQuery('record mutations require a SQLite database')
    return self.catalog.replace_record(
        record_id, payload, expected_revision,
        derivation=derivation, actor_token_id=actor_token_id,
    )

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
    if self.catalog is None:
      raise InvalidQuery('record uploads require a SQLite database')
    return self.catalog.stage_submission(
      material_id, payload, actor_token_id=actor_token_id,
      material_name=material_name,
      derivation=derivation, target_record_id=target_record_id,
      expected_revision=expected_revision,
    )

  def list_submissions(
      self, status: str = 'pending', limit: int = 100,
   ) -> list[dict[str, Any]]:
    if self.catalog is None:
      raise InvalidQuery('submission review requires a SQLite database')
    return self.catalog.list_submissions(status, limit)

  def list_admin_records(
      self, query: str = '', limit: int = 100,
   ) -> list[dict[str, Any]]:
    if self.catalog is None:
      raise InvalidQuery('record administration requires a SQLite database')
    return self.catalog.list_admin_records(query, limit)

  def soft_delete_record(
      self, record_id: str, *, actor_token_id: str,
   ) -> dict[str, Any]:
    if self.catalog is None:
      raise InvalidQuery('record administration requires a SQLite database')
    return self.catalog.soft_delete_record(
      record_id, actor_token_id=actor_token_id,
    )

  def restore_record(
      self, record_id: str, *, actor_token_id: str,
   ) -> dict[str, Any]:
    if self.catalog is None:
      raise InvalidQuery('record administration requires a SQLite database')
    return self.catalog.restore_record(
      record_id, actor_token_id=actor_token_id,
    )

  def review_submission(
      self,
      submission_id: str,
      decision: str,
      *,
      actor_token_id: str,
      note: str | None = None,
   ) -> dict[str, Any]:
    if self.catalog is None:
      raise InvalidQuery('submission review requires a SQLite database')
    return self.catalog.review_submission(
      submission_id, decision, actor_token_id=actor_token_id, note=note,
    )

  def authenticate_token(self, token: str) -> dict[str, Any] | None:
    if self.catalog is None:
        return None
    return self.catalog.authenticate_token(token)

  def create_token(
        self, name: str, scopes: list[str], expires_at: str | None = None,
        *, actor_token_id: str | None = None,
  ) -> dict[str, Any]:
    if self.catalog is None:
        raise InvalidQuery('token administration requires a SQLite database')
    return self.catalog.create_token(
      name, scopes, expires_at, actor_token_id=actor_token_id,
    )

  def list_tokens(self) -> list[dict[str, Any]]:
    if self.catalog is None:
        raise InvalidQuery('token administration requires a SQLite database')
    return self.catalog.list_tokens()

  def list_audit_events(self, limit: int = 100) -> list[dict[str, Any]]:
    if self.catalog is None:
      raise InvalidQuery('audit log requires a SQLite database')
    return self.catalog.list_audit_events(limit)

  def revoke_token(
      self, token_id: str, *, actor_token_id: str | None = None,
  ) -> None:
    if self.catalog is None:
        raise InvalidQuery('token administration requires a SQLite database')
    self.catalog.revoke_token(token_id, actor_token_id=actor_token_id)

  def export_record(
        self, record_id: str, revision: int | None, format_name: str,
  ) -> tuple[str, str]:
    if self.catalog is not None:
        return self.catalog.export_record(record_id, revision, format_name)
    record = self.get_record_by_id(record_id, revision)
    if format_name in ('json', 'yaml'):
        return json.dumps(
          record, indent=2, ensure_ascii=False, allow_nan=False,
        ) + '\n', (
          'application/json' if format_name == 'json' else 'application/yaml'
        )
    if format_name != 'csv':
        raise InvalidQuery(f'unsupported export format: {format_name!r}')
    if record['model'] != 'tabulated':
        raise InvalidQuery('CSV export is only available for tabulated records')
    import csv
    import io
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
