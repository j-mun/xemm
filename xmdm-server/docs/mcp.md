# MCP interface

The MCP server exposes the shared XMDM service through tools for interactive
operations and resources for reading catalogs and revision-pinned data. It
runs over stdio for local MCP clients, or over Streamable HTTP mounted on the
same API server.

## Starting the server

```bash
xmdm mcp --db /path/to/material-database --backend json
xmdm mcp --db ./materials.sqlite --backend sqlite
xmdm server --db ./materials.sqlite --backend sqlite --mcp
```

If `--db` or `--backend` is omitted, the same service defaults and path
inference used by the CLI apply. Keep stdout reserved for MCP protocol
messages.

Read and compute operations work with JSON and SQLite. For stdio, writes are
opt-in: set `XMDM_MCP_TOKEN` to a valid SQLite token with the `records:write`
scope before starting the process. The `submit_record` tool is only registered
in that case. An invalid, expired, revoked, or insufficiently scoped configured
token prevents server startup; the server does not silently downgrade.

With `xmdm server --mcp`, public read tools are available over HTTP and
`submit_record` requires a request bearer token with `records:write`. The tool
verifies and stages a pending submission; it does not publish immediately.
HTTP host/origin checks allow localhost by default. Configure
`XMDM_MCP_ALLOWED_HOSTS` and, when needed, `XMDM_MCP_ALLOWED_ORIGINS` for
trusted remote hostnames/origins. The endpoint is `/mcp/`; remote deployments
should use TLS and a narrow allowlist.

## Tools

| Tool | Inputs | Use case |
| --- | --- | --- |
| `list_materials` | `query?`, `limit?`, `offset?`, `physics?`, `model?` | Search and page through materials, optionally requiring current records in a domain/model. |
| `get_material` | `material_id` | Read material metadata, aliases, and current records. |
| `list_records` | `query?`, `model?`, `material_id?`, `limit?`, `offset?`, `physics?` | Search current records and narrow by material or record attributes. |
| `get_record` | UUID selector: `record_id`, `revision?`; or human selector: `material_id`, `record_name`, `model?` | Retrieve a full record and revision envelope, either by stable identity or familiar selector. |
| `evaluate_record` | Human selector or `record_id`/`revision?`; `coordinates`, `unit`, `parameter`, `interpolation?` | Evaluate a model at supplied coordinates and obtain ordered complex values. |
| `resample_record` | `record_id`, `coordinates`, `unit`, `parameter`, `interpolation?`, `range_policy?`, `revision?` | Return a transient tabulated record and provenance without persisting it. |
| `validate_record` | `record_id`, `revision?` | Validate a stored record revision. |
| `submit_record` | `material_id`, `payload`, `derivation?`, `material_name?` | Verify and create a pending submission; include `material_name` to propose a new material, created only upon approval. Requires `records:write` (stdio token at startup, HTTP bearer token per request). |

Search list tools default to 100 results and accept pagination arguments. The
shared service bounds catalog pages and evaluation inputs. Supported spectral
units are `m`, `nm`, `um`, `Hz`, `GHz`, `THz`, `cm-1`, and `eV`; parameters
are `n` (complex refractive index), `e` (complex permittivity), `k` (extinction
coefficient), and `n2` (tabulated nonlinear index coefficient). `n2` requires
tabulated `n2` data. Use `physics="nlo"` in catalog tools to find nonlinear
records and `parameter="n2"` to evaluate them; resampling retains their `nlo`
classification. Tabulated evaluation accepts `linear` or `cubic`;
resampling supports `clip`, `error`, or `extrapolate` range policies.

## Resources

Resource content is JSON text. Page resources use `limit` (default 100) and
`offset` (default 0); use tools when filtered search or numerical computation
is needed.

| Resource URI/template | Content | Use case |
| --- | --- | --- |
| `xmdm://materials?limit={limit}&offset={offset}` | Page of material summaries. | Discover catalog contents and follow up on a material. |
| `xmdm://materials/{material_id}` | Material metadata and current record summaries. | Inspect one material without a tool call. |
| `xmdm://records?limit={limit}&offset={offset}` | Page of current record summaries. | Browse current records. |
| `xmdm://records/{record_id}` | Current full payload and revision envelope. | Read a record at its latest revision. |
| `xmdm://records/{record_id}/revisions/{revision}` | Full immutable revision and envelope. | Reproduce an analysis against a fixed revision. |
| `xmdm://records/{record_id}/data?revision={revision}` | Revision-specific model data. | Retrieve coefficients or tabulated values only. |
| `xmdm://records/{record_id}/metadata?revision={revision}` | Revision-specific source metadata. | Inspect citations and source fields separately. |
| `xmdm://records/{record_id}/provenance?revision={revision}` | Revision hash, import mapping, and derivation lineage. | Trace record origin or derivation. |

The current-record URI may change after a write; a revision URI identifies
immutable content. Large coordinate arrays belong in tool calls, not resource
URIs. A transient resampled result is not addressable as a resource unless it
is explicitly persisted through the authorized write workflow.

## Example workflows

### Discover and evaluate

1. Call `list_materials` or read the materials resource.
2. Use `list_records` to locate candidate records, then call `get_record` for
   the complete payload or revision details.
3. Call `evaluate_record` with a stable UUID/revision when reproducibility
   matters, or with a material/name/model selector for convenient lookup.
4. Use `resample_record` to produce a tabulated representation for downstream
   consumers without changing the catalog.

### Submit an authorized record for review

Create a local token with `records:write`, set its secret in
`XMDM_MCP_TOKEN`, and restart the stdio process. Confirm that `submit_record`
is listed, then send `material_id` and a complete XMDM payload. The service
validates it and returns a pending `submission_id`; it becomes catalog data
only after an administrator approves it through the HTTP review API or web UI.
For HTTP MCP, send the bearer token in the request's `Authorization` header.
Do not pass the token as a tool argument or include it in prompts.

MCP write authorization is enforced independently from tool registration.
Token administration and submission review are performed through the local
CLI or separately authorized HTTP admin endpoints; there are no MCP
token-admin or review tools.