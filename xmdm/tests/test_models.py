import json

import jax
import jax.numpy as jp
import numpy as np
import pytest

from xmdm import Cauchy, Drude, Lorentz, RefractiveIndexFormula, Sellmeier


def _write_database(root, model, material_id, name, data, source='Test Source'):
  record_id = '0a8c1393-f8da-4a29-a4bf-100aeb510f3e'
  material_dir = root / material_id
  material_dir.mkdir(parents=True, exist_ok=True)
  record = {
    'schema_version': '1',
    'model': model,
    'name': name,
    'id': record_id,
    'data': data,
    'metadata': {'source': source},
  }
  (material_dir / f'{record_id}.json').write_text(
    json.dumps(record), encoding='utf-8'
  )
  (root / 'index.json').write_text(
    json.dumps({
      'schema_version': '1',
      'materials': {
        material_id: {
          'name': f'Example ({material_id})',
          'aliases': [],
          'records': [{
            'id': record_id,
            'model': model,
            'name': name,
            'source': source,
            'path': f'{material_id}/{record_id}.json',
          }],
        },
      },
    }),
    encoding='utf-8',
  )


def test_drude_parameters_and_units():
  model = Drude.from_params(eps_inf=1.0, omega_p=9.0, gamma=0.2)
  energy = jp.array(2.0)
  expected = 1.0 - 9.0**2 / (energy**2 + 1j * 0.2 * energy)

  np.testing.assert_allclose(model.eps(energy, unit='eV'), expected)
  np.testing.assert_allclose(
    model.eps(619.920992, unit='nm'),
    model.eps(2.0, unit='eV'),
    rtol=2e-6,
  )
  np.testing.assert_allclose(model.n(energy, unit='eV') ** 2, expected)


def test_drude_is_jittable_and_differentiable():
  model = Drude.from_params(eps_inf=1.0, omega_p=9.0, gamma=0.2)
  epsilon = jax.jit(lambda energy: model.eps(energy, unit='eV'))(2.0)
  gradient = jax.grad(
    lambda energy: jp.real(model.eps(energy, unit='eV'))
  )(2.0)
  parameter_gradient = jax.grad(
    lambda candidate: jp.real(candidate.eps(2.0, unit='eV'))
  )(model)

  assert np.isfinite(epsilon)
  assert np.isfinite(gradient)
  assert np.isfinite(parameter_gradient.omega_p)


def test_drude_from_database_record():
  model = Drude.from_db('Ag/Ordal')

  assert model.name == 'Silver (Ag)'
  assert 'Ordal' in model.ref
  np.testing.assert_allclose(model.omega_p, 9.01)
  np.testing.assert_allclose(model.gamma, 0.018)


def test_drude_avail_lists_bundled_materials_and_sources():
  materials = Drude.avail()

  assert {'Ag', 'Au'} <= set(materials)
  assert 'Ordal' in Drude.avail('Ag')


def test_model_avail_uses_provided_database(tmp_path):
  _write_database(
    tmp_path,
    'drude',
    'Ex',
    'Example Source',
    {'eps_inf': 1.0, 'omega_p': 2.0, 'gamma': 0.1},
    source='Example Source (2020)',
  )

  assert Drude.avail(db=tmp_path) == ['Ex']
  assert Drude.avail('Ex', db=tmp_path) == ['Example Source']
  assert Drude.avail('missing', db=tmp_path) == []


def test_lorentz_from_database_supports_multiple_oscillators():
  model = Lorentz.from_db('Ag/Rakic')
  energy = jp.array([1.0, 2.0])
  epsilon = model.eps(energy, unit='eV')

  assert epsilon.shape == energy.shape
  assert model.f.shape == model.gamma.shape == model.omega_0.shape
  assert np.isfinite(epsilon).all()


def test_lorentz_single_oscillator_parameters():
  model = Lorentz.from_params(
    eps_inf=1.0,
    omega_p=4.0,
    gamma=0.1,
    omega_0=2.0,
  )

  np.testing.assert_allclose(
    model.eps(1.0, unit='eV'),
    1.0 + 16.0 / (4.0 - 1.0 - 0.1j),
  )


def test_sellmeier_parameters_use_selected_wavelength_unit():
  model = Sellmeier.from_params(B=[1.0], C=[0.25], unit='um')

  np.testing.assert_allclose(model.eps(1.0, unit='um'), 1 + 1 / 0.75)
  np.testing.assert_allclose(
    model.n(1.0, unit='um') ** 2,
    model.eps(1.0, unit='um'),
  )


def test_sellmeier_rejects_non_wavelength_parameter_unit():
  with pytest.raises(ValueError, match='unsupported Sellmeier wavelength unit'):
    Sellmeier.from_params(B=[1.0], C=[0.25], unit='eV')


def test_cauchy_parameters_use_selected_wavelength_unit():
  model = Cauchy.from_params(A=1.5, B=0.01, C=0.001, unit='um')
  wavelength = jp.array([0.5, 1.0])
  expected_index = 1.5 + 0.01 / wavelength**2 + 0.001 / wavelength**4

  np.testing.assert_allclose(model.n(wavelength, unit='um'), expected_index)
  np.testing.assert_allclose(model.eps(wavelength, unit='um'), expected_index**2)
  derivative = jax.grad(
    lambda coefficient: Cauchy.from_params(
      coefficient, 0.01, 0.001, unit='um'
    ).n(1.0, unit='um')
  )(1.5)
  np.testing.assert_allclose(derivative, 1.0)


def test_cauchy_can_load_from_material_first_database(tmp_path):
  _write_database(
    tmp_path,
    'cauchy',
    'Ex',
    'Example Cauchy',
    {'A': 1.5, 'B': 0.01, 'C': 0.001, 'unit': 'um'},
  )

  model = Cauchy.from_db('Ex/Example Cauchy', db=tmp_path)
  np.testing.assert_allclose(model.n(1.0, unit='um'), 1.511)


def test_cauchy_rejects_non_wavelength_parameter_unit():
  with pytest.raises(ValueError, match='unsupported Cauchy wavelength unit'):
    Cauchy.from_params(A=1.0, B=0.0, C=0.0, unit='eV')


@pytest.mark.parametrize(
  ('formula', 'coefficients', 'expected'),
  [
    (1, [0, 0.1, 2, 0.1, 3, 0.1, 4],
     (1 + 0.1 / -3 + 0.1 / -8 + 0.1 / -15) ** 0.5),
    (2, [0.2, 0.5, 0.1], (1.2 + 0.5 / 0.9) ** 0.5),
    (3, [2, 1, 2, 0.5, 4], 3.5**0.5),
    (4, [2, 1, 2, 0.5, 2, 3, 1, 0.25, 2],
     (2 + 1 / 0.75 + 3 / 0.9375) ** 0.5),
    (5, [1.5, 0.2, -2, 0.1, 2], 1.8),
    (6, [0.1, 0.2, 2], 1.3),
    (7, [1.5, 0.2, 0.1, 0.01, 0.001],
     1.5 + 0.2 / 0.972 + 0.1 / 0.972**2 + 0.011),
    (8, [0.1, 0.2, 0.3, 0.4], 12**0.5),
    (9, [1, 0.2, 0.3, 0.4, 0.5, 0.1],
     (1 + 0.2 / 0.7 + 0.2 / 0.35) ** 0.5),
  ],
)
def test_refractiveindex_formula_families(formula, coefficients, expected):
  model = RefractiveIndexFormula.from_params(formula, coefficients)

  np.testing.assert_allclose(model.n(1.0, unit='um'), expected, rtol=2e-6)


def test_refractiveindex_formula_1_is_jittable_and_supports_nm():
  model = RefractiveIndexFormula.from_params(
    1,
    [0, 0.6961663, 0.0684043, 0.4079426, 0.1162414, 0.8974794, 9.896161],
  )

  wavelength_nm = jax.jit(lambda wavelength: model.n(wavelength, 'nm'))(587.6)
  derivative = jax.grad(
    lambda wavelength: jp.real(model.n(wavelength, 'um')),
  )(0.5876)

  np.testing.assert_allclose(wavelength_nm, 1.458462, rtol=2e-6)
  assert np.isfinite(derivative)


def test_refractiveindex_formula_rejects_incomplete_formula_2():
  model = RefractiveIndexFormula.from_params(
    2, [3.6453, 2.2057, 0.1879, 1.8377],
  )

  with pytest.raises(ValueError, match='incomplete coefficient list'):
    model.n(1.0, unit='um')


def test_sellmeier_avail_is_empty_without_a_sellmeier_database():
  assert Sellmeier.avail() == []


def test_sellmeier_avail_uses_a_provided_database(tmp_path):
  _write_database(
    tmp_path,
    'sellmeier',
    'Ex',
    'Example Source',
    {'B': [1.0], 'C': [0.25], 'unit': 'um'},
    source='Example Source (2020)',
  )

  assert Sellmeier.avail(db=tmp_path) == ['Ex']
  assert Sellmeier.avail('Ex', db=tmp_path) == ['Example Source']
  model = Sellmeier.from_db('Ex/Example Source', db=tmp_path)
  np.testing.assert_allclose(model.eps(1.0, unit='um'), 1 + 1 / 0.75)


def test_model_database_selection_errors_are_explicit(tmp_path):
  (tmp_path / 'index.json').write_text(
    json.dumps({'schema_version': '1', 'materials': {}}),
    encoding='utf-8',
  )
  with pytest.raises(ValueError, match='form'):
    Drude.from_db('Ag', db=tmp_path)

  with pytest.raises(ValueError, match='does not exist'):
    Drude.from_db('Ag/Ordal', db=tmp_path / 'missing')

  with pytest.raises(ValueError, match='not found'):
    Drude.from_db('Ag/Ordal', db=tmp_path)


def test_model_record_schema_and_name_are_validated(tmp_path):
  _write_database(
    tmp_path,
    'drude',
    'Ex',
    'Example Source',
    {'eps_inf': 1.0, 'omega_p': float('nan'), 'gamma': 0.1},
  )

  with pytest.raises(ValueError, match='finite numeric values'):
    Drude.from_db('Ex/Example Source', db=tmp_path)
