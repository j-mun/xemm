import asyncio
import json
import os
from pathlib import Path
import sys

import pytest


CUSTOM_DB = Path(__file__).resolve().parents[2] / 'xmdm' / 'tests' / 'custom-db'


def test_mcp_stdio_tools():
  pytest.importorskip('mcp')
  from mcp import ClientSession, StdioServerParameters
  from mcp.client.stdio import stdio_client

  async def check_tools():
    server_src = Path(__file__).resolve().parents[1] / 'src'
    xmdm_src = Path(__file__).resolve().parents[2] / 'xmdm' / 'src'
    pythonpath = os.pathsep.join((str(server_src), str(xmdm_src)))
    parameters = StdioServerParameters(
      command=sys.executable,
      args=['-m', 'xmdm_server', 'mcp', '--db', str(CUSTOM_DB)],
      env={
        **os.environ,
        'PYTHONPATH': pythonpath,
        'XMDM_MCP_TOKEN': '',
      },
    )
    async with stdio_client(parameters) as (read, write):
      async with ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        assert {
          'list_materials', 'list_records', 'get_record', 'evaluate_record',
          'get_material', 'resample_record', 'validate_record',
        } <= {tool.name for tool in tools.tools}
        templates = await session.list_resource_templates()
        template_uris = {
          template.uriTemplate for template in templates.resourceTemplates
        }
        assert 'xmdm://records/{record_id}' in template_uris
        assert 'xmdm://materials/{material_id}' in template_uris
        response = await session.call_tool('get_record', {
          'material_id': 'Example',
          'record_name': 'linear',
          'model': 'tabulated',
        })
        assert not response.isError
        assert json.loads(response.content[0].text)['name'] == 'linear'
        failure = await session.call_tool('get_record', {
          'material_id': 'Example',
          'record_name': 'missing',
          'model': 'tabulated',
        })
        assert failure.isError

  asyncio.run(asyncio.wait_for(check_tools(), timeout=20))


def test_mcp_submit_tool_requires_a_scoped_environment_token(tmp_path):
  pytest.importorskip('mcp')
  from mcp import ClientSession, StdioServerParameters
  from mcp.client.stdio import stdio_client
  from xmdm_server.db import SQLiteCatalog, initialize_database

  database_path = tmp_path / 'database.sqlite'
  catalog = SQLiteCatalog(initialize_database(database_path))
  catalog.import_json(CUSTOM_DB)
  writer = catalog.create_token('mcp-writer', ['records:write'])
  payload = catalog.get_record('Example', 'linear', 'tabulated')
  payload['name'] = 'mcp-submitted'
  payload.pop('id')

  async def check_write_tool():
    server_src = Path(__file__).resolve().parents[1] / 'src'
    xmdm_src = Path(__file__).resolve().parents[2] / 'xmdm' / 'src'
    parameters = StdioServerParameters(
      command=sys.executable,
      args=['-m', 'xmdm_server', 'mcp', '--db', str(database_path)],
      env={
        **os.environ,
        'PYTHONPATH': os.pathsep.join((str(server_src), str(xmdm_src))),
        'XMDM_MCP_TOKEN': writer['token'],
      },
    )
    async with stdio_client(parameters) as (read, write):
      async with ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        assert 'submit_record' in {tool.name for tool in tools.tools}
        result = await session.call_tool('submit_record', {
          'material_id': 'Example',
          'payload': payload,
        })
        assert not result.isError
        submission = json.loads(result.content[0].text)
        assert submission['status'] == 'pending'
        assert len(catalog.list_submissions()) == 1
        accepted = catalog.review_submission(
          submission['submission_id'], 'approve',
          actor_token_id=catalog.create_token(
            'reviewer', ['tokens:admin'],
          )['token_id'],
        )
        assert accepted['revision'] == 1

  asyncio.run(asyncio.wait_for(check_write_tool(), timeout=20))


def test_mcp_nlo_catalog_evaluation_and_resampling():
  pytest.importorskip('mcp')
  from mcp import ClientSession, StdioServerParameters
  from mcp.client.stdio import stdio_client
  import numpy as np

  async def check_nlo_tools():
    server_src = Path(__file__).resolve().parents[1] / 'src'
    xmdm_src = Path(__file__).resolve().parents[2] / 'xmdm' / 'src'
    parameters = StdioServerParameters(
      command=sys.executable,
      args=['-m', 'xmdm_server', 'mcp', '--db', str(xmdm_src / 'xmdm-db')],
      env={
        **os.environ,
        'PYTHONPATH': os.pathsep.join((str(server_src), str(xmdm_src))),
        'XMDM_MCP_TOKEN': '',
      },
    )
    async with stdio_client(parameters) as (read, write):
      async with ClientSession(read, write) as session:
        await session.initialize()
        catalog = await session.call_tool('list_records', {'physics': 'nlo'})
        assert not catalog.isError
        assert json.loads(catalog.content[0].text)['total'] == 207
        selected = await session.call_tool('get_record', {
          'material_id': 'ZnSe',
          'record_name': 'Matteo-200ps',
          'model': 'tabulated',
        })
        assert not selected.isError
        record = json.loads(selected.content[0].text)
        assert record['physics'] == 'nlo'
        request = {
          'record_id': record['id'],
          'coordinates': [10.6],
          'unit': 'um',
          'parameter': 'n2',
        }
        evaluated = await session.call_tool('evaluate_record', request)
        assert not evaluated.isError
        np.testing.assert_allclose(
          json.loads(evaluated.content[0].text)['values'][0]['real'],
          1.2e-18,
          rtol=1e-6,
        )
        resampled = await session.call_tool('resample_record', request)
        assert not resampled.isError
        assert json.loads(resampled.content[0].text)['record']['physics'] == 'nlo'

  asyncio.run(asyncio.wait_for(check_nlo_tools(), timeout=20))
