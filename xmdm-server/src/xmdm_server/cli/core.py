"""Command-line entry points for the XMDM server."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from typing import Sequence

from .. import __version__
from ..config import Settings
from ..db import SQLiteCatalog, SQLiteRepository, initialize_database, migrate_database
from ..services import DatabaseService
from xmdm import database_directory


def _parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(prog='xmdm')
  parser.add_argument('--version', action='version', version=f'xmdm {__version__}')
  commands = parser.add_subparsers(dest='command')

  server = commands.add_parser('server', help='start the HTTP API and browser UI')
  server.add_argument('--db')
  server.add_argument('--backend', choices=('json', 'sqlite'))
  server.add_argument('--host')
  server.add_argument('--port', type=int)
  web_options = server.add_mutually_exclusive_group()
  web_options.add_argument(
    '--web', dest='web', action='store_true',
    help='serve the browser UI (the default)',
  )
  web_options.add_argument(
    '--no-web', dest='web', action='store_false',
    help='disable the browser UI',
  )
  server.set_defaults(web=True)
  server.add_argument(
    '--mcp', action='store_true',
    help='also expose Streamable HTTP MCP at /mcp',
  )

  mcp = commands.add_parser('mcp', help='run the stdio MCP server')
  mcp.add_argument('--db')
  mcp.add_argument('--backend', choices=('json', 'sqlite'))

  verify = commands.add_parser('verify', help='validate the configured database')
  verify.add_argument('--db')
  verify.add_argument('--backend', choices=('json', 'sqlite'))

  db = commands.add_parser('db', help='manage a local SQLite database')
  db_commands = db.add_subparsers(dest='db_command')
  initialize = db_commands.add_parser('init', help='create a new database')
  initialize.add_argument('--db', required=True)
  initialize.add_argument('--empty', action='store_true')
  migrate = db_commands.add_parser('migrate', help='apply storage migrations')
  migrate.add_argument('--db', required=True)
  import_db = db_commands.add_parser('import', help='import a JSON database')
  import_db.add_argument('--source', required=True)
  import_db.add_argument('--db', required=True)
  import_db.add_argument(
    '--on-change', choices=('error', 'new_revision'), default='error',
  )
  export_db = db_commands.add_parser('export', help='export a JSON database')
  export_db.add_argument('--destination', required=True)
  export_db.add_argument('--db', required=True)
  backup_db = db_commands.add_parser('backup', help='create a consistent backup')
  backup_db.add_argument('--destination', required=True)
  backup_db.add_argument('--db', required=True)

  admin = commands.add_parser('admin', help='manage local API tokens')
  admin_commands = admin.add_subparsers(dest='admin_command')
  tokens = admin_commands.add_parser('token', help='manage bearer tokens')
  token_commands = tokens.add_subparsers(dest='token_command')
  token_create = token_commands.add_parser('create', help='create a token')
  token_create.add_argument('--db', required=True)
  token_create.add_argument('--name', required=True)
  token_create.add_argument(
    '--scope', action='append', required=True,
    choices=('records:write', 'tokens:admin'),
  )
  token_create.add_argument('--expires-in-days', type=int)
  token_list = token_commands.add_parser('list', help='list token metadata')
  token_list.add_argument('--db', required=True)
  token_revoke = token_commands.add_parser('revoke', help='revoke a token')
  token_revoke.add_argument('--db', required=True)
  token_revoke.add_argument('token_id')
  token_audit = token_commands.add_parser('audit', help='inspect audit events')
  token_audit.add_argument('--db', required=True)
  token_audit.add_argument('--limit', type=int, default=100)
  return parser


def _catalog(path: str) -> SQLiteCatalog:
  catalog = SQLiteCatalog(SQLiteRepository(path))
  catalog.check_database()
  return catalog


def _database_command(args: argparse.Namespace) -> int:
  if args.db_command == 'init':
    repository = initialize_database(args.db)
    if not args.empty:
      catalog = SQLiteCatalog(repository)
      report = catalog.import_json(database_directory())
      print(json.dumps({'initialized': args.db, **report}, indent=2))
    else:
      print(json.dumps({'initialized': args.db, 'empty': True}, indent=2))
    return 0
  if args.db_command == 'migrate':
    migrate_database(args.db)
    _catalog(args.db).check_database()
    print(json.dumps({'migrated': args.db}, indent=2))
    return 0
  if args.db_command == 'import':
    report = _catalog(args.db).import_json(
      args.source, on_change=args.on_change,
    )
    print(json.dumps(report, indent=2))
    return 0
  if args.db_command == 'export':
    destination = _catalog(args.db).export_json(args.destination)
    print(json.dumps({'exported': str(destination)}, indent=2))
    return 0
  if args.db_command == 'backup':
    destination = _catalog(args.db).backup(args.destination)
    print(json.dumps({'backup': str(destination)}, indent=2))
    return 0
  return 2


def _admin_command(args: argparse.Namespace) -> int:
  catalog = _catalog(args.db)
  if args.token_command == 'create':
    expires_at = None
    if args.expires_in_days is not None:
      if args.expires_in_days < 1:
        raise ValueError('--expires-in-days must be positive')
      expires_at = (
        datetime.now(UTC) + timedelta(days=args.expires_in_days)
      ).isoformat()
    print(json.dumps(
      catalog.create_token(args.name, args.scope, expires_at), indent=2,
    ))
    return 0
  if args.token_command == 'list':
    print(json.dumps(catalog.list_tokens(), indent=2))
    return 0
  if args.token_command == 'audit':
    print(json.dumps(catalog.list_audit_events(args.limit), indent=2))
    return 0
  if args.token_command == 'revoke':
    catalog.revoke_token(args.token_id)
    print(json.dumps({'revoked': args.token_id}, indent=2))
    return 0
  return 2


def main(argv: Sequence[str] | None = None) -> int:
  parser = _parser()
  args = parser.parse_args(argv)
  if args.command is None:
    parser.print_help()
    return 0

  try:
    if args.command == 'db':
      return _database_command(args)
    if args.command == 'admin':
      return _admin_command(args)
    if args.command == 'verify':
      settings = Settings.from_environment(
        db=args.db, db_backend=args.backend,
      )
      service = DatabaseService(settings.db, backend=settings.db_backend)
      report = service.verify()
      print(json.dumps(report, indent=2, allow_nan=False))
      return 0 if report['valid'] else 1
    if args.command == 'mcp':
      settings = Settings.from_environment(
        db=args.db, db_backend=args.backend,
      )
      from ..mcp import run
      run(settings.db, backend=settings.db_backend)
      return 0

    settings = Settings.from_environment(
      db=args.db, host=args.host, port=args.port,
      db_backend=args.backend,
    )
    service = DatabaseService(settings.db, backend=settings.db_backend)
    from uvicorn import run
    from ..api import create_app
    run(
      create_app(
        service, web=args.web, mcp_http=args.mcp, mcp_host=settings.host,
      ),
      host=settings.host,
      port=settings.port,
    )
    return 0
  except ModuleNotFoundError as error:
    extras = {'mcp': 'mcp', 'fastapi': 'web', 'uvicorn': 'web'}
    if error.name not in extras:
      raise
    print(
      f'xmdm: install the optional interface with '
      f'python -m pip install "xmdm-server[{extras[error.name]}]"',
      file=sys.stderr,
    )
    return 2
  except (ValueError, OSError, PermissionError, RuntimeError) as error:
    print(f'xmdm: {error}', file=sys.stderr)
    return 1
