"""Resolve bundled and user-provided material database paths."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_SOURCE_DB = Path(__file__).resolve().parent.parent / 'xemm-db'
_INSTALLED_DB = Path(sys.prefix) / 'xemm-db'


def _database_directory(
    db: str | os.PathLike[str] | None,
    subdirectory: str | None = None,
) -> Path:
  if db is not None:
    return Path(db)

  source_path = _SOURCE_DB / subdirectory if subdirectory else _SOURCE_DB
  installed_path = _INSTALLED_DB / subdirectory if subdirectory else _INSTALLED_DB
  return source_path if source_path.is_dir() else installed_path


def resolve_tabulated_file(
    file: str | os.PathLike[str],
    db: str | os.PathLike[str] | None = None,
) -> str:
  """Resolve a tabulated material file, accepting an optional YAML suffix."""
  root = _database_directory(db, subdirectory='tabulated')
  if not root.is_dir():
    raise ValueError(f'material database directory does not exist: {str(root)!r}')

  path = Path(file)
  if not path.is_absolute():
    path = root / path
  if path.suffix in ('.yml', '.yaml'):
    candidates = (path,)
  else:
    candidates = (
      Path(os.fspath(path) + '.yml'),
      Path(os.fspath(path) + '.yaml'),
    )
  for candidate in candidates:
    if candidate.is_file():
      return os.fspath(candidate)
  raise ValueError(f'material data file does not exist: {str(file)!r}')


def resolve_model_file(
    filename: str | os.PathLike[str],
    db: str | os.PathLike[str] | None = None,
    *,
    missing_ok: bool = False,
) -> Path | None:
  """Resolve a model database file within the model database root."""
  root = _database_directory(db)
  if not root.is_dir():
    raise ValueError(f'model database directory does not exist: {str(root)!r}')
  path = root / filename
  if not path.is_file():
    if missing_ok:
      return None
    raise ValueError(f'model database file does not exist: {str(path)!r}')
  return path


def available_tabulated_materials(
    db: str | os.PathLike[str] | None = None,
) -> list[str]:
  """List material directories in the selected tabulated database."""
  root = _database_directory(db, subdirectory='tabulated')
  if not root.is_dir():
    raise ValueError(f'material database directory does not exist: {str(root)!r}')
  return sorted(
    (entry.name for entry in root.iterdir() if entry.is_dir()),
    key=str.casefold,
  )


def available_tabulated_models(
    name: str,
    db: str | os.PathLike[str] | None = None,
) -> list[str]:
  """List YAML model names for a material in the selected tabulated database."""
  root = _database_directory(db, subdirectory='tabulated')
  if not root.is_dir():
    raise ValueError(f'material database directory does not exist: {str(root)!r}')

  material = next(
    (
      entry for entry in root.iterdir()
      if entry.is_dir() and entry.name.casefold() == name.casefold()
    ),
    None,
  )
  if material is None:
    return []
  models = {
    path.stem
    for path in material.iterdir()
    if path.is_file() and path.suffix.casefold() in ('.yml', '.yaml')
  }
  return sorted(models, key=str.casefold)