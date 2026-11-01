"""Versioned HTTP API with bearer-authorized staged submissions."""

from __future__ import annotations

import logging
from pathlib import Path
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, ConfigDict, StrictFloat, StrictInt

from ...errors import (
  AmbiguousRecord,
  DatabaseUnavailable,
  InvalidQuery,
  RecordNotFound,
  RevisionConflict,
)
from ...services import DatabaseService

logger = logging.getLogger(__name__)
_STATIC = Path(__file__).resolve().parents[2] / 'web' / 'static'


class EvaluationRequest(BaseModel):
  model_config = ConfigDict(extra='forbid')
  material_id: str | None = None
  record_name: str | None = None
  model: str | None = None
  record_id: str | None = None
  revision: int | None = None
  coordinates: list[StrictInt | StrictFloat]
  unit: str
  parameter: str
  interpolation: str = 'linear'


class ResampleRequest(BaseModel):
  model_config = ConfigDict(extra='forbid')
  coordinates: list[StrictInt | StrictFloat]
  unit: str
  parameter: str
  interpolation: str = 'linear'
  range_policy: str = 'clip'
  revision: int | None = None


class RecordWriteRequest(BaseModel):
  model_config = ConfigDict(extra='forbid')
  material_id: str
  material_name: str | None = None
  payload: dict
  derivation: dict | None = None


class RecordRevisionRequest(BaseModel):
  model_config = ConfigDict(extra='forbid')
  payload: dict
  derivation: dict | None = None


class TokenRequest(BaseModel):
  model_config = ConfigDict(extra='forbid')
  name: str
  scopes: list[str]
  expires_at: str | None = None


class ReviewRequest(BaseModel):
  model_config = ConfigDict(extra='forbid')
  note: str | None = None


def _token_for_scope(
    request: Request,
    database: DatabaseService,
    required_scope: str,
) -> dict:
  authorization = request.headers.get('authorization', '')
  scheme, separator, secret = authorization.partition(' ')
  if not separator or scheme.casefold() != 'bearer' or not secret.strip():
    raise HTTPException(
      status_code=401,
      detail='Bearer token required',
      headers={'WWW-Authenticate': 'Bearer'},
    )
  token = database.authenticate_token(secret.strip())
  if token is None:
    raise HTTPException(
      status_code=401,
      detail='Invalid or expired bearer token',
      headers={'WWW-Authenticate': 'Bearer'},
    )
  if required_scope not in token['scopes']:
    raise HTTPException(status_code=403, detail='Insufficient token scope')
  return token


def _revision_from_etag(value: str | None) -> int:
  if value is None:
    raise HTTPException(status_code=428, detail='If-Match header is required')
  match = re.fullmatch(r'"([1-9][0-9]*)"', value.strip())
  if match is None:
    raise InvalidQuery('If-Match must contain a quoted revision number')
  return int(match.group(1))


def create_app(
    service: DatabaseService | None = None,
    *,
    web: bool = True,
    mcp_http: bool = False,
    mcp_host: str = '127.0.0.1',
) -> FastAPI:
  database = service if service is not None else DatabaseService()
  mcp_server = None
  if mcp_http:
    from ...mcp.server import (
      AuthorizationContextMiddleware,
      create_server as create_mcp_server,
    )

    mcp_server = create_mcp_server(
      database, http_transport=True, host=mcp_host,
    )
    mcp_http_app = AuthorizationContextMiddleware(
      mcp_server.streamable_http_app(),
    )
  else:
    mcp_http_app = None

  @asynccontextmanager
  async def lifespan(_app):
    if mcp_server is None:
      yield
    else:
      async with mcp_server.session_manager.run():
        yield

  app = FastAPI(title='XMDM Server', version='1', lifespan=lifespan)

  @app.exception_handler(ValueError)
  async def handle_value_error(_request: Request, error: ValueError):
    if isinstance(error, RecordNotFound):
      status_code = 404
    elif isinstance(error, AmbiguousRecord):
      status_code = 409
    elif isinstance(error, InvalidQuery):
      status_code = 400
    else:
      logger.error(
        'Database operation failed handling HTTP %s request',
        _request.method,
        exc_info=(type(error), error, error.__traceback__),
      )
      return JSONResponse(
        status_code=500,
        content={'detail': 'Database operation failed; consult server logs'},
      )
    return JSONResponse(status_code=status_code, content={'detail': str(error)})

  @app.exception_handler(RevisionConflict)
  async def handle_revision_conflict(request: Request, error: RevisionConflict):
    logger.info('Rejected stale revision update for %s', request.url.path)
    return JSONResponse(
      status_code=412,
      content={'detail': str(error)},
    )

  @app.exception_handler(DatabaseUnavailable)
  async def handle_database_unavailable(
      request: Request, error: DatabaseUnavailable,
  ):
    logger.error(
      'Configured material database is unavailable while handling HTTP %s',
      request.method,
      exc_info=(type(error.__cause__), error.__cause__,
                error.__cause__.__traceback__ if error.__cause__ else None),
    )
    return JSONResponse(
      status_code=503,
      content={'detail': 'Configured material database is unavailable'},
    )

  if web:
    @app.get('/', include_in_schema=False)
    def web_index():
      return RedirectResponse('/data', status_code=307)

    @app.get('/data', include_in_schema=False)
    def web_data():
      return FileResponse(_STATIC / 'data.html')

    @app.get('/upload', include_in_schema=False)
    def web_upload():
      return FileResponse(_STATIC / 'upload.html')

    @app.get('/admin', include_in_schema=False)
    def web_admin():
      return FileResponse(_STATIC / 'admin.html')

    @app.get('/status', include_in_schema=False)
    def web_status():
      return FileResponse(_STATIC / 'status.html')

    @app.get('/static/{asset}', include_in_schema=False)
    def web_asset(asset: str):
      if asset not in ('app.js', 'style.css'):
        raise HTTPException(status_code=404, detail='Asset not found')
      return FileResponse(_STATIC / asset)

  if mcp_http_app is not None:
    app.mount('/mcp', mcp_http_app)

  @app.get('/api/v1/health')
  def health() -> dict[str, str | bool]:
    database.check_database()
    return {
      'service': 'xmdm-server',
      'status': 'ok',
      'read_only': database.catalog is None,
      'web_ui': web,
      'mcp_http': mcp_http,
    }

  @app.get('/api/v1/materials')
  def list_materials(
      query: str = '',
      physics: str | None = None,
      model: str | None = None,
      limit: int = Query(100, ge=1, le=1000),
      offset: int = Query(0, ge=0),
  ):
    return database.list_materials(query, limit, offset, physics, model)

  @app.get('/api/v1/materials/{material_id}')
  def get_material(material_id: str):
    return database.get_material(material_id)

  @app.get('/api/v1/records')
  def list_records(
      query: str = '',
      model: str | None = None,
      material_id: str | None = None,
      physics: str | None = None,
      limit: int = Query(100, ge=1, le=1000),
      offset: int = Query(0, ge=0),
  ):
    return database.list_records(
      query, model, material_id, limit, offset, physics,
    )

  @app.get('/api/v1/records/{record_id}/revisions')
  def list_record_revisions(record_id: str):
    return {'items': database.get_revisions(record_id)}

  @app.get('/api/v1/records/{record_id}/data')
  def get_record_data(record_id: str, revision: int | None = None):
    return database.get_record_by_id(record_id, revision)['data']

  @app.get('/api/v1/records/{record_id}/metadata')
  def get_record_metadata(record_id: str, revision: int | None = None):
    return database.get_record_by_id(record_id, revision)['metadata']

  @app.get('/api/v1/records/{record_id}/provenance')
  def get_record_provenance(record_id: str, revision: int | None = None):
    return database.get_provenance(record_id, revision)

  @app.get('/api/v1/records/{record_id}/export')
  def export_record(
      record_id: str,
      format: str = Query('json', pattern='^(json|yaml|csv|lumerical)$'),
      revision: int | None = None,
  ):
    content, media_type = database.export_record(record_id, revision, format)
    suffix = 'yaml' if format == 'yaml' else format
    return Response(
      content=content,
      media_type=media_type,
      headers={
        'Content-Disposition':
          f'attachment; filename="{record_id}-r{revision or 1}.{suffix}"',
      },
    )

  @app.get('/api/v1/records/{record_id}')
  def get_record_by_id(record_id: str, revision: int | None = None):
    return database.get_record_envelope(record_id, revision)

  @app.post('/api/v1/records/{record_id}/validate')
  def validate_record(record_id: str, revision: int | None = None):
    return database.validate_record(record_id, revision)

  @app.post('/api/v1/records/{record_id}/resample')
  def resample_record(record_id: str, request: ResampleRequest):
    return database.resample_record(
      record_id, request.coordinates, request.unit, request.parameter,
      request.interpolation, request.range_policy, request.revision,
    )

  @app.get('/api/v1/records/{material_id}/{record_name}')
  def get_record(
      material_id: str,
      record_name: str,
      model: str | None = None,
      physics: str | None = None,
  ):
    return database.get_record(material_id, record_name, model, physics)

  @app.post('/api/v1/evaluate')
  def evaluate(request: EvaluationRequest):
    if request.record_id is not None:
      if request.material_id is not None or request.record_name is not None:
        raise InvalidQuery('use either record_id or a material/name selector')
      return database.evaluate_record_by_id(
        request.record_id, request.coordinates, request.unit,
        request.parameter, request.interpolation, request.revision,
      )
    if (
      request.material_id is None
      or request.record_name is None
      or request.model is None
    ):
      raise InvalidQuery(
        'material_id, record_name, and model are required without record_id',
      )
    return database.evaluate_record(
      request.material_id, request.record_name, request.model,
      request.coordinates, request.unit, request.parameter,
      request.interpolation,
    )

  @app.post('/api/v1/submissions', status_code=202)
  @app.post('/api/v1/records', status_code=202, include_in_schema=False)
  def create_record_submission(
      request: RecordWriteRequest, http_request: Request,
  ):
    token = _token_for_scope(http_request, database, 'records:write')
    result = database.stage_submission(
      request.material_id,
      request.payload,
      material_name=request.material_name,
      derivation=request.derivation,
      actor_token_id=token['token_id'],
    )
    return JSONResponse(
      status_code=202,
      content=result,
      headers={'Cache-Control': 'no-store'},
    )

  @app.put('/api/v1/records/{record_id}', status_code=202)
  def stage_record_revision(
      record_id: str,
      request: RecordRevisionRequest,
      http_request: Request,
      if_match: str | None = Header(default=None, alias='If-Match'),
  ):
    token = _token_for_scope(http_request, database, 'records:write')
    expected_revision = _revision_from_etag(if_match)
    result = database.stage_submission(
      None,
      request.payload,
      target_record_id=record_id,
      expected_revision=expected_revision,
      derivation=request.derivation,
      actor_token_id=token['token_id'],
    )
    return JSONResponse(
      status_code=202,
      content=result,
      headers={'Cache-Control': 'no-store'},
    )

  @app.get('/api/v1/admin/tokens')
  def list_tokens(request: Request):
    _token_for_scope(request, database, 'tokens:admin')
    return {'items': database.list_tokens()}

  @app.get('/api/v1/admin/audit')
  def list_audit_events(
      request: Request,
      limit: int = Query(100, ge=1, le=1000),
  ):
    _token_for_scope(request, database, 'tokens:admin')
    return {'items': database.list_audit_events(limit)}

  @app.get('/api/v1/admin/submissions')
  def list_submissions(
      request: Request,
      status: str = 'pending',
      limit: int = Query(100, ge=1, le=1000),
  ):
    _token_for_scope(request, database, 'tokens:admin')
    return {'items': database.list_submissions(status, limit)}

  @app.get('/api/v1/admin/records')
  def list_admin_records(
      request: Request,
      query: str = '',
      limit: int = Query(100, ge=1, le=1000),
  ):
    _token_for_scope(request, database, 'tokens:admin')
    return {'items': database.list_admin_records(query, limit)}

  @app.delete('/api/v1/admin/records/{record_id}')
  def archive_record(record_id: str, request: Request):
    token = _token_for_scope(request, database, 'tokens:admin')
    return database.soft_delete_record(
      record_id, actor_token_id=token['token_id'],
    )

  @app.post('/api/v1/admin/records/{record_id}/restore')
  def restore_record(record_id: str, request: Request):
    token = _token_for_scope(request, database, 'tokens:admin')
    return database.restore_record(
      record_id, actor_token_id=token['token_id'],
    )

  @app.post('/api/v1/admin/submissions/{submission_id}/approve')
  def approve_submission(
      submission_id: str,
      request: Request,
      review: ReviewRequest | None = None,
  ):
    token = _token_for_scope(request, database, 'tokens:admin')
    return database.review_submission(
      submission_id, 'approve', actor_token_id=token['token_id'],
      note=None if review is None else review.note,
    )

  @app.post('/api/v1/admin/submissions/{submission_id}/reject')
  def reject_submission(
      submission_id: str,
      request: Request,
      review: ReviewRequest | None = None,
  ):
    token = _token_for_scope(request, database, 'tokens:admin')
    return database.review_submission(
      submission_id, 'reject', actor_token_id=token['token_id'],
      note=None if review is None else review.note,
    )

  @app.post('/api/v1/admin/tokens', status_code=201)
  def create_token(request: TokenRequest, http_request: Request):
    token = _token_for_scope(http_request, database, 'tokens:admin')
    return JSONResponse(
      status_code=201,
      content=database.create_token(
        request.name, request.scopes, request.expires_at,
        actor_token_id=token['token_id'],
      ),
      headers={'Cache-Control': 'no-store'},
    )

  @app.delete('/api/v1/admin/tokens/{token_id}', status_code=204)
  def revoke_token(token_id: str, request: Request):
    token = _token_for_scope(request, database, 'tokens:admin')
    database.revoke_token(token_id, actor_token_id=token['token_id'])
    return Response(status_code=204)

  return app
