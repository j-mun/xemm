import jax
import jax.numpy as jp
import numpy as np
import pytest

from xemm import Drude, Lorentz, Sellmeier


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
  (tmp_path / 'drude.yml').write_text(
    '''materials:
  - name: Example (Ex)
    ref: Example Source (2020)
    eps_inf: 1.0
    omega_p: 2.0
    gamma: 0.1
'''
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


def test_sellmeier_avail_is_empty_without_a_sellmeier_database():
  assert Sellmeier.avail() == []


def test_sellmeier_avail_uses_a_provided_database(tmp_path):
  (tmp_path / 'sellmeier.yml').write_text(
    '''materials:
  - name: Example (Ex)
    ref: Example Source (2020)
'''
  )

  assert Sellmeier.avail(db=tmp_path) == ['Ex']
  assert Sellmeier.avail('Ex', db=tmp_path) == ['Example Source']


def test_model_database_selection_errors_are_explicit(tmp_path):
  with pytest.raises(ValueError, match='form'):
    Drude.from_db('Ag', db=tmp_path)

  with pytest.raises(ValueError, match='does not exist'):
    Drude.from_db('Ag/Ordal', db=tmp_path)

  (tmp_path / 'drude.yml').write_text('materials: []\n')
  with pytest.raises(ValueError, match='not found'):
    Drude.from_db('Ag/Ordal', db=tmp_path)
