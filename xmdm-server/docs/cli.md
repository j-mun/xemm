# Command-line interface

The `xmdm` executable provides server/runtime commands, explicit SQLite
maintenance, and local bearer-token administration. Run `xmdm --help` or
`xmdm <command> --help` for parser-generated usage.

## Commands and use cases

| Command | Important options | Use case |
| --- | --- | --- |
| `xmdm --version` | — | Check the installed server package version. |
| `xmdm server` | `--db PATH`, `--backend json\|sqlite`, `--host HOST`, `--port PORT`, `--web` / `--no-web`, `--mcp` | Start the HTTP API, optionally serve the browser UI, and optionally mount Streamable HTTP MCP at `/mcp/`. |
| `xmdm mcp` | `--db PATH`, `--backend json\|sqlite` | Start the MCP server over stdio for a local MCP client. |
| `xmdm verify` | `--db PATH`, `--backend json\|sqlite` | Validate that a configured data source can be read; exit nonzero when invalid. |
| `xmdm db init` | required `--db PATH`; optional `--empty` | Create a new SQLite database. By default import the bundled XMDM catalog; use `--empty` to create only the schema. |
| `xmdm db migrate` | required `--db PATH` | Apply pending storage schema migrations to an existing SQLite file and verify it. |
| `xmdm db import` | required `--source JSON_ROOT`, `--db PATH`; `--on-change error\|new_revision` | Import a JSON catalog, reimport idempotently, or explicitly append revisions when source payloads changed. |
| `xmdm db export` | required `--db PATH`, `--destination DIRECTORY` | Export current record revisions as a material-first JSON database. |
| `xmdm db backup` | required `--db PATH`, `--destination FILE` | Create a consistent SQLite online backup, preserving revision and audit history. |
| `xmdm admin token create` | required `--db PATH`, `--name NAME`, one or more `--scope`; optional `--expires-in-days N` | Create a scoped API token locally and display its secret once. |
| `xmdm admin token list` | required `--db PATH` | List token metadata, scopes, expiry, and revocation state; secrets are not shown. |
| `xmdm admin token revoke` | required `--db PATH`, positional `TOKEN_ID` | Revoke a token using local database access. |
| `xmdm admin token audit` | required `--db PATH`; optional `--limit N` (default 100) | Inspect recent audit events locally. |

`--scope` may be repeated and accepts `records:write` and `tokens:admin`.
An expiration interval must be a positive number of days. Database maintenance
and token commands operate locally and do not require an HTTP admin API token.

## Common workflows

### Run against JSON

```bash
xmdm verify --db /path/to/material-database --backend json
xmdm server --db /path/to/material-database --backend json
```

JSON directories support reads and evaluation; they are not writable through
the server API.

### Initialize and run SQLite

```bash
xmdm db init --db ./materials.sqlite
xmdm server --db ./materials.sqlite --backend sqlite
```

Run the API, browser UI, and Streamable HTTP MCP together:

```bash
xmdm server --db ./materials.sqlite --backend sqlite --host 0.0.0.0 --mcp
```

The browser UI is enabled by default; `--no-web` disables it and `--web`
explicitly enables it. MCP remains protected against DNS rebinding. Local
hostnames are allowed by default; set `XMDM_MCP_ALLOWED_HOSTS` to a
comma-separated list of trusted host patterns (for example
`materials.example.org:*`) and `XMDM_MCP_ALLOWED_ORIGINS` to trusted browser
origins if required. Do not use a broad allowlist on an untrusted network.

Initialization refuses to overwrite an existing path. To import a custom
catalog, create an empty database and import explicitly:

```bash
xmdm db init --db ./custom.sqlite --empty
xmdm db import --source /path/to/material-database --db ./custom.sqlite
xmdm verify --db ./custom.sqlite
```

Identical records in the same source namespace are no-ops on reimport. A
changed imported payload fails by default; `--on-change new_revision` is an
explicit request to append a revision.

### Back up and export

```bash
xmdm db backup --db ./materials.sqlite --destination ./materials-backup.sqlite
xmdm db export --db ./materials.sqlite --destination ./materials-json
```

Use backup to preserve SQLite revision history. JSON export contains only each
record's current revision.

### Bootstrap API administration

Create a token with both scopes when administering tokens and writing records:

```bash
xmdm admin token create --db ./materials.sqlite --name administrator \
  --scope tokens:admin --scope records:write
```

Use `records:write` to stage HTTP record submissions and `tokens:admin` for
HTTP submission review, token, and audit endpoints. Token output is sensitive
because the secret is shown only once; store it securely.

## Configuration and exit behavior

For `server`, `mcp`, and `verify`, command-line settings override environment
variables. Supported environment defaults are:

| Variable | Default / accepted values | Applies to |
| --- | --- | --- |
| `XMDM_DB` | Unset uses the service's bundled JSON database default | server, mcp, verify |
| `XMDM_DB_BACKEND` | `json`, `sqlite`, or unset for path inference | server, mcp, verify |
| `XMDM_HOST` | `127.0.0.1` | server |
| `XMDM_PORT` | `8000`; integer 1–65535 | server |
| `XMDM_MCP_ALLOWED_HOSTS` | Localhost patterns plus configured comma-separated patterns | Streamable HTTP MCP |
| `XMDM_MCP_ALLOWED_ORIGINS` | Localhost origins plus configured comma-separated origins | Streamable HTTP MCP |

An existing directory or file can be inferred when no backend is supplied.
Explicitly configured missing paths are errors; the server does not silently
create a database or switch to another source. SQLite initialization is only
done by `db init`.

Commands return 0 on success. Verification returns 1 for an invalid database;
operational errors are printed to stderr and return 1. Missing optional
interface dependencies print an installation hint and return 2. MCP stdio
protocol traffic uses stdout; server logs and CLI errors use stderr. The HTTP
MCP transport shares the server bind address and port.