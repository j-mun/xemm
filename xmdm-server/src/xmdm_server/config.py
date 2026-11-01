"""Runtime settings shared by server entry points."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
  db: str | None = None
  host: str = '127.0.0.1'
  port: int = 8000
  db_backend: str | None = None

  @classmethod
  def from_environment(
      cls,
      *,
      db: str | None = None,
      host: str | None = None,
      port: int | None = None,
      db_backend: str | None = None,
  ) -> Settings:
    selected_backend = (
      db_backend
      if db_backend is not None
      else os.environ.get('XMDM_DB_BACKEND')
    )
    if selected_backend not in (None, 'json', 'sqlite'):
      raise ValueError('XMDM_DB_BACKEND must be "json" or "sqlite"')
    selected_port = port
    if selected_port is None:
      raw_port = os.environ.get('XMDM_PORT', '8000')
      try:
        selected_port = int(raw_port)
      except ValueError as error:
        raise ValueError('XMDM_PORT must be an integer') from error
    if not 1 <= selected_port <= 65535:
      raise ValueError('port must be in the range 1..65535')
    return cls(
      db=db if db is not None else os.environ.get('XMDM_DB'),
      host=host if host is not None else os.environ.get('XMDM_HOST', '127.0.0.1'),
      port=selected_port,
      db_backend=selected_backend,
    )
