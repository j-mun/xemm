import jax
import jax.numpy as jp
import numpy as np

from xemm import ellipsometry_index, ellipsometry_rho, retrieve_sparameters


def test_ellipsometry_rho_converts_degrees_and_radians():
  rho_degrees = ellipsometry_rho(30.0, 45.0)
  rho_radians = ellipsometry_rho(
    jp.deg2rad(30.0), jp.deg2rad(45.0), angle_unit='rad'
  )

  np.testing.assert_allclose(rho_degrees, rho_radians)


def test_bare_interface_ellipsometry_recovers_complex_index():
  index = 1.7 + 0.2j
  theta = jp.deg2rad(60.0)
  transmitted_cosine = jp.sqrt(index**2 - jp.sin(theta)**2)
  r_s = (jp.cos(theta) - transmitted_cosine) / (
    jp.cos(theta) + transmitted_cosine
  )
  r_p = (index**2 * jp.cos(theta) - transmitted_cosine) / (
    index**2 * jp.cos(theta) + transmitted_cosine
  )
  rho = r_p / r_s
  psi = jp.rad2deg(jp.arctan(jp.abs(rho)))
  delta = jp.rad2deg(jp.angle(rho))

  recovered = ellipsometry_index(psi, delta, 60.0)
  np.testing.assert_allclose(recovered, index, rtol=1e-6)


def test_sparameter_retrieval_recovers_slab_parameters():
  index = 1.8 + 0.1j
  impedance = 1.2 + 0.05j
  thickness = 0.05
  wavelength = 1.0
  phase = 2 * jp.pi * index * thickness / wavelength
  a = jp.cos(phase)
  b = -1j * impedance * jp.sin(phase)
  c = -1j * jp.sin(phase) / impedance
  d = a
  denominator = a + b + c + d
  s21 = 2 / denominator
  s11 = (a + b - c - d) / denominator
  s22 = (-a + b - c + d) / denominator
  s12 = 2 * (a * d - b * c) / denominator

  result = retrieve_sparameters(
    s11,
    s21,
    thickness,
    wavelength,
    unit='m',
    s22=s22,
    s12=s12,
    unwrap=False,
  )

  np.testing.assert_allclose(result.n, index, rtol=2e-6)
  np.testing.assert_allclose(result.z, impedance, rtol=2e-6)
  np.testing.assert_allclose(result.eps, index / impedance, rtol=2e-6)
  np.testing.assert_allclose(result.mu, index * impedance, rtol=2e-6)


def test_sparameter_retrieval_is_jittable():
  def retrieve(s11, s21):
    return retrieve_sparameters(
      s11, s21, thickness=0.05, frequency=1.0, unit='m', unwrap=False
    ).n

  result = jax.jit(retrieve)(jp.asarray(0.1 + 0.02j), jp.asarray(0.7 - 0.1j))
  assert np.isfinite(result)
