import json
from pathlib import Path
import uuid

import numpy as np
import pytest

from xmdm_server.services import (
  AmbiguousRecord,
  DatabaseService,
  InvalidQuery,
  RecordNotFound,
)


CUSTOM_DB = Path(__file__).resolve().parents[2] / 'xmdm' / 'tests' / 'custom-db'


@pytest.fixture
def database():
  return DatabaseService(CUSTOM_DB)


def test_catalog_search_and_record_access(database):
  assert database.list_materials()['items'][0]['id'] == 'Example'
  assert database.list_materials(query='DEMO')['total'] == 1
  assert database.list_records(query='synthetic')['total'] == 2
  assert database.list_records(model='cauchy')['items'][0]['name'] == 'cauchy'
  assert database.get_material('demo')['id'] == 'Example'
  assert database.get_record('demo', 'LINEAR')['model'] == 'tabulated'
  assert database.get_record('Example', 'cauchy')['data']['A'] == 1.5


def test_tabulated_and_model_evaluation(database):
  tabulated = database.evaluate_record(
    'Example', 'linear', 'tabulated', [450, 550], 'nm', 'n', 'linear',
  )
  np.testing.assert_allclose(
    [item['real'] for item in tabulated['values']], [2.5, 3.5],
  )
  np.testing.assert_allclose(
    [item['imag'] for item in tabulated['values']], [0.15, 0.25],
  )

  cauchy = database.evaluate_record(
    'Example', 'cauchy', 'cauchy', [500, 1000], 'nm', 'n',
  )
  np.testing.assert_allclose(
    [item['real'] for item in cauchy['values']], [1.556, 1.511],
  )
  assert [item['imag'] for item in cauchy['values']] == [0, 0]


def test_invalid_and_ambiguous_queries(database):
  with pytest.raises(RecordNotFound):
    database.get_record('missing', 'linear')
  with pytest.raises(InvalidQuery, match='unsupported model'):
    database.list_records(model='unknown')
  with pytest.raises(InvalidQuery, match='non-empty'):
    database.evaluate_record('Example', 'linear', 'tabulated', [], 'nm', 'n')
  with pytest.raises(InvalidQuery, match='finite numeric'):
    database.evaluate_record(
      'Example', 'linear', 'tabulated', [True], 'nm', 'n',
    )
  with pytest.raises(InvalidQuery, match='finite numeric'):
    database.evaluate_record(
      'Example', 'linear', 'tabulated', [10 ** 10000], 'nm', 'n',
    )
  with pytest.raises(InvalidQuery, match='unsupported spectral unit'):
    database.evaluate_record(
      'Example', 'linear', 'tabulated', [500], 'yards', 'n',
    )


def test_verify_validates_every_custom_database_record(database):
  assert database.verify() == {'valid': True, 'checked': 2, 'errors': []}


def test_verify_reports_missing_record_without_leaking_database_path(tmp_path):
  import shutil

  shutil.copytree(CUSTOM_DB, tmp_path, dirs_exist_ok=True)
  database = DatabaseService(tmp_path)
  record_file = next((tmp_path / 'Example').glob('*.json'))
  record_file.unlink()

  report = database.verify()

  assert not report['valid']
  assert report['checked'] == 2
  assert len(report['errors']) == 1
  assert str(tmp_path) not in json.dumps(report)


def test_bundled_database_is_available_and_valid():
  database = DatabaseService()
  assert database.list_materials()['total'] > 0
  assert database.verify()['valid']


def test_evaluate_all_analytic_models(tmp_path):
  model_data = {
    'drude': {
      'eps_inf': 1.0, 'omega_p': 2.0, 'gamma': 0.1, 'unit': 'eV',
    },
    'lorentz': {
      'eps_inf': 1.0, 'omega_p': 2.0, 'f': [1.0],
      'gamma': [0.1], 'omega_0': [2.0],
    },
    'sellmeier': {'B': [0.7], 'C': [0.04], 'unit': 'um'},
    'cauchy': {'A': 1.5, 'B': 0.01, 'C': 0.001, 'unit': 'um'},
  }
  material_dir = tmp_path / 'Example'
  material_dir.mkdir()
  references = []
  for model, data in model_data.items():
    record_id = str(uuid.uuid4())
    relative_path = f'Example/{record_id}.json'
    record = {
      'schema_version': '1',
      'physics': 'optics',
      'model': model,
      'name': model,
      'id': record_id,
      'data': data,
      'metadata': {'source': 'Synthetic test'},
    }
    (tmp_path / relative_path).write_text(json.dumps(record), encoding='utf-8')
    references.append({
      'id': record_id,
      'physics': 'optics',
      'model': model,
      'name': model,
      'path': relative_path,
    })
  (tmp_path / 'index.json').write_text(json.dumps({
    'schema_version': '1',
    'materials': {
      'Example': {
        'name': 'Synthetic example',
        'aliases': [],
        'records': references,
      },
    },
  }), encoding='utf-8')

  database = DatabaseService(tmp_path)
  references[1]['name'] = references[0]['name']
  index_path = tmp_path / 'index.json'
  index_path.write_text(json.dumps({
    'schema_version': '1',
    'materials': {
      'Example': {
        'name': 'Synthetic example',
        'aliases': [],
        'records': references,
      },
    },
  }), encoding='utf-8')
  with pytest.raises(AmbiguousRecord):
    database.get_record('Example', 'drude')

  references[1]['name'] = 'lorentz'
  index_path.write_text(json.dumps({
    'schema_version': '1',
    'materials': {
      'Example': {
        'name': 'Synthetic example',
        'aliases': [],
        'records': references,
      },
    },
  }), encoding='utf-8')
  for model in model_data:
    unit = 'eV' if model in ('drude', 'lorentz') else 'um'
    result = database.evaluate_record(
      'Example', model, model, [1.0], unit, 'e',
    )
    assert len(result['values']) == 1
    assert np.isfinite(result['values'][0]['real'])
    assert np.isfinite(result['values'][0]['imag'])
  with pytest.raises(InvalidQuery, match='only configurable'):
    database.evaluate_record(
      'Example', 'drude', 'drude', [1.0], 'eV', 'e', 'cubic',
    )
  assert database.verify()['valid']


def test_rii_formula_and_tabulated_k_n2_evaluation_on_both_backends(tmp_path):
  from xmdm_server.db.catalog import SQLiteCatalog
  from xmdm_server.db.repository import initialize_database

  material_dir = tmp_path / 'Example'
  material_dir.mkdir()
  records = [
    ('tabulated', 'k-only', {
      'unit': 'nm', 'type': 'k', 'f': [400, 600], 're': [0.1, 0.3],
      'im': [0, 0],
    }),
    ('tabulated', 'nonlinear', {
      'unit': 'nm', 'type': 'n2', 'f': [400, 600],
      're': [1e-19, 3e-19], 'im': [0, 0],
    }),
    ('rii_formula', 'formula', {
      'formula': 5, 'coefficients': [1.5, 0.2, -2, 0.1, 2],
      'unit': 'um', 'wavelength_range': [0.4, 2],
    }),
  ]
  references = []
  for model, name, data in records:
    record_id = str(uuid.uuid4())
    relative_path = f'Example/{record_id}.json'
    physics = 'nlo' if data.get('type') == 'n2' else 'optics'
    payload = {
      'schema_version': '1',
      'physics': physics,
      'model': model,
      'name': name,
      'id': record_id,
      'data': data,
      'metadata': {'source': 'Synthetic test'},
    }
    (tmp_path / relative_path).write_text(
      json.dumps(payload), encoding='utf-8',
    )
    references.append({
      'id': record_id,
      'physics': physics,
      'model': model,
      'name': name,
      'path': relative_path,
    })
  (tmp_path / 'index.json').write_text(json.dumps({
    'schema_version': '1',
    'materials': {
      'Example': {
        'name': 'Synthetic example',
        'aliases': [],
        'records': references,
      },
    },
  }), encoding='utf-8')

  json_database = DatabaseService(tmp_path)
  sqlite_database = SQLiteCatalog(
    initialize_database(tmp_path / 'database.sqlite'),
  )
  sqlite_database.import_json(tmp_path)
  for database in (json_database, sqlite_database):
    assert database.list_records(physics='nlo')['total'] == 1
    assert database.list_records(physics='optics')['total'] == 2
    assert database.list_materials(physics='nlo')['total'] == 1
    k = database.evaluate_record(
      'Example', 'k-only', 'tabulated', [500], 'nm', 'k',
    )
    n2 = database.evaluate_record(
      'Example', 'nonlinear', 'tabulated', [500], 'nm', 'n2',
    )
    formula = database.evaluate_record(
      'Example', 'formula', 'rii_formula', [1], 'um', 'n',
    )

    np.testing.assert_allclose(k['values'][0]['real'], 0.2, rtol=1e-6)
    np.testing.assert_allclose(n2['values'][0]['real'], 2e-19, rtol=1e-6)
    np.testing.assert_allclose(formula['values'][0]['real'], 1.8, rtol=1e-6)
    nonlinear_id = references[1]['id']
    by_id = database.evaluate_record_by_id(
      nonlinear_id, [500], 'nm', 'n2',
    )
    np.testing.assert_allclose(by_id['values'][0]['real'], 2e-19, rtol=1e-6)
    resampled = database.resample_record(
      nonlinear_id, [400, 500, 600], 'nm', 'n2',
    )
    assert resampled['record']['physics'] == 'nlo'
    assert resampled['record']['data']['type'] == 'n2'
    np.testing.assert_allclose(
      resampled['record']['data']['re'], [1e-19, 2e-19, 3e-19], rtol=1e-6,
    )
    with pytest.raises(InvalidQuery, match='nonlinear'):
      database.evaluate_record(
        'Example', 'nonlinear', 'tabulated', [500], 'nm', 'n',
      )
