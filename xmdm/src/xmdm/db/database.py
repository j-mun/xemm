"""Read and validate the material-first JSON database."""

from __future__ import annotations

import json
import math
import os
import unicodedata
import uuid
from pathlib import Path
from typing import Any

from .. import __schema_version__
from .paths import database_directory


class MaterialNotFound(ValueError):
  """No material matches a catalog lookup."""


class AmbiguousMaterial(ValueError):
  """Multiple materials match a catalog lookup."""


def _normalized(value: str) -> str:
  return ''.join(
    character
    for character in unicodedata.normalize('NFKD', value).casefold()
    if not unicodedata.combining(character)
  )


def _read_json(path: Path) -> dict[str, Any]:
  if not path.is_file():
    raise ValueError(f'database file does not exist: {str(path)!r}')
  try:
    with path.open(encoding='utf-8') as stream:
      value = json.load(stream)
  except json.JSONDecodeError as error:
    raise ValueError(f'invalid JSON database file: {str(path)!r}') from error
  except OSError as error:
    raise ValueError(f'could not read database file: {str(path)!r}') from error
  if not isinstance(value, dict):
    raise ValueError(f'expected a JSON object in database file: {str(path)!r}')
  return value


def load_index(db: str | os.PathLike[str] | None = None) -> tuple[Path, dict[str, Any]]:
  root = database_directory(db)
  index_path = root / 'index.json'
  if not root.is_dir():
    raise ValueError(f'material database directory does not exist: {str(root)!r}')
  if not index_path.is_file():
    raise ValueError(f'material database index does not exist: {str(index_path)!r}')
  index = _read_json(index_path)
  if index.get('schema_version') != __schema_version__:
    raise ValueError(
      f'unsupported database schema version in {str(index_path)!r}: '
      f'{index.get("schema_version")!r}'
    )
  materials = index.get('materials')
  if not isinstance(materials, dict):
    raise ValueError(f'invalid material catalog in {str(index_path)!r}')
  for material_id, entry in materials.items():
    if (
      not isinstance(material_id, str)
      or not material_id
      or not isinstance(entry, dict)
    ):
      raise ValueError(f'invalid material entry in {str(index_path)!r}')
    aliases = entry.get('aliases', [])
    records = entry.get('records')
    if (
      not isinstance(entry.get('name'), str)
      or not entry['name']
      or not isinstance(aliases, list)
      or not all(isinstance(alias, str) for alias in aliases)
      or not isinstance(records, list)
      or not all(isinstance(record, dict) for record in records)
    ):
      raise ValueError(f'invalid material entry in {str(index_path)!r}')
  return root, index


def _material_entry(
    materials: dict[str, Any],
    query: str,
) -> tuple[str, dict[str, Any]]:
  normalized_query = _normalized(query)
  matches = [
    (material_id, entry)
    for material_id, entry in materials.items()
    if isinstance(entry, dict)
    and (
      _normalized(material_id) == normalized_query
      or _normalized(str(entry.get('name', ''))) == normalized_query
      or any(
        isinstance(alias, str) and _normalized(alias) == normalized_query
        for alias in entry.get('aliases', [])
      )
    )
  ]
  if not matches:
    raise MaterialNotFound(f'material {query!r} not found in database')
  if len(matches) > 1:
    raise AmbiguousMaterial(f'material name {query!r} is ambiguous in database')
  material_id, entry = matches[0]
  return material_id, entry


def available_materials(
    db: str | os.PathLike[str] | None = None,
) -> list[str]:
  _, index = load_index(db)
  return sorted(index['materials'], key=str.casefold)


def available_model_materials(
    model: str,
    db: str | os.PathLike[str] | None = None,
) -> list[str]:
  _, index = load_index(db)
  return sorted(
    (
      material_id
      for material_id, entry in index['materials'].items()
      if isinstance(entry, dict)
      and isinstance(entry.get('records'), list)
      and any(
        isinstance(record, dict) and record.get('model') == model
        for record in entry['records']
      )
    ),
    key=str.casefold,
  )


def available_records(
    material: str,
    model: str,
    db: str | os.PathLike[str] | None = None,
) -> list[str]:
  _, index = load_index(db)
  try:
    _, entry = _material_entry(index['materials'], material)
  except ValueError as error:
    if str(error).startswith(f'material {material!r} not found'):
      return []
    raise
  records = entry.get('records')
  if not isinstance(records, list):
    raise ValueError(f'invalid record catalog for material {material!r}')
  names = {
    record['name']
    for record in records
    if isinstance(record, dict)
    and record.get('model') == model
    and isinstance(record.get('name'), str)
  }
  return sorted(names, key=str.casefold)


def load_record(
    query: str,
    model: str,
    db: str | os.PathLike[str] | None = None,
) -> tuple[dict[str, Any], str]:
  root, index = load_index(db)
  parts = query.split('/', maxsplit=1)
  if len(parts) != 2 or not all(parts):
    raise ValueError("record name must have the form 'material/name'")
  material_query, name_query = parts
  material_id, entry = _material_entry(index['materials'], material_query)
  records = entry.get('records')
  if not isinstance(records, list):
    raise ValueError(f'invalid record catalog for material {material_id!r}')
  matching_records = [
    record
    for record in records
    if isinstance(record, dict)
    and record.get('model') == model
    and isinstance(record.get('name'), str)
    and _normalized(record['name']) == _normalized(name_query)
  ]
  if not matching_records:
    raise ValueError(f'{model} record {query!r} not found in database')
  if len(matching_records) > 1:
    raise ValueError(f'{model} record name {query!r} is ambiguous in database')
  reference = matching_records[0]
  relative_path = reference.get('path')
  if not isinstance(relative_path, str):
    raise ValueError(f'invalid record path for {query!r}')
  record_path = (root / relative_path).resolve()
  try:
    record_path.relative_to(root.resolve())
  except ValueError as error:
    raise ValueError(f'record path escapes database root for {query!r}') from error

  record = _read_json(record_path)
  if record.get('schema_version') != __schema_version__:
    raise ValueError(
      f'unsupported record schema version in {str(record_path)!r}: '
      f'{record.get("schema_version")!r}'
    )
  if record.get('id') != reference.get('id'):
    raise ValueError(f'record ID does not match index entry for {query!r}')
  if record_path.stem != record.get('id') or record_path.parent.name != material_id:
    raise ValueError(f'record path does not match its identity for {query!r}')
  if record.get('model') != model or record.get('name') != reference.get('name'):
    raise ValueError(f'record metadata does not match index entry for {query!r}')
  try:
    uuid.UUID(record['id'])
  except (KeyError, TypeError, ValueError, AttributeError) as error:
    raise ValueError(f'invalid record ID in {str(record_path)!r}') from error
  data = record.get('data')
  if not isinstance(data, dict):
    raise ValueError(f'invalid model data in {str(record_path)!r}')
  metadata = record.get('metadata')
  if not isinstance(metadata, dict):
    raise ValueError(f'invalid record metadata in {str(record_path)!r}')
  return record, str(entry.get('name', material_id))


def tabulated_arrays(
    record: dict[str, Any],
) -> tuple[list[float], list[float], list[float], str, str]:
  data = record['data']
  unit = data.get('unit')
  parm = data.get('type')
  if unit not in ('m', 'nm', 'um', 'Hz', 'GHz', 'THz', 'cm-1', 'eV'):
    raise ValueError(f'invalid tabulated unit in record {record["id"]!r}')
  if parm not in ('n', 'nk', 'e', 'eps', 'k', 'n2'):
    raise ValueError(f'invalid tabulated property type in record {record["id"]!r}')
  arrays: list[list[float]] = []
  for field in ('f', 're', 'im'):
    values = data.get(field)
    if not isinstance(values, list) or not values:
      raise ValueError(f'invalid tabulated {field!r} array in record {record["id"]!r}')
    try:
      if any(
        isinstance(value, bool) or not isinstance(value, (int, float))
        for value in values
      ):
        raise TypeError
      array = [float(value) for value in values]
    except (TypeError, ValueError) as error:
      raise ValueError(
        f'invalid tabulated {field!r} values in record {record["id"]!r}'
      ) from error
    if not all(map(math.isfinite, array)):
      raise ValueError(f'non-finite tabulated values in record {record["id"]!r}')
    arrays.append(array)
  if len({len(array) for array in arrays}) != 1:
    raise ValueError(f'tabulated array lengths differ in record {record["id"]!r}')
  return arrays[0], arrays[1], arrays[2], unit, parm


__all__ = [
  'available_materials',
  'available_model_materials',
  'available_records',
  'load_index',
  'load_record',
  'tabulated_arrays',
]
