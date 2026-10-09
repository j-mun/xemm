from pathlib import Path

import jax
import jax.numpy as jp
import numpy as np
import pytest

from xemm import MaterialData


def _write_material(db: Path) -> None:
  material_dir = db / 'Test'
  material_dir.mkdir()
  (material_dir / 'linear.yml').write_text(
    '''NAME: Linear test material
DATA:
  - type: tabulated
    parm: n
    unit: nm
    data: |
      400  2  0.1
      500  3  0.2
      600  4  0.3
      700  5  0.4
'''
  )


@pytest.fixture
def material_db(tmp_path: Path) -> Path:
  _write_material(tmp_path)
  return tmp_path


def test_from_db_loads_custom_data_without_extension(material_db: Path):
  material = MaterialData.from_db(
    'Test/linear', db=str(material_db), verbose=False
  )

  assert material.name == 'Linear test material'
  assert material.unit == 'nm'
  assert material.parm == 'n'
  np.testing.assert_allclose(material.f, [400, 500, 600, 700])
  np.testing.assert_allclose(
    material.complex,
    [2 + 0.1j, 3 + 0.2j, 4 + 0.3j, 5 + 0.4j],
  )


def test_from_db_converts_coordinates_and_parameters(material_db: Path):
  material = MaterialData.from_db(
    'Test/linear',
    db=str(material_db),
    unit='THz',
    parm='eps',
    verbose=False,
  )

  source_wavelengths = np.array([700, 600, 500, 400])
  source_indices = np.array([5 + 0.4j, 4 + 0.3j, 3 + 0.2j, 2 + 0.1j])
  expected_frequency = 1e-3 * 299_792_458.0 / source_wavelengths

  assert material.unit == 'THz'
  assert material.parm == 'eps'
  np.testing.assert_allclose(material.f, expected_frequency, rtol=1e-6)
  np.testing.assert_allclose(material.complex, source_indices ** 2, rtol=1e-6)


def test_linear_interpolation_clips_or_extrapolates(material_db: Path):
  material = MaterialData.from_db(
    'Test/linear', db=str(material_db), verbose=False
  )

  interpolated = material.interp(
    jp.array([300.0, 450.0, 800.0]), unit='nm', parm='n'
  )
  extrapolated = material.interp(
    jp.array([300.0, 800.0]), unit='nm', parm='n', extrap=True
  )

  np.testing.assert_allclose(
    interpolated,
    [2 + 0.1j, 2.5 + 0.15j, 5 + 0.4j],
    rtol=1e-6,
  )
  np.testing.assert_allclose(extrapolated, [1 + 0j, 6 + 0.5j], rtol=1e-6)


def test_cubic_interpolation_is_jittable_and_differentiable(material_db: Path):
  material = MaterialData.from_db(
    'Test/linear', db=str(material_db), verbose=False
  )

  def real_index(wavelength):
    return jp.real(material.interp(wavelength, unit='nm', kind='cubic'))

  value = jax.jit(real_index)(jp.array(450.0))
  gradient = jax.grad(real_index)(jp.array(450.0))

  np.testing.assert_allclose(value, 2.5, rtol=1e-6)
  np.testing.assert_allclose(gradient, 0.01, rtol=1e-5)


def test_invalid_interpolation_kind_raises(material_db: Path):
  material = MaterialData.from_db(
    'Test/linear', db=str(material_db), verbose=False
  )

  with pytest.raises(ValueError, match='unsupported interpolation kind'):
    material.interp(500.0, unit='nm', kind='nearest')


def test_missing_database_and_material_raise(tmp_path: Path):
  with pytest.raises(ValueError, match='database directory does not exist'):
    MaterialData.from_db('missing', db=str(tmp_path / 'missing'), verbose=False)

  with pytest.raises(ValueError, match='material data file does not exist'):
    MaterialData.from_db('missing', db=str(tmp_path), verbose=False)


def test_bundled_database_material_is_available():
  material = MaterialData.from_db('Ag/Johnson', verbose=False)

  assert 'Silver' in material.name
  assert material.f.ndim == material.re.ndim == material.im.ndim == 1
  assert material.f.size == material.re.size == material.im.size
  assert material.f.size > 4


def test_avail_lists_bundled_tabulated_materials_and_models():
  materials = MaterialData.avail()
  models = MaterialData.avail('Ag')

  assert materials == sorted(materials, key=str.casefold)
  assert {'Ag', 'Au', 'Si'} <= set(materials)
  assert models == ['CRC', 'Johnson', 'Palik_ir', 'Palik_vis', 'Rakic']


def test_avail_uses_provided_tabulated_database(tmp_path: Path):
  custom_db = tmp_path / 'custom-tab'
  custom_db.mkdir()
  _write_material(custom_db)
  (custom_db / 'Other').mkdir()
  (custom_db / 'Other' / 'table.yaml').write_text('NAME: Other\n')

  assert MaterialData.avail(db=str(custom_db)) == ['Other', 'Test']
  assert MaterialData.avail('Test', db=str(custom_db)) == ['linear']
  assert MaterialData.avail('missing', db=str(custom_db)) == []