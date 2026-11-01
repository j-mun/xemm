"""Resolve bundled and user-provided material database paths."""

from __future__ import annotations

import sys
from pathlib import Path

_SOURCE_DB = Path(__file__).resolve().parents[2] / 'xmdm-db'
_INSTALLED_DB = Path(sys.prefix) / 'xmdm-db'


def database_directory(db: str | Path | None = None) -> Path:
  """Return the root directory of a material-first JSON database."""
  if db is not None:
    return Path(db)

  return _SOURCE_DB if (_SOURCE_DB / 'index.json').is_file() else _INSTALLED_DB