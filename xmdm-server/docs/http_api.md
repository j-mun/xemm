# HTTP API

The versioned API is rooted at `/api/v1`. Reads and compute operations work
with the bundled/custom JSON directory or an explicitly configured SQLite
database. Writes and token administration are supported only with SQLite.
`xmdm server` serves separate pages at `/data`, `/upload`, `/admin`, and
`/status`; `/` redirects to `/data`. The UI uses these HTTP routes and does not
access database files directly.

## Endpoints

Paths in the table are relative to `/api/v1`. `record_id` is the server UUID.
`revision` selects an immutable revision; omission selects the current
revision. `limit` defaults to 100 and is bounded to 1–1000; `offset` defaults
to 0 and must be nonnegative.

| Method and path | Parameters / body | Access | Use case |
| --- | --- | --- | --- |
| `GET /health` | — | Public | Confirm that the configured data source is available. |
| `GET /materials` | `query?`, `physics?`, `model?`, `limit?`, `offset?` | Public | Search and page through materials; domain/model filters require matching current records. |
| `GET /materials/{material_id}` | Material ID or alias | Public | Inspect material metadata, aliases, and current record summaries. |
| `GET /records` | `query?`, `material_id?`, `physics?`, `model?`, `limit?`, `offset?` | Public | Search and page through current records. |
| `GET /records/{record_id}` | `revision?` | Public | Read a full record payload and revision envelope by UUID. |
| `GET /records/{record_id}/revisions` | — | Public | Review immutable revision history. |
| `GET /records/{record_id}/data` | `revision?` | Public | Retrieve a revision's model data only. |
| `GET /records/{record_id}/metadata` | `revision?` | Public | Retrieve a revision's source metadata only. |
| `GET /records/{record_id}/provenance` | `revision?` | Public | Inspect import identity, payload hash, and derivation details. |
| `GET /records/{record_id}/export` | `format=json\|yaml\|csv\|lumerical`, `revision?` | Public | Download an export; unsupported Lumerical conversion is rejected. |
| `GET /records/{material_id}/{record_name}` | `model?`, `physics?` | Public | Look up a record with its familiar material/name selector. |
| `POST /evaluate` | Evaluation request JSON | Public | Evaluate an analytic or tabulated model at requested coordinates. |
| `POST /records/{record_id}/resample` | Resampling request JSON | Public | Generate a transient tabulated record with provenance; no write occurs. |
| `POST /records/{record_id}/validate` | `revision?` | Public | Validate a stored payload and return errors/warnings. |
| `POST /submissions` | `{ "material_id": "...", "payload": {...}, "material_name"?, "derivation"? }` | `records:write` | Verify and stage a new record for administrator review; optional material name proposes a new material. Returns 202. |
| `PUT /records/{record_id}` | `{ "payload": {...}, "derivation"? }`, `If-Match: "N"` | `records:write` | Verify and stage a revision if the supplied current revision matches; returns 202. |
| `GET /admin/submissions` | `status?` (`pending` by default), `limit?` | `tokens:admin` | List pending or reviewed submissions for moderation. |
| `POST /admin/submissions/{submission_id}/approve` | Optional `{ "note"? }` | `tokens:admin` | Publish an accepted submission as a new record or revision. |
| `POST /admin/submissions/{submission_id}/reject` | Optional `{ "note"? }` | `tokens:admin` | Reject a submission without publishing it. |
| `GET /admin/records` | `query?`, `limit?` | `tokens:admin` | Search published and archived records. |
| `DELETE /admin/records/{record_id}` | — | `tokens:admin` | Archive a record from public catalog views while retaining its immutable history. |
| `POST /admin/records/{record_id}/restore` | — | `tokens:admin` | Restore an archived record; fails if its selector now conflicts with another published record. |
| `GET /admin/tokens` | — | `tokens:admin` | List token metadata without exposing secrets. |
| `POST /admin/tokens` | `{ "name": "...", "scopes": [...], "expires_at"? }` | `tokens:admin` | Create a scoped token; return the secret once. |
| `DELETE /admin/tokens/{token_id}` | — | `tokens:admin` | Revoke a token. |
| `GET /admin/audit` | `limit?` | `tokens:admin` | Inspect recent token and record mutation events. |

Catalog list responses contain `items`, `total`, `limit`, and `offset`. Admin
audit, submission, and record responses contain `items`. The browser routes
serve separate data, upload, admin, and status pages; `/static/app.js` and
`/static/style.css` serve shared assets.

## Common workflows

### Browse and identify a record

1. Call `GET /materials?query=...` or `GET /records?query=...`.
2. Read material details or a record by UUID.
3. If using the human selector route, provide `model` (and optionally
   `physics`) when a name is ambiguous. Ambiguous selectors return 409.
4. Use the record UUID for revision-pinned data, metadata, provenance,
   validation, resampling, or export.

For example:

```http
GET /api/v1/records/Ag/Johnson?model=tabulated
```

### Evaluate and plot

`POST /evaluate` accepts either a human selector (`material_id`,
`record_name`, and `model`) or `record_id`, with optional `revision`, plus
coordinates, unit, parameter, and interpolation:

```json
{
  "record_id": "00000000-0000-0000-0000-000000000001",
  "revision": 1,
  "coordinates": [450, 550, 650],
  "unit": "nm",
  "parameter": "n",
  "interpolation": "cubic"
}
```

Coordinates must be non-empty, finite, and limited to 10,000. Supported units
are `m`, `nm`, `um`, `Hz`, `GHz`, `THz`, `cm-1`, and `eV`; parameters are `n`
(complex refractive index), `e` (complex relative permittivity), `k`
(extinction coefficient), and `n2` (tabulated nonlinear index coefficient).
`k` can be evaluated from tabulated `n`/`nk` or `k` data and analytic models;
`n2` requires a tabulated `n2` record. Nonlinear records use `physics="nlo"`;
use `GET /records?physics=nlo` to find them and `parameter="n2"` to evaluate
them. Tabulated records support `linear` and
`cubic`; analytic models accept the default `linear`. The result returns
coordinates in input order and complex values as `real`/`imag` pairs.

For transient resampling, the body uses the same coordinates, unit, parameter,
and interpolation fields, plus `range_policy` (`clip`, `error`, or
`extrapolate`) and optional `revision`. The result contains a generated
tabulated `record`, pinned `source` UUID/revision/hash, and `operation`
parameters and warnings. It preserves coordinate order and duplicates and
does not change database state. Resampled `n2` records use `physics="nlo"`.

### Export and validation

`format=json` preserves the XMDM record payload; `yaml` is emitted as JSON
syntax, valid YAML 1.2; `csv` is for tabulated records and contains coordinate,
real, and imaginary columns. `lumerical` is recognized but rejected because
its output layout and metadata fidelity are not specified. JSON catalog
exports contain current revisions; use a SQLite backup to retain all history.

`POST /records/{record_id}/validate?revision=N` checks an existing revision
without mutation and returns `valid`, `errors`, and `warnings`.

### Submit and review uploads

Uploads require a SQLite-backed service and a bearer token with
`records:write`. `POST /submissions` verifies the complete XMDM payload before
storing it as pending; it does not make the record visible in catalog reads.
For a new material, include `material_name` alongside a new `material_id` and
`payload`. The ID must be a non-empty directory name without path separators.
Omit `material_name` when uploading to an existing material. Both the new
material and its first record remain unpublished until approval; rejection
creates neither. The Upload page offers existing/new destinations and fields
for the new ID and display name.

On the Data page, searching also filters the material dropdown; clearing the
search restores all materials.

Use `PUT /records/{record_id}` with the current `If-Match: "N"` revision to
stage a replacement. A stale revision returns 412 before staging, and approval
checks the revision again to prevent lost updates.

An administrator uses a separate token with `tokens:admin` to list pending
submissions and approve or reject them. Approval publishes a new record or
revision atomically; rejection records the decision and optional note without
changing the catalog. Review decisions and submissions are audited. The
legacy `POST /records` path is an undocumented alias for `POST /submissions`
and also returns 202.

### Archive and restore records

The admin page can search records and archive a published record using
`DELETE /admin/records/{record_id}`. This is a soft delete: the record
disappears from public catalog/search and record-detail routes, while its
revisions, provenance, submissions, and audit history remain stored. A
`tokens:admin` caller can restore it with
`POST /admin/records/{record_id}/restore`. Restore fails with 400 if another
published record has taken the same material/name/physics/model selector.
SQLite JSON exports include only currently published records; backups retain
archived records and history.

### Authorize writes

Create the initial admin token locally so no unauthenticated HTTP bootstrap
path is needed:

```bash
xmdm admin token create --db ./materials.sqlite --name administrator \
  --scope tokens:admin --scope records:write
```

To authorize a request, put the returned secret in its HTTP Authorization
header using the bearer authentication scheme. Upload staging requires
`records:write`; token listing/creation/revocation, submission review, and
audit access require `tokens:admin`. Use separate credentials for submitters
and reviewers. Token secrets are high entropy, shown only at creation, and
stored as SHA-256 digests. Expiration timestamps must be future, timezone-aware
ISO 8601 values. Submissions, review decisions, and token create/revoke
operations are audited.

For revision submissions, send `If-Match: "N"` with the current revision. A
missing header returns 428; a stale revision returns 412. Staged upload
responses use 202 and include a `submission_id`; the published record UUID and
revision are returned only after approval. Reads and evaluation are public.
An HTTP server using a JSON directory remains read-only.

### Streamable HTTP MCP

Start MCP alongside the web/API server with `xmdm server --mcp`; its endpoint
is `/mcp/`. MCP reads are public, while `submit_record` requires a
`records:write` bearer token on each HTTP request and creates a pending
submission. The HTTP transport validates `Host` and `Origin` headers to
mitigate DNS rebinding. Localhost is allowed by default. For a remote reverse
proxy or a custom hostname, set comma-separated `XMDM_MCP_ALLOWED_HOSTS`
patterns (for example `materials.example.org:*`) and, when needed,
`XMDM_MCP_ALLOWED_ORIGINS` origins (for example
`https://materials.example.org`). Keep the allowlist narrow and use TLS.

## Errors and limits

| Status | Meaning |
| --- | --- |
| 400 | Invalid selector, unsupported operation, or invalid `If-Match` syntax. |
| 401 | Missing, invalid, expired, or revoked bearer token. |
| 403 | Valid token lacks the required scope. |
| 404 | Material or record does not exist. |
| 409 | Human selector is ambiguous. |
| 412 | `If-Match` revision is stale. |
| 421 | MCP HTTP request has an unapproved `Host` or `Origin`. |
| 422 | Request body or FastAPI query constraints are invalid. |
| 428 | Required `If-Match` header is missing. |
| 503 | Configured database is unavailable. |
| 500 | Unexpected internal database/service failure; details are logged, not returned. |

The API binds to `127.0.0.1:8000` by default. Configure a trusted network
boundary and TLS before exposing it beyond localhost. MCP additionally
requires explicit remote host/origin allowlisting.
