"""MCP tool adapter over the shared XMDM database service."""

from __future__ import annotations

import json
import os
from contextvars import ContextVar
from typing import Any

from ..errors import AuthenticationRequired
from ..services import DatabaseService

HTTP_MCP_AUTHORIZATION: ContextVar[str | None] = ContextVar(
  'xmdm_http_mcp_authorization', default=None,
)


def create_server(
    service: DatabaseService | None = None,
    *,
    http_transport: bool = False,
    host: str = '127.0.0.1',
):
  from mcp.server.fastmcp import FastMCP

  database = service if service is not None else DatabaseService()
  server_options: dict[str, Any] = {
    'streamable_http_path': '/',
    'stateless_http': True,
  }
  if http_transport:
    from mcp.server.transport_security import TransportSecuritySettings

    configured_hosts = [
      value.strip()
      for value in os.environ.get('XMDM_MCP_ALLOWED_HOSTS', '').split(',')
      if value.strip()
    ]
    configured_origins = [
      value.strip()
      for value in os.environ.get('XMDM_MCP_ALLOWED_ORIGINS', '').split(',')
      if value.strip()
    ]
    server_options.update({
      'host': host,
      'transport_security': TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[
          '127.0.0.1:*', 'localhost:*', '[::1]:*', *configured_hosts,
        ],
        allowed_origins=[
          'http://127.0.0.1:*', 'http://localhost:*', 'http://[::1]:*',
          *configured_origins,
        ],
      ),
    })
  server = FastMCP('xmdm-server', **server_options)
  server.tool(name='list_materials')(database.list_materials)
  server.tool(name='list_records')(database.list_records)

  @server.tool(name='get_material')
  def get_material(material_id: str) -> dict:
    return database.get_material(material_id)

  @server.tool(name='get_record')
  def get_record(
      record_id: str | None = None,
      revision: int | None = None,
      material_id: str | None = None,
      record_name: str | None = None,
      model: str | None = None,
  ) -> dict:
    if record_id is not None:
      if material_id is not None or record_name is not None:
        raise ValueError('use a record ID or a material/name selector')
      return database.get_record_envelope(record_id, revision)
    if material_id is None or record_name is None:
      raise ValueError('record_id or material_id and record_name are required')
    return database.get_record(material_id, record_name, model)

  @server.tool(name='evaluate_record')
  def evaluate_record(
      material_id: str | None = None,
      record_name: str | None = None,
      model: str | None = None,
      coordinates: list[float] | None = None,
      unit: str = 'nm',
      parameter: str = 'n',
      interpolation: str = 'linear',
      record_id: str | None = None,
      revision: int | None = None,
  ) -> dict:
    if coordinates is None:
      raise ValueError('coordinates are required')
    if record_id is not None:
      if material_id is not None or record_name is not None:
        raise ValueError('use a record ID or a material/name selector')
      return database.evaluate_record_by_id(
        record_id, coordinates, unit, parameter, interpolation, revision,
      )
    if material_id is None or record_name is None or model is None:
      raise ValueError('material_id, record_name, and model are required')
    return database.evaluate_record(
      material_id, record_name, model, coordinates, unit, parameter,
      interpolation,
    )

  @server.tool(name='resample_record')
  def resample_record(
      record_id: str,
      coordinates: list[float],
      unit: str,
      parameter: str,
      interpolation: str = 'linear',
      range_policy: str = 'clip',
      revision: int | None = None,
  ) -> dict:
    return database.resample_record(
      record_id, coordinates, unit, parameter, interpolation,
      range_policy, revision,
    )

  @server.tool(name='validate_record')
  def validate_record(record_id: str, revision: int | None = None) -> dict:
    return database.validate_record(record_id, revision)

  @server.resource('xmdm://materials?limit={limit}&offset={offset}')
  def materials_resource(limit: int = 100, offset: int = 0) -> str:
    return json.dumps(database.list_materials(limit=limit, offset=offset))

  @server.resource('xmdm://materials/{material_id}')
  def material_resource(material_id: str) -> str:
    return json.dumps(database.get_material(material_id))

  @server.resource('xmdm://records?limit={limit}&offset={offset}')
  def records_resource(limit: int = 100, offset: int = 0) -> str:
    return json.dumps(database.list_records(limit=limit, offset=offset))

  @server.resource('xmdm://records/{record_id}')
  def record_resource(record_id: str) -> str:
    return json.dumps(database.get_record_envelope(record_id))

  @server.resource('xmdm://records/{record_id}/revisions/{revision}')
  def revision_resource(record_id: str, revision: int) -> str:
    return json.dumps(database.get_record_envelope(record_id, revision))

  @server.resource('xmdm://records/{record_id}/data?revision={revision}')
  def record_data_resource(record_id: str, revision: int | None = None) -> str:
    return json.dumps(database.get_record_by_id(record_id, revision)['data'])

  @server.resource('xmdm://records/{record_id}/metadata?revision={revision}')
  def record_metadata_resource(
      record_id: str, revision: int | None = None,
  ) -> str:
    return json.dumps(
      database.get_record_by_id(record_id, revision)['metadata'],
    )

  @server.resource('xmdm://records/{record_id}/provenance?revision={revision}')
  def record_provenance_resource(
      record_id: str, revision: int | None = None,
  ) -> str:
    return json.dumps(database.get_provenance(record_id, revision))

  mcp_token = os.environ.get('XMDM_MCP_TOKEN') if not http_transport else None
  principal: dict[str, Any] | None = None
  if mcp_token:
    principal = database.authenticate_token(mcp_token)
    if principal is None:
      raise AuthenticationRequired(
        'XMDM_MCP_TOKEN is invalid, revoked, or expired',
      )
    if 'records:write' not in principal['scopes']:
      raise AuthenticationRequired(
        'XMDM_MCP_TOKEN requires the records:write scope',
      )

  if http_transport or principal is not None:
    @server.tool(name='submit_record')
    def submit_record(
        material_id: str,
        payload: dict,
        derivation: dict | None = None,
        material_name: str | None = None,
    ) -> dict:
      upload_principal = principal
      if http_transport:
        authorization = HTTP_MCP_AUTHORIZATION.get() or ''
        scheme, separator, secret = authorization.partition(' ')
        if (
          not separator or scheme.casefold() != 'bearer' or not secret.strip()
        ):
          raise AuthenticationRequired(
            'a bearer token with the records:write scope is required',
          )
        upload_principal = database.authenticate_token(secret.strip())
        if upload_principal is None:
          raise AuthenticationRequired('invalid or expired bearer token')
        if 'records:write' not in upload_principal['scopes']:
          raise AuthenticationRequired('token requires the records:write scope')
      if upload_principal is None:
        raise AuthenticationRequired('a records:write token is required')
      return database.stage_submission(
        material_id,
        payload,
        material_name=material_name,
        derivation=derivation,
        actor_token_id=upload_principal['token_id'],
      )

  return server


def run(db: str | None = None, backend: str | None = None) -> None:
  create_server(DatabaseService(db, backend=backend)).run(transport='stdio')


class AuthorizationContextMiddleware:
  """Make each Streamable HTTP request's bearer header available to tools."""

  def __init__(self, app):
    self.app = app

  async def __call__(self, scope, receive, send):
    if scope['type'] != 'http':
      await self.app(scope, receive, send)
      return
    authorization = next(
      (
        value.decode('latin-1')
        for key, value in scope.get('headers', [])
        if key.lower() == b'authorization'
      ),
      None,
    )
    token = HTTP_MCP_AUTHORIZATION.set(authorization)
    try:
      await self.app(scope, receive, send)
    finally:
      HTTP_MCP_AUTHORIZATION.reset(token)
