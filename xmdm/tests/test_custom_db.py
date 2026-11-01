from pathlib import Path

import numpy as np
import pytest

from xmdm import (
  Cauchy,
  Drude,
  Material,
  available_materials,
  available_model_materials,
  available_records,
  database_directory,
  load_index,
  load_record,
  validate_record_data,
)


CUSTOM_DB = Path(__file__).resolve().parent / 'custom-db'


def test_custom_database_catalog_and_model_availability():
  assert database_directory(CUSTOM_DB) == CUSTOM_DB
  root, index = load_index(CUSTOM_DB)
  assert root == CUSTOM_DB
  assert index['schema_version'] == '1'
  assert available_materials(db=CUSTOM_DB) == ['Example']
  assert available_model_materials('tabulated', db=CUSTOM_DB) == ['Example']
  assert available_model_materials('cauchy', db=CUSTOM_DB) == ['Example']
  assert Material.avail(db=CUSTOM_DB) == ['Example']
  assert Material.avail('Example', db=CUSTOM_DB) == ['linear']
  assert Cauchy.avail('Example', db=CUSTOM_DB) == ['cauchy']
  assert Drude.avail(db=CUSTOM_DB) == []
  assert available_records('Example', 'drude', db=CUSTOM_DB) == []
  assert Material.avail('missing', db=CUSTOM_DB) == []
  assert Material.avail('Ag', db=CUSTOM_DB) == []


@pytest.mark.parametrize('selector', [
  'Example/linear',
  'example/LINEAR',
  'demo/linear',
  'Synthetic optical material/linear',
])
def test_import_custom_tabulated_data(selector):
  material = Material.from_db(selector, db=CUSTOM_DB, verbose=False)

  assert material.name == 'Synthetic optical material'
  assert material.unit == 'nm'
  assert material.kind == 'n'
  np.testing.assert_allclose(material.f, [400, 500, 600, 700])
  np.testing.assert_allclose(
    material.complex, [2 + 0.1j, 3 + 0.2j, 4 + 0.3j, 5 + 0.4j],
    rtol=1e-6,
  )
  assert Material.avail('DEMO', db=CUSTOM_DB) == ['linear']
  assert available_records('demo', 'cauchy', db=CUSTOM_DB) == ['cauchy']


@pytest.mark.parametrize('interpolation', ['linear', 'cubic'])
def test_interpolate_custom_data_and_convert_to_permittivity(interpolation):
  material = Material.from_db('Example/linear', db=CUSTOM_DB, verbose=False)
  wavelengths = np.array([450.0, 550.0, 650.0])
  expected = np.array([2.5 + 0.15j, 3.5 + 0.25j, 4.5 + 0.35j])

  np.testing.assert_allclose(
    material.interp(wavelengths, unit='nm', kind='n', interp=interpolation),
    expected, rtol=1e-6,
  )
  np.testing.assert_allclose(
    material.eps(wavelengths, unit='nm', interp=interpolation),
    expected**2, rtol=1e-6,
  )


def test_import_custom_data_with_unit_and_property_conversion():
  material = Material.from_db(
    'Example/linear', db=str(CUSTOM_DB), unit='THz', kind='e', verbose=False,
  )
  indices = np.array([5 + 0.4j, 4 + 0.3j, 3 + 0.2j, 2 + 0.1j])

  assert material.unit == 'THz'
  assert material.kind == 'e'
  np.testing.assert_allclose(
    material.f, 299_792.458 / np.array([700, 600, 500, 400]), rtol=1e-6,
  )
  np.testing.assert_allclose(material.complex, indices**2, rtol=1e-6)


def test_import_custom_cauchy_model():
  model = Cauchy.from_db('demo/cauchy', db=CUSTOM_DB)
  wavelengths_um = np.array([0.5, 1.0])
  expected = 1.5 + 0.01 / wavelengths_um**2 + 0.001 / wavelengths_um**4

  assert model.unit == 'um'
  np.testing.assert_allclose(model.n(wavelengths_um, unit='um'), expected)
  np.testing.assert_allclose(model.eps(wavelengths_um * 1000, unit='nm'), expected**2)


def test_custom_records_preserve_physics_and_validate():
  _, index = load_index(CUSTOM_DB)
  for reference in index['materials']['Example']['records']:
    record, name = load_record(
      f'Example/{reference["name"]}', reference['model'], db=CUSTOM_DB,
    )
    assert name == 'Synthetic optical material'
    assert record['id'] == reference['id']
    assert record['physics'] == reference['physics'] == 'optics'
    assert record['metadata']['source'].startswith('Synthetic test')
    validate_record_data(record)


@pytest.mark.parametrize(('selector', 'model'), [
  ('missing/linear', Material),
  ('Example/missing', Material),
  ('Example/cauchy', Material),
  ('Example/linear', Cauchy),
  ('Ag/Johnson', Material),
])
def test_custom_database_missing_records_do_not_fall_back(selector, model):
  with pytest.raises(ValueError, match='not found'):
    model.from_db(selector, db=CUSTOM_DB)
