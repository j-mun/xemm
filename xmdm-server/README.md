# XMDM Server

`xmdm-server` provides shared material catalog and optical-model services over
HTTP, MCP, a command-line interface, and a small browser UI. It can read the
bundled/custom material-first JSON database or an explicitly initialized
SQLite catalog. SQLite is the writable backend; JSON directories remain
supported for migration and interchange.

## Installation

Install the server with its HTTP and MCP interfaces:

```bash
python -m pip install '.[all]'
```

For a source checkout, install `xmdm` first and then `xmdm-server`:

```bash
cd /path/to/xmdm
python -m pip install .
cd /path/to/xmdm-server
python -m pip install '.[dev,all]'
```

## Database setup

The bundled `xmdm-db` JSON catalog is used by default. A JSON directory can be
selected explicitly:

```bash
xmdm verify --db /path/to/material-database --backend json
xmdm server --db /path/to/material-database --backend json
```

Create a SQLite catalog by importing the bundled records, or create an empty
schema and import a custom JSON catalog:

```bash
xmdm db init --db ./materials.sqlite
xmdm db init --db ./empty.sqlite --empty
xmdm db import --source /path/to/material-database --db ./empty.sqlite
xmdm verify --db ./materials.sqlite
xmdm db backup --db ./materials.sqlite --destination ./materials-backup.sqlite
xmdm db export --db ./materials.sqlite --destination ./json-export
xmdm server --db ./materials.sqlite --backend sqlite
```

To serve the browser UI and Streamable HTTP MCP from the same process, use
`xmdm server --mcp`. When binding beyond localhost, configure the MCP host and
origin allowlists described in the [CLI guide](docs/cli.md).

Initialization refuses to overwrite an existing file. Migration, verification,
import, export, and backup are explicit CLI operations. JSON imports are
idempotent for a stable source namespace; changed imported payloads are rejected
unless `--on-change new_revision` is specified. UUID collisions are assigned
new server UUIDs and the import identity is retained.

`--backend` accepts `json` or `sqlite`; existing directories/files are also
recognized when no backend is supplied. A missing configured path is an error,
not a request to create a database or silently use another one.
`XMDM_DB`, `XMDM_DB_BACKEND`, `XMDM_HOST`, and `XMDM_PORT` provide environment
defaults; command-line options take precedence.

## HTTP API and browser UI

See the detailed [HTTP API](docs/http_api.md), [CLI](docs/cli.md),
[database](docs/db.md), and [MCP](docs/mcp.md) references for endpoint tables,
command options, schema details, and client workflows.

Run the API and web interface:

```bash
xmdm server --db ./materials.sqlite --backend sqlite
```

The API listens on `127.0.0.1:8000` by default. The browser has separate
`/data`, `/upload`, `/admin`, and `/status` pages; `/` redirects to `/data`.
Use Data to search records and plot complex refractive-index spectra (`n`/`k`),
permittivity (`ε`), standalone extinction coefficients, and nonlinear index
(`n²`), Upload to preview and submit records, Admin to review submissions and
archive/restore records, and Status to check API/database health.

| Method and path | Description |
| --- | --- |
| `GET /api/v1/health` | Database readiness. |
| `GET /api/v1/materials` | Search/page materials; supports `query`, `physics`, `model`, `limit`, and `offset`. |
| `GET /api/v1/materials/{material_id}` | Material aliases and current record summaries. |
| `GET /api/v1/records` | Search/page current records; supports `query`, `material_id`, `physics`, `model`, `limit`, and `offset`. |
| `GET /api/v1/records/{record_id}` | Record and revision envelope; optional `revision`. |
| `GET /api/v1/records/{record_id}/revisions` | Revision history summaries. |
| `GET /api/v1/records/{record_id}/data` | Original model data; optional `revision`. |
| `GET /api/v1/records/{record_id}/metadata` | Source metadata; optional `revision`. |
| `GET /api/v1/records/{record_id}/provenance` | Payload hash, import mapping, and derivation details. |
| `GET /api/v1/records/{record_id}/export?format=json\|yaml\|csv` | Export a record. CSV is tabulated-only. |
| `GET /api/v1/records/{material_id}/{record_name}` | Existing human-selector lookup. |
| `POST /api/v1/evaluate` | Evaluate a selected material/name or UUID/revision. |
| `POST /api/v1/records/{record_id}/resample` | Compute a transient tabulated record with provenance; no write. |
| `POST /api/v1/records/{record_id}/validate` | Validate a stored revision. |
| `POST /api/v1/submissions` | Verify and stage a new record for approval (requires `records:write`; returns 202). |
| `PUT /api/v1/records/{record_id}` | Stage a revision using `If-Match: "revision"` (requires `records:write`; returns 202). |
| `/api/v1/admin/submissions` | List, approve, or reject pending uploads (requires `tokens:admin`). |
| `GET /api/v1/admin/records` | Search published and archived records (requires `tokens:admin`). |
| `DELETE /api/v1/admin/records/{record_id}` | Archive a record without removing history. |
| `POST /api/v1/admin/records/{record_id}/restore` | Restore an archived record if its selector is available. |
| `/api/v1/admin/tokens`, `/api/v1/admin/audit` | Token administration and audit data (requires `tokens:admin`). |

Page sizes are limited to 1000 and evaluation/resampling to 10,000 finite
coordinates. Supported spectral units are `m`, `nm`, `um`, `Hz`, `GHz`, `THz`,
`cm-1`, and `eV`. Parameters are `n`, `e`, `k`, and tabulated `n2`. Tabulated
data supports linear and cubic interpolation, with `clip`, `error`, or
`extrapolate` range policies for resampling.

JSON export retains the XMDM material-first schema. YAML export is emitted as
JSON syntax, which is valid YAML 1.2. CSV export contains coordinate, real, and
imaginary columns for tabulated records. Lumerical export is not implemented
until its format and metadata fidelity are specified. The JSON interchange
format exports current records; SQLite revision history remains in SQLite.

## Bearer-token administration

Read and evaluation endpoints are public; the default bind address is loopback.
Only SQLite-backed HTTP mutation and token administration are supported, and
they require bearer tokens with the relevant scope. Tokens are generated
locally, stored only as SHA-256 digests, and displayed once:

```bash
xmdm admin token create --db ./materials.sqlite --name writer \
  --scope records:write --expires-in-days 30
xmdm admin token create --db ./materials.sqlite --name administrator \
  --scope tokens:admin --scope records:write
xmdm admin token list --db ./materials.sqlite
xmdm admin token revoke --db ./materials.sqlite TOKEN_ID
xmdm admin token audit --db ./materials.sqlite --limit 100
```

`records:write` permits verified submission staging. `tokens:admin` permits
submission review, record archive/restore, and token and audit API access.
Archived records are hidden from public catalog views but retained in SQLite
with their revisions and provenance. Uploads remain pending and invisible to
catalog reads until approved. Token creation/revocation,
submission, review, and publication append audit events. The CLI token
commands are local administrative operations and require filesystem access to
the database.

The browser UI supports paste or multiple CSV/TXT/JSON files, preview of each
selected spectrum, submission with a `records:write` token, and review with a
separate `tokens:admin` token; tokens are not persisted. MCP tools and
resources share the service layer for discovery,
revision access, evaluation, validation, and transient resampling. Stdio MCP
submission is opt-in with `XMDM_MCP_TOKEN`; HTTP MCP is mounted at `/mcp/` with
`xmdm server --mcp` and requires per-request bearer authorization for uploads.

## Security and deployment

The HTTP API has no authentication for reads/evaluation and binds to
`127.0.0.1` by default. Do not expose it directly to an untrusted network. For
remote deployments, use TLS and an appropriate network boundary; use bearer
tokens for writes and token administration. Restrict database file permissions
and protect token output at creation. SQLite uses foreign-key enforcement,
WAL, bounded busy timeouts, transactions, and SQLite's online backup API.

Asynchronous fitting/job management, user accounts, token rotation policies,
Lumerical export, and multi-record comparison are not part of this release.
