# Database storage

`xmdm-server` uses the XMDM material-first JSON database as an import/export
format and SQLite as its revisioned writable backend. The two schemas serve
different purposes: record payloads retain the XMDM record schema, while
SQLite tables index identity, revisions, import mappings, tokens, and audit
events.

## Choosing and initializing a backend

- JSON mode points `--db` at an existing material-first JSON directory and is
  read-only through HTTP/MCP.
- SQLite mode points `--db` at an initialized SQLite file. HTTP record writes
  and token administration require this backend.
- `xmdm db init --db FILE` creates a new SQLite database and imports the
  bundled XMDM catalog. It refuses to overwrite an existing file.
- `xmdm db init --db FILE --empty` creates schema only. Import additional JSON
  with `xmdm db import`.
- `xmdm db migrate` applies supported migrations to an existing database.
- A missing configured path is an error; it is not implicitly initialized.

Storage schema versions are tracked in `schema_migrations`, independently from
the XMDM record payload's `schema_version` (currently `"1"`). Unsupported
future storage versions and inconsistent migration histories are rejected.

XMDM records may use tabulated data or the analytic `drude`, `lorentz`,
`sellmeier`, `cauchy`, and `rii_formula` models. Tabulated property types
include `n`, `nk`, `e`/`eps`, `k`, and `n2`; formulas 1–9 retain the
RefractiveIndex.INFO coefficient order and optional wavelength range.
Nonlinear `n2` records use `physics="nlo"`; linear optical records use
`physics="optics"`. Import/export retains this record-level classification,
and resampled `n2` records also use `nlo`.

## SQLite schema

The current storage schema version is 5. Columns shown as JSON contain
canonical JSON text; timestamps are UTC ISO 8601 strings.

| Table | Columns and constraints | Purpose |
| --- | --- | --- |
| `schema_migrations` | `version INTEGER PRIMARY KEY`, positive; `applied_at TEXT NOT NULL` | Applied storage migration history. |
| `materials` | `id TEXT PRIMARY KEY`; `name TEXT NOT NULL`; `normalized_id TEXT UNIQUE NOT NULL`; `normalized_name TEXT NOT NULL`; `created_at TEXT NOT NULL` | Stable material identity and searchable normalized names. |
| `material_aliases` | `material_id TEXT REFERENCES materials(id)`; `alias TEXT NOT NULL`; `normalized_alias TEXT NOT NULL`; primary key `(material_id, normalized_alias)` | Material aliases; normalized aliases may identify ambiguous matches across materials. |
| `records` | `id TEXT PRIMARY KEY`; `material_id TEXT REFERENCES materials(id)`; `current_revision INTEGER CHECK >= 1`; `created_at TEXT NOT NULL`; nullable `deleted_at TEXT`; deferred FK `(id, current_revision)` to `record_revisions(record_id, revision)` | Stable server UUID, current immutable revision, and optional soft-archive timestamp. |
| `record_revisions` | `record_id TEXT REFERENCES records(id)`; `revision INTEGER CHECK >= 1`; `name`, `normalized_name`, `physics`, `model`, `schema_version`; `data_json`, `metadata_json`; `payload_sha256`; `created_at`; primary key `(record_id, revision)` | Versioned record payload fields and canonical payload hash. JSON columns must be valid JSON objects. |
| `record_derivations` | `(record_id, revision)` primary key/FK to a revision; `source_record_id`, `source_revision` FK to a source revision; `operation`; `parameters_json` object | Provenance for an explicitly persisted derived record. |
| `import_records` | `import_key TEXT PRIMARY KEY`; source record/material IDs; `record_id REFERENCES records(id)`; `source_sha256` | Idempotent import mapping and source identity, including UUID collisions. |
| `api_tokens` | `token_id TEXT PRIMARY KEY`; unique 64-character `token_hash`; `name`; `scopes_json` array; `created_at`; nullable `expires_at`, `revoked_at` | Token metadata and a one-way digest; plaintext secrets are never persisted. |
| `audit_events` | integer `event_id PRIMARY KEY`; nullable `actor_token_id REFERENCES api_tokens`; `action`, `object_type`, `object_id`; `details_json` object; `created_at` | Append-only audit history of token and record mutations. |
| `pending_submissions` | `submission_id TEXT PRIMARY KEY`; nullable `material_id REFERENCES materials`; nullable `new_material_json` object (`id`, `name`), exactly one of these material fields required; nullable `target_record_id REFERENCES records` and `expected_revision`; `payload_json` object; nullable `derivation_json` object; `submitted_by_token_id REFERENCES api_tokens`; `submitted_at`; `status` (`pending`, `accepted`, `rejected`); nullable reviewer token/time/note and accepted record/revision | Verified proposed new records and revisions, held out of the catalog until an administrator accepts them. New materials are also created only upon approval. A status/submission-time index supports review queues. |

Run `xmdm db migrate --db ./materials.sqlite` for an existing SQLite database.
Migration 5 preserves prior submissions and permits pending new-material
proposals without publishing empty materials.

Indexes support normalized material/alias/name lookup, `(physics, model)`
filtering, active/archived record administration, and audit ordering by
creation time.

### Invariants

- Foreign keys are enabled on every repository connection. First revision and
  record identity are created in a single transaction.
- Record UUID/material identity cannot be changed. Current revisions must
  advance, and revision rows cannot be updated or deleted by SQLite triggers.
- Archiving sets `records.deleted_at`; it hides a record from published
  catalog queries but retains revisions, derivations, import mappings, and
  audit history. Restore clears the timestamp after checking selector
  uniqueness.
- Audit rows cannot be updated or deleted by SQLite triggers.
- New and imported payloads are validated with XMDM model validation as well
  as structural and finite-JSON checks. Names, material identity, and the
  current `(material, name, physics, model)` selector are checked before write.
- Payload hashes use canonical JSON (sorted keys, compact separators,
  UTF-8/Unicode retained, non-finite numbers rejected) and SHA-256.
- SQLite connections use foreign-key enforcement, a bounded busy timeout,
  WAL for initialization, and short `BEGIN IMMEDIATE` write transactions.
  Backups use SQLite's online backup API rather than copying the main file.

## Import identity and revisions

Import keys combine a source namespace, material ID, and original record ID.
By default, the namespace is the resolved source directory path. Reimport of
unchanged payloads is a no-op. Changed content is rejected unless
`--on-change new_revision` is selected, in which case the mapped server record
gets a new revision.

An imported UUID is retained if globally unused. If it collides, the server
allocates a UUID and records the original source identity in `import_records`;
UUID equality alone never merges records. Exports reconstruct the
material-first JSON catalog with current revisions only. SQLite backup
preserves full history, import mappings, tokens, and audit data.

## Token and audit data

Token scopes are `records:write` and `tokens:admin`. A token is generated with
a high-entropy `xmdm_` secret, but only its SHA-256 digest is saved. The secret
is returned once from creation. Expired and revoked tokens are not accepted.
Token creation/revocation, submission, review, and publication append audit
events; token and submission administration requires `tokens:admin`.

Uploads are validated before a pending row is inserted. New submissions retain
the selected material identity; revision submissions retain the target record
and expected current revision. Approval revalidates the payload and publishes
the record or revision and changes submission status within one transaction.
If a target revision became stale while pending, approval fails and the
submission remains pending. Rejection records the reviewer, time, and optional
note without publishing data.

## Operational commands

```bash
xmdm db init --db ./materials.sqlite
xmdm db migrate --db ./materials.sqlite
xmdm db import --source /path/to/json-db --db ./materials.sqlite
xmdm verify --db ./materials.sqlite
xmdm db export --db ./materials.sqlite --destination ./json-export
xmdm db backup --db ./materials.sqlite --destination ./backup.sqlite
```

The verify command checks XMDM payload validity, SQLite integrity, and
consistency between record/revision pointers and stored data. Keep SQLite
files on local storage with restrictive filesystem permissions; deployment
processes and TLS are managed outside this package.