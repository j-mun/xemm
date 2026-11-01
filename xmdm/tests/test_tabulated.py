import json
from pathlib import Path

import jax
import jax.numpy as jp
import numpy as np
import pytest

from xmdm import Material, Material


def _write_material(db: Path) -> None:
  material_dir = db / 'Test'
  material_dir.mkdir(parents=True)
  record = {
    'schema_version': '1',
    'model': 'tabulated',
    'name': 'linear',
    'id': '0a8c1393-f8da-4a29-a4bf-100aeb510f3e',
    'data': {
      'unit': 'nm',
      'type': 'n',
      'f': [400, 500, 600, 700],
      're': [2, 3, 4, 5],
      'im': [0.1, 0.2, 0.3, 0.4],
    },
    'metadata': {},
  }
  (material_dir / f'{record["id"]}.json').write_text(
    json.dumps(record), encoding='utf-8'
  )
  (db / 'index.json').write_text(
    json.dumps({
      'schema_version': '1',
      'materials': {
        'Test': {
          'name': 'Linear test material',
          'aliases': [],
          'records': [{
            'id': record['id'],
            'model': 'tabulated',
            'name': 'linear',
            'path': f'Test/{record["id"]}.json',
          }],
        },
      },
    }),
    encoding='utf-8',
  )


@pytest.fixture
def material_db(tmp_path: Path) -> Path:
  _write_material(tmp_path)
  return tmp_path


def test_from_db_loads_custom_data_without_extension(material_db: Path):
  material = Material.from_db(
    'Test/linear', db=str(material_db), verbose=False
  )

  assert material.name == 'Linear test material'
  assert material.unit == 'nm'
  assert material.kind == 'n'
  np.testing.assert_allclose(material.f, [400, 500, 600, 700])
  np.testing.assert_allclose(
    material.complex,
    [2 + 0.1j, 3 + 0.2j, 4 + 0.3j, 5 + 0.4j],
  )


def test_from_db_converts_coordinates_and_parameters(material_db: Path):
  material = Material.from_db(
    'Test/linear',
    db=str(material_db),
    unit='THz',
    kind='e',
    verbose=False,
  )

  source_wavelengths = np.array([700, 600, 500, 400])
  source_indices = np.array([5 + 0.4j, 4 + 0.3j, 3 + 0.2j, 2 + 0.1j])
  expected_frequency = 1e-3 * 299_792_458.0 / source_wavelengths

  assert material.unit == 'THz'
  assert material.kind == 'e'
  np.testing.assert_allclose(material.f, expected_frequency, rtol=1e-6)
  np.testing.assert_allclose(material.complex, source_indices ** 2, rtol=1e-6)


def test_linear_interpolation_clips_or_extrapolates(material_db: Path):
  material = Material.from_db(
    'Test/linear', db=str(material_db), verbose=False
  )

  interpolated = material.interp(
    jp.array([300.0, 450.0, 800.0]), unit='nm', kind='n'
  )
  extrapolated = material.interp(
    jp.array([300.0, 800.0]), unit='nm', kind='n', extrap=True
  )

  np.testing.assert_allclose(
    interpolated,
    [2 + 0.1j, 2.5 + 0.15j, 5 + 0.4j],
    rtol=1e-6,
  )
  np.testing.assert_allclose(extrapolated, [1 + 0j, 6 + 0.5j], rtol=1e-6)


def test_cubic_interpolation_is_jittable_and_differentiable(material_db: Path):
  material = Material.from_db(
    'Test/linear', db=str(material_db), verbose=False
  )

  def real_index(wavelength):
    return jp.real(material.interp(wavelength, unit='nm', interp='cubic'))

  value = jax.jit(real_index)(jp.array(450.0))
  gradient = jax.grad(real_index)(jp.array(450.0))

  np.testing.assert_allclose(value, 2.5, rtol=1e-6)
  np.testing.assert_allclose(gradient, 0.01, rtol=1e-5)


def test_invalid_interpolation_kind_raises(material_db: Path):
  material = Material.from_db(
    'Test/linear', db=str(material_db), verbose=False
  )

  with pytest.raises(ValueError, match='unsupported interpolation kind'):
    material.interp(500.0, unit='nm', interp='nearest')


def test_missing_database_and_material_raise(tmp_path: Path):
  with pytest.raises(ValueError, match='database directory does not exist'):
    Material.from_db('missing', db=str(tmp_path / 'missing'), verbose=False)

  with pytest.raises(ValueError, match='material database index does not exist'):
    Material.from_db('missing', db=str(tmp_path), verbose=False)


def test_bundled_database_material_is_available():
  material = Material.from_db('Ag/Johnson', verbose=False)

  assert 'Silver' in material.name
  assert material.f.ndim == material.re.ndim == material.im.ndim == 1
  assert material.f.size == material.re.size == material.im.size
  assert material.f.size > 4


def test_avail_lists_bundled_tabulated_materials_and_models():
  materials = Material.avail()
  models = Material.avail('Ag')

  assert materials == sorted(materials, key=str.casefold)
  assert {'Ag', 'Au', 'Si'} <= set(materials)
  assert {'CRC', 'Johnson', 'Palik_ir', 'Palik_vis', 'Rakic'} <= set(models)


def test_avail_uses_provided_tabulated_database(tmp_path: Path):
  custom_db = tmp_path / 'custom-tab'
  custom_db.mkdir()
  _write_material(custom_db)

  assert Material.avail(db=str(custom_db)) == ['Test']
  assert Material.avail('Test', db=str(custom_db)) == ['linear']
  assert Material.avail('missing', db=str(custom_db)) == []


def test_k_tables_and_nonlinear_index_tables(tmp_path: Path):
  _write_material(tmp_path)
  record_path = next((tmp_path / 'Test').glob('*.json'))
  record = json.loads(record_path.read_text(encoding='utf-8'))
  record['data']['type'] = 'nk'
  record_path.write_text(json.dumps(record), encoding='utf-8')
  nk_material = Material.from_db('Test/linear', db=tmp_path, verbose=False)
  np.testing.assert_allclose(nk_material.k(550.0, unit='nm'), 0.25)

  n2_db = tmp_path / 'n2'
  _write_material(n2_db)
  n2_record_path = next((n2_db / 'Test').glob('*.json'))
  n2_record = json.loads(n2_record_path.read_text(encoding='utf-8'))
  n2_record['data'].update({
    'type': 'n2',
    'f': [532],
    're': [8.25e-19],
    'im': [0],
    'unit': 'nm',
  })
  n2_record_path.write_text(json.dumps(n2_record), encoding='utf-8')
  n2_material = Material.from_db('Test/linear', db=n2_db, verbose=False)
  np.testing.assert_allclose(
    n2_material.n2(532.0, unit='nm'), 8.25e-19, rtol=1e-6,
  )
  assert np.isnan(n2_material.n2(531.0, unit='nm'))


def test_json_database_rejects_unsupported_schema_version(material_db: Path):
  index_path = material_db / 'index.json'
  index = json.loads(index_path.read_text(encoding='utf-8'))
  index['schema_version'] = '2'
  index_path.write_text(json.dumps(index), encoding='utf-8')

  with pytest.raises(ValueError, match='unsupported database schema version'):
    Material.avail(db=material_db)


def test_json_database_rejects_record_paths_outside_root(material_db: Path):
  index_path = material_db / 'index.json'
  index = json.loads(index_path.read_text(encoding='utf-8'))
  index['materials']['Test']['records'][0]['path'] = '../outside.json'
  index_path.write_text(json.dumps(index), encoding='utf-8')

  with pytest.raises(ValueError, match='escapes database root'):
    Material.from_db('Test/linear', db=material_db, verbose=False)