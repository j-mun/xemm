# XMDM Server Plan

This document outlines the proposed design, goals, use cases, and implementations.
The listed features and use cases may not have been actually implemented yet.


`xmdm-server` provides network, command-line, and eventually interactive
interfaces to the material data and optical models in [`xmdm`](../xmdm/).
The server package is a separate distribution; it should use `xmdm`'s public
database and model APIs rather than reimplementing its schema or numerical
behavior.

The project has shared JSON/SQLite services, HTTP and MCP interfaces,
explicit SQLite import/export/backup workflows, revisioned records,
bearer-token authorization, and a browser spectra explorer with verified
uploads staged for administrator review. MCP is available over stdio or
Streamable HTTP alongside the web server. Bundled/custom `xmdm` JSON databases
remain import sources and the interchange format. Asynchronous jobs, fitting,
Lumerical export, user accounts, and multi-record comparison are not
implemented.

## Goals and boundaries

### Current implementation

- Serve material and record catalog data from JSON or SQLite.
- Provide HTTP operations for catalog discovery, revision access,
  optical-property evaluation, transient resampling, and authorized mutation.
- Expose shared reads and compute operations through stdio or HTTP MCP; require
  scoped bearer authorization before staging submissions.
- Provide a CLI for server/database operation and local token management, plus
  a browser UI for catalog browsing and n/k or epsilon spectra.
- Keep request handling, validation, and response behavior consistent across
  HTTP and MCP by sharing service functions.

### Deferred work

- Asynchronous fitting or conversion jobs.
- Multi-record comparison.
- Lumerical export until the target format and metadata fidelity are specified.
- Additional data formats and physical-property domains.

The local server remains read-only when configured with a JSON directory.
SQLite writes require bearer tokens with explicit scopes.

## Design principles

- Treat SQLite as the server's authoritative storage after migration, and
  `xmdm` as the source of truth for interchange payload validation and
  material-model calculations. See the
  [database schema](../xmdm/src/xmdm-db/README.md).
- Keep reads, evaluation, and transient resampling available without enabling
  writes. Local initialization/import and authenticated remote mutation have
  explicit, separate lifecycles.
- Keep core server operations independent of the HTTP framework and MCP
  transport so both interfaces share the same validation and errors.
- Do not infer missing metadata or silently fall back to another database.
- Bound list sizes and evaluation input sizes; return explicit validation
  errors for unsupported models, parameters, units, and interpolation options.
- Keep deployment concerns such as process supervision, TLS, and secrets
  outside the CLI's responsibility.

## Proposed package layout

```text
xmdm-server/
├── src/xmdm_server/
│   ├── __init__.py
│   ├── __main__.py
│   ├── config.py          # database backend and server settings
│   ├── services/          # shared catalog, record, and evaluation operations
│   ├── api/v1/            # HTTP application and routes
│   ├── mcp/               # MCP tools and server entry point
│   ├── web/static/        # browser interface
│   ├── db/                # SQLite repository and migrations
│   └── cli/               # command-line interface
├── tests/
│   ├── test_services.py
│   ├── test_api.py
│   ├── test_mcp.py
│   └── test_cli.py
└── docs/
```

Keep the layout modest as implementation proceeds; split modules only when
they acquire distinct responsibilities.

## Data access and configuration

### SQLite ownership and migration

- In SQLite mode, `--db PATH` identifies a database **file**, not a JSON
  directory. Preserve the prototype's directory mode during an explicit
  migration window; do not silently reinterpret paths or initialize empty
  databases when configured files are missing.
- `xmdm db init --db PATH` creates a new SQLite file and imports the bundled
  `xmdm` catalog. `--empty` creates only the schema. Refuse to overwrite an
  existing file. `db import --source JSON_ROOT --db PATH` explicitly imports a
  custom database; `db export` reconstructs the material-first JSON format.
- Track SQLite migrations separately from `xmdm` record
  `schema_version="1"`. Refuse newer, unsupported storage schema versions.
- Put SQL and transactions in a repository module used by shared services.
  HTTP and MCP must not open arbitrary client-selected files.
- Adapt validated record payloads into `xmdm` numerical objects in memory.
  Existing `from_db()` functions read JSON directories and cannot simply
  receive a SQLite filename. Reuse numerical constructors and extract a
  shared payload-loading adapter where necessary; do not duplicate
  interpolation mathematics in the server.

### Proposed tables

Use relational columns for identity, lookup, and revisions; retain
model-dependent `data` and extensible `metadata` as JSON rather than making one
wide table for all dispersion coefficients.

| Table | Principal columns and constraints | Purpose |
| --- | --- | --- |
| `schema_migrations` | `version INTEGER PRIMARY KEY`, `applied_at TEXT NOT NULL` | Server storage migrations, separate from record schema versions. |
| `materials` | `id TEXT PRIMARY KEY`, `name TEXT NOT NULL`, `normalized_id TEXT UNIQUE NOT NULL`, `normalized_name TEXT NOT NULL`, `created_at TEXT NOT NULL` | Stable material IDs and display names; names need not be globally unique. |
| `material_aliases` | `material_id TEXT REFERENCES materials(id)`, `alias TEXT`, `normalized_alias TEXT`; primary key `(material_id, normalized_alias)` | Indexed normalized alias lookup; shared aliases produce ambiguity errors. |
| `records` | `id TEXT PRIMARY KEY`, `material_id TEXT NOT NULL REFERENCES materials(id)`, `current_revision INTEGER NOT NULL CHECK(current_revision >= 1)`, `created_at TEXT NOT NULL` | Server-global UUID and pointer to the latest immutable revision. |
| `record_revisions` | `record_id TEXT REFERENCES records(id)`, `revision INTEGER`, `name TEXT NOT NULL`, `normalized_name TEXT NOT NULL`, `physics TEXT NOT NULL`, `model TEXT NOT NULL`, `schema_version TEXT NOT NULL`, `data_json TEXT NOT NULL`, `metadata_json TEXT NOT NULL`, `payload_sha256 TEXT NOT NULL`, `created_at TEXT NOT NULL`; primary key `(record_id, revision)` | Immutable data and metadata; validate JSON objects and the complete `xmdm` payload before committing. |
| `record_derivations` | `record_id TEXT`, `revision INTEGER`, `source_record_id TEXT`, `source_revision INTEGER`, `operation TEXT`, `parameters_json TEXT NOT NULL`; primary key `(record_id, revision)` and foreign keys to both revision pairs | Reproducible lineage for persisted resampling or later fitting, including coordinates, units, property, interpolation, and range policy. |
| `import_records` | `import_key TEXT PRIMARY KEY`, `source_record_id TEXT NOT NULL`, `source_material_id TEXT NOT NULL`, `record_id TEXT NOT NULL REFERENCES records(id)`, `source_sha256 TEXT NOT NULL` | Idempotent import mapping and original identities, including legacy UUID collisions. |

The SQLite migrations define these tables and structural constraints, plus
token and audit tables for scoped administration. Payload validation and
service-level write invariants are enforced by the repository and services.
Invariants:

- Enforce foreign keys on every connection; use a deferred composite foreign
  key from `(records.id, current_revision)` to `record_revisions`. Create a
  record and its first revision in one transaction.
- Require positive revision numbers, non-empty identities, valid UUIDs, and
  valid JSON objects. JSON checks alone are insufficient: use `xmdm` validation
  for model coefficients, finite numbers, arrays, and payload schema versions.
- Index normalized material names and aliases, revision names, and
  `(physics, model)`. Human selector queries join only current revisions.
- Reject duplicate normalized current
  `(material_id, name, physics, model)` selectors inside the write transaction.
  Different models with the same name are valid and require disambiguation.
- Preserve imported UUIDs when globally unique. For collisions across material
  directories, allocate a new server UUID and retain the original identity in
  `import_records`; never merge solely because UUIDs match. An import key
  combines a stable source namespace, material ID, and source record ID.
  Reimporting identical payloads is a no-op; changed content requires an
  explicit new-revision policy.
- Store UTC server timestamps separately from source dates in metadata. Do not
  invent absent authors, dates, or citations. Hash canonical payload JSON for
  import comparison and provenance; hashes do not replace record IDs.
- Use short write transactions, a bounded busy timeout, and WAL for local
  deployments. Use SQLite's backup API for live backups rather than copying
  only the main file during WAL writes. Avoid network-filesystem deployments.
- Store token digests and audit events in SQLite, never plaintext bearer
  tokens; job tables remain deferred because no job lifecycle is implemented.

## HTTP API

Use a versioned `/api/v1` prefix. All routes below are implemented; write and
administration routes require appropriately scoped bearer tokens. A revision
parameter selects an immutable stored revision; omission selects the current
revision.

| Method and path | Purpose and result | Status / access |
| --- | --- | --- |
| `GET /api/v1/health` | Report readiness and storage availability; unavailable storage returns 503. | Read |
| `GET /api/v1/materials` | Paginated search using `query`, `limit`, `offset`, `physics`, and `model` filters based on matching current records. | Read |
| `GET /api/v1/materials/{material_id}` | Material metadata, aliases, and current record summaries. | Read |
| `GET /api/v1/records` | Paginated search using `query`, `material_id`, `model`, `limit`, `offset`, and `physics`. | Read |
| `GET /api/v1/records/{record_id}` | Full `xmdm` payload for a UUID, optionally `revision`; server revision information is in a separate envelope. | Read |
| `GET /api/v1/records/{record_id}/revisions` | Revision history summaries for a record. | Read |
| `GET /api/v1/records/{record_id}/data` | Original model data only, optionally `revision`; no implicit interpolation. | Read |
| `GET /api/v1/records/{record_id}/metadata` | Source metadata only, optionally `revision`; do not manufacture missing fields. | Read |
| `GET /api/v1/records/{record_id}/provenance` | Revision identity, payload hash, import identity, and derivation source/parameters. | Read |
| `GET /api/v1/records/{record_id}/export?format=json\|csv\|yaml` | Download a revision. JSON/YAML preserve the payload; CSV requires tabulated data. Unsupported conversions are rejected. | Read |
| `GET /api/v1/records/{material_id}/{record_name}` | Resolve a human selector, optionally `model`; return 409 when ambiguous. Retain compatibility with the existing raw-payload response. | Read |
| `POST /api/v1/evaluate` | Return complex values at supplied coordinates using a human selector or UUID/revision. No record is created. | Compute |
| `POST /api/v1/records/{record_id}/resample` | Return a transient tabulated `xmdm` record at supplied coordinates with pinned source revision and operation metadata. No storage mutation. | Compute |
| `POST /api/v1/submissions` | Verify a payload with `material_id`, optionally derivation details, and create a pending submission; return 202. | `records:write` |
| `PUT /api/v1/records/{record_id}` | Verify and stage a full replacement with `If-Match`; return 412 for stale edits. Approval creates the revision. | `records:write` |
| `GET /api/v1/admin/submissions`, `POST .../{submission_id}/approve`, `POST .../{submission_id}/reject` | List pending submissions and approve or reject them. Approval publishes atomically; rejection stores the decision. | `tokens:admin` |
| `POST /api/v1/records/{record_id}/validate` | Validate an existing revision and return structured errors/warnings without mutation. | Compute |
| `GET /api/v1/admin/tokens`, `POST /api/v1/admin/tokens`, `DELETE /api/v1/admin/tokens/{token_id}` | List/create/revoke token metadata; secrets are returned only at creation. | `tokens:admin` |
| `GET /api/v1/admin/audit` | Read bounded audit events. | `tokens:admin` |

Use `PUT`, not `POST /records/{record_id}`, for full replacement. Partial
updates remain deferred. Record deletion uses reversible soft archiving so
immutable revisions and provenance are retained.
Register `/data`, `/metadata`, `/provenance`, `/export`, and `/resample` before
the legacy two-segment selector route so static subpaths are not mistaken for
material/name lookups.

### Interpolated records

Yes: `xmdm.Material.interp()` already computes interpolated complex values for
tabulated sources; analytic models provide `n()` and `eps()` evaluations.
`/evaluate` returns values only. `/resample` packages those
values as a **new tabulated record**, not changed source measurements or
modified analytic coefficients.

Example request to `POST /api/v1/records/{record_id}/resample`:

```json
{
  "coordinates": [450, 550, 650],
  "unit": "nm",
  "parameter": "n",
  "interpolation": "linear",
  "range_policy": "clip",
  "revision": 1
}
```

- Resolve and pin the source revision before computation. Delegate unit and
  property conversion to `xmdm`; preserve coordinate order and repeated
  coordinates in `data.f`.
- Support `linear`/`cubic` for tabulated sources. For analytic sources,
  interpolation is not applicable: omit it or accept only the default.
- Support explicit `clip` (matching current `xmdm` defaults), `error`, and
  `extrapolate` range policies for tabulated sources. Record clipping and
  extrapolation warnings. Do not invent validity ranges for analytic models.
- Return an envelope containing `record`, `source`, and `operation`. `record`
  has schema version `"1"`, a fresh UUID, `physics="optics"`,
  `model="tabulated"`, a derived name, `data.unit`, `data.type` (`n` or `eps`),
  `data.f`, `data.re`, `data.im`, and source metadata with explicit derivation
  information. Do not copy unrelated `additional_columns` unchanged.
- `source` identifies UUID, revision, and payload hash; `operation` records
  the request, numerical library version, and warnings. Repeated computations
  may have different transient UUIDs but equivalent data.
- No persistence or authentication is required for this read-only computation.
  Submission is separately authenticated through `POST /submissions`; verify
  lineage against the pinned source and save it in `record_derivations` only
  when an administrator approves the submission.
  Client-supplied provenance is not automatically verified evidence.
- Retain finite-number and 10,000-point limits. Test conversion, order,
  repeated coordinates, clipping, extrapolation, analytic sampling, and JSON
  round-trip validation.


### API behavior

- Use URL path segments for material and record selectors; clients must encode
  reserved characters. A `material_id` plus `record_name` path avoids treating
  the slash in an `xmdm` selector as an ambiguous single path parameter.
- For evaluation, accept a selector (`material_id`, `record_name`, and model),
  a non-empty list of coordinates, their supported spectral unit, and the
  model-specific parameter selection. Validate the complete request before
  evaluating it.
- Return metadata and JSON-compatible numeric results. Preserve the requested
  coordinate order and make the output parameter and units explicit.
- Define stable error responses for malformed requests, invalid selectors,
  missing records, ambiguous lookups, unsupported options, and database
  failures. Use appropriate HTTP status codes rather than success-shaped
  fallback responses.
- Use a documented maximum page size and maximum number of evaluation points.
  Return pagination metadata with list responses.
- Authentication is required for SQLite writes and token administration;
  reads/evaluation remain public. CORS and public internet deployment policy
  remain deployment-specific.


## MCP interface

Agents work best with a small set of purpose-built, well-described tools and
resources.

### MCP tools

| Tool and principal arguments | Result / matching REST operation | Status / access |
| --- | --- | --- |
| `list_materials(query?, physics?, model?, limit?, offset?)` | Paginated material summaries; `GET /materials`. | Read |
| `get_material(material_id)` | Material metadata and current record summaries; `GET /materials/{material_id}`. | Read |
| `list_records(query?, material_id?, physics?, model?, limit?, offset?)` | Paginated current record summaries; `GET /records`. | Read |
| `get_record(record_id?, revision?, material_id?, record_name?, model?)` | Full payload and revision envelope via UUID or human selector; retain the existing human-selector result shape. | Read |
| `evaluate_record(selector, coordinates, unit, parameter, interpolation?)` | Coordinate-ordered real/imaginary values; `POST /evaluate`. | Compute |
| `resample_record(selector, coordinates, unit, parameter, interpolation?, range_policy?)` | Transient tabulated record plus provenance; `POST /records/{record_id}/resample`. | Compute |
| `validate_record(record_id, revision?)` | Validation errors and warnings for an existing revision. | Compute |
| `submit_record(material_id, payload, derivation?)` | Verify and stage a record for review; return the pending submission ID. | `records:write`; stdio startup token or HTTP request bearer |

`selector` abbreviates UUID/revision or material/name/model arguments; publish
an explicit typed input schema, not an unstructured string/dictionary. Keep
existing tool names rather than adding synonyms. Both transports use the same
repository, validation, and numerical services. Register write tools only when
writes are enabled and the caller has the required scope. Mark reads/compute
as read-only in MCP annotations, but enforce authorization independently.
The stdio transport registers submission only with a valid scoped startup
token; HTTP MCP exposes it but validates a scoped bearer token per request.
Return actionable expected errors; log internal failures without exposing
filesystem paths.

### MCP resources and resource templates

| Resource URI/template | Content | Status |
| --- | --- | --- |
| `xmdm://materials?limit={limit}&offset={offset}` | Bounded page of material summaries with detail links and next-page information. | Implemented |
| `xmdm://materials/{material_id}` | Material metadata and current record summaries. | Implemented |
| `xmdm://records?limit={limit}&offset={offset}` | Bounded page of current record summaries; use tools for filtered search. | Implemented |
| `xmdm://records/{record_id}` | Full current record and revision envelope. | Implemented |
| `xmdm://records/{record_id}/revisions/{revision}` | Full immutable revision. | Implemented |
| `xmdm://records/{record_id}/data?revision={revision}` | Original model data as JSON. | Implemented |
| `xmdm://records/{record_id}/metadata?revision={revision}` | Source metadata as JSON. | Implemented |
| `xmdm://records/{record_id}/provenance?revision={revision}` | Source/import identity, revision hash, and derivation lineage. | Implemented |

Use paginated catalogs, not unbounded dumps. URI variables are percent-encoded;
resources are JSON with explicit revision information. Latest resources may
change after writes; revision resources are immutable. Numerical requests with
large coordinate arrays remain tools, not encoded resource URIs. Transient
resampled records become addressable resources only after explicit persistence.

## CLI and runtime

Provide a small CLI for configuration and local operation:

```bash
xmdm --help
xmdm --version
xmdm server [--help] [--host HOST] [--port PORT] [--db PATH]
xmdm mcp [--help] [--db PATH]
xmdm verify [--db PATH]
xmdm db [--help] init|migrate|import|export|backup [options]
xmdm admin token create|list|revoke|audit [options]
```

- `server` starts the HTTP application; `mcp` runs the MCP transport appropriate
  for local clients (stdio by default); `verify` validates database access and
  exits with a non-zero status on failure.
- `server --mcp` mounts Streamable HTTP MCP at `/mcp/`; configure
  `XMDM_MCP_ALLOWED_HOSTS` and `XMDM_MCP_ALLOWED_ORIGINS` for trusted remote
  names/origins while retaining DNS-rebinding protection.
- Support equivalent settings through documented environment variables where
  useful, with explicit precedence between command-line arguments, environment,
  and defaults.
- Do not implement `stop` or `restart` commands; use the operating system's
  service manager or container runtime for process lifecycle.
- Keep logs on stderr and reserve stdout for protocol traffic when running MCP
  over stdio.
- Local `db init|migrate|import|export|backup` commands manage SQLite. Token
  administration is available through local `admin token` commands.
- `xmdm db` manages schema and data import/export. `init --empty` creates
  schema only; it is not a generic flag for migration or export.
- `xmdm admin token create` accepts one or more scopes and an optional expiration; `list`, `revoke`, and `audit` operate on a local database.

## Web UI

The browser UI is served on separate `/data`, `/upload`, `/admin`, and
`/status` pages and calls the HTTP API. It provides:

- Material search and record browsing.
- Record metadata and provenance display.
- Interactive plots of supported optical properties against wavelength or
  another requested spectral coordinate.
- Upload preview from pasted three-column data or multiple CSV/TXT/JSON files,
  with material, property kind, unit, and source metadata selection.
- Submission with a `records:write` token and an administrator review queue
  using a separate `tokens:admin` token. Tokens are held only in page inputs.
- Search and show pending submission payloads; archive and restore published
  records without deleting their immutable histories.
- Server health and published catalog counts.
- Multi-record comparison remains a possible follow-up.

## Implementation milestones

Milestones 1-6 describe implemented capabilities and deferred decisions.

### 1. Package and shared services

- [x] Define server package metadata, runtime dependencies, and console entry
  points.
- [x] Add typed configuration for the database root and runtime settings.
- [x] Implement shared catalog, record-detail, and evaluation service
  operations using `xmdm` APIs.
- [x] Normalize expected lookup and validation failures into transport-neutral
  service errors; preserve unexpected failures for explicit logging.
- [x] Test custom database access, missing records, invalid
  requests, and output serialization.

**Done when:** shared operations work without an HTTP or MCP transport, use
both bundled and custom databases, and have tests for success and failure
cases.

### 2. Read-only HTTP API

- [x] Implement the versioned endpoints and documented request/response
  schemas.
- [x] Add pagination and input-size limits.
- [x] Map service errors to stable HTTP error responses.
- [x] Test route behavior, status codes, response schemas, and database errors
  with an in-process client.

**Done when:** every initial API operation has request, success, and failure
coverage and the API contract is documented.

### 3. MCP and CLI

- [x] Add MCP tools backed by the shared services.
- [x] Add `server`, `mcp`, `verify`, `--help`, and `--version` commands.
- [x] Verify stdout/stderr behavior for stdio MCP and configuration precedence.
- [x] Test MCP tool results and errors, CLI argument parsing, and non-zero
  failure exits.

**Done when:** HTTP and MCP return equivalent service results for equivalent
inputs, and the CLI can validate a database and launch each supported mode.

### 4. Packaging and release readiness

- [x] Build and install the server wheel into a clean target; verify its CLI,
  declared dependency metadata, and operation with the dependency-complete
  `dev-2026.1` environment.
- [x] Document local setup, custom database configuration, API usage, MCP
  setup, and security considerations for deployment.
- [x] Run the server test suite and a smoke test against the bundled database.

**Done when:** a fresh wheel install can configure and run the server with its
declared runtime dependencies, and the published instructions cover setup and
use.

### 5. SQLite and derived records

- [x] Define the initial SQLite schema and migration/connection foundation;
  initialization is explicit and existing files are not overwritten.
- [x] Integrate a service-facing repository and explicit file-based
  configuration without silently changing existing JSON-directory behavior.
- [x] Add local initialization, import, export, verification, and backup
  workflows; test UUID collision handling and idempotent import.
- [x] Adapt validated SQLite payloads to `xmdm` numerical objects in memory.
- [x] Add UUID/revision REST access and matching MCP tools/resources.
- [x] Add transient resampling with explicit range policy, provenance,
  coordinate-order preservation, and no implicit writes.
- [x] Verify JSON export/import round trips, revision consistency, storage
  errors, and equivalent REST/MCP outputs against the same SQLite fixtures.

### 6. Deferred capabilities

- [x] Define bearer-token authentication, `records:write` and `tokens:admin`
  scopes, token hashing/expiry/revocation, payload validation, and audit
  requirements; implement authenticated staged uploads and the HTTP token and
  submission-review APIs.
- [x] Defer asynchronous fitting/jobs: no fitting operation or job consumer is
  specified. No job persistence, cancellation, or status API is exposed.
- [x] Define JSON, JSON-as-YAML 1.2, and tabulated CSV export. Reject
  Lumerical conversion until its layout and metadata requirements are defined.
- [x] Build a browser UI over the HTTP API for catalog search, record metadata
  and revisions, interactive n/k or epsilon spectra, upload preview, and
  administrator review. Multi-record comparison remains deferred.
- [x] Stage verified new records and revisions for review; publish approval
  atomically and reject stale pending revisions without losing submissions.
- [x] Expose Streamable HTTP MCP alongside the web server with public reads,
  per-request upload authorization, and configurable host/origin allowlists.
- [x] Split the browser UI into data, upload, admin, and status pages; add
  reversible admin record archiving while retaining revisions and audit history.

## Verification expectations

- Test against both the bundled database and the small synthetic database in
  `xmdm/tests/custom-db`.
- Include negative tests for unknown and ambiguous selectors, unsupported
  models and units, malformed payloads, and invalid database configuration.
- Check that outputs contain only JSON-serializable values and do not leak
  local filesystem paths or internal exception details.
- Test API and MCP operations against the same service-level expectations.
- Keep the server tests independent of network access and external services.


## Potential use cases

- Browse material sources and compare their optical properties.
- Sample a measured record or analytic model onto a simulation's spectral grid.
- Export a derived tabulated record with traceable source and interpolation
  settings, without altering the original measurements.
- Import bundled/custom material records into a local SQLite catalog.
- Let an MCP client retrieve records and evaluate or resample them with the
  same semantics as REST clients.
