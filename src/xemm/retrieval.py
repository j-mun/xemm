"""Retrieve optical properties from ellipsometric and S-parameter data."""

from __future__ import annotations

from typing import NamedTuple

import jax.numpy as jp

from .tabulated import _convert_unit

Array = jp.ndarray


class SParameterResult(NamedTuple):
  """Effective relative properties retrieved for a homogeneous slab."""

  n: Array
  z: Array
  eps: Array
  mu: Array


def ellipsometry_rho(
    psi: Array,
    delta: Array,
    *,
    angle_unit: str = 'deg',
) -> Array:
  """Convert ellipsometric Psi and Delta to ``rho = tan(Psi) exp(i Delta)``."""
  if angle_unit == 'deg':
    scale = jp.pi / 180
  elif angle_unit == 'rad':
    scale = 1.0
  else:
    raise ValueError(f'unsupported ellipsometry angle unit: {angle_unit!r}')
  psi_rad = jp.asarray(psi) * scale
  delta_rad = jp.asarray(delta) * scale
  return jp.tan(psi_rad) * jp.exp(1j * delta_rad)


def ellipsometry_index(
    psi: Array,
    delta: Array,
    incidence_angle: Array,
    *,
    ambient_index: Array = 1.0,
    angle_unit: str = 'deg',
) -> Array:
  """Retrieve the pseudo-index of a bare, isotropic semi-infinite interface.

  ``psi`` and ellipsometric ``delta`` are the measured angles. The incidence
  angle uses ``angle_unit`` as well. This pointwise inversion assumes a single
  interface with known, real ambient index; it does not model films,
  substrates, roughness, or anisotropy.
  """
  rho = ellipsometry_rho(psi, delta, angle_unit=angle_unit)
  scale = jp.pi / 180 if angle_unit == 'deg' else 1.0
  theta = jp.asarray(incidence_angle) * scale
  ambient = jp.asarray(ambient_index)
  ratio = (1 - rho) / (1 + rho)
  epsilon = (
    ambient**2 * jp.sin(theta)**2
    * (1 + jp.tan(theta)**2 * ratio**2)
  )
  index = jp.sqrt(epsilon + 0j)
  return jp.where(jp.imag(index) < 0, -index, index)


def retrieve_sparameters(
    s11: Array,
    s21: Array,
    thickness: Array,
    frequency: Array,
    *,
    unit: str = 'Hz',
    s22: Array | None = None,
    s12: Array | None = None,
    branch: int = 0,
    unwrap: bool = True,
) -> SParameterResult:
  """Retrieve effective ``n``, impedance ``z``, ``eps``, and ``mu`` from S data.

  Uses the transfer-matrix inversion of a homogeneous slab at normal
  incidence. Supply ``s22`` for asymmetric reflection; ``s12`` defaults to
  ``s21`` and ``s22`` defaults to ``s11``. ``frequency`` accepts the spectral
  units supported by :class:`MaterialData`; ``thickness`` is in metres.

  The returned phase branch is selected by ``branch`` and optionally
  unwrapped along the last array axis. This does not infer a globally correct
  branch from a single frequency point.
  """
  r1 = jp.asarray(s11, dtype=jp.complex64)
  t21 = jp.asarray(s21, dtype=jp.complex64)
  r2 = r1 if s22 is None else jp.asarray(s22, dtype=jp.complex64)
  t12 = t21 if s12 is None else jp.asarray(s12, dtype=jp.complex64)
  r1, t21, r2, t12 = jp.broadcast_arrays(r1, t21, r2, t12)

  denominator = 2 * t21
  a = ((1 + r1) * (1 - r2) + t12 * t21) / denominator
  b = ((1 + r1) * (1 + r2) - t12 * t21) / denominator
  c = ((1 - r1) * (1 - r2) - t12 * t21) / denominator
  d = ((1 - r1) * (1 + r2) + t12 * t21) / denominator

  phase = jp.arccos((a + d) / 2)
  phase = jp.where(jp.imag(phase) < 0, -phase, phase)
  if unwrap and phase.ndim > 0:
    phase = jp.unwrap(jp.real(phase)) + 1j * jp.imag(phase)
  phase = phase + 2 * jp.pi * branch

  wavelength = _convert_unit(frequency, unit, 'm')
  k0 = 2 * jp.pi / wavelength
  index = phase / (k0 * jp.asarray(thickness))

  impedance = jp.sqrt(b / c + 0j)
  impedance = jp.where(jp.real(impedance) < 0, -impedance, impedance)
  return SParameterResult(
    n=index,
    z=impedance,
    eps=index / impedance,
    mu=index * impedance,
  )


__all__ = [
  'SParameterResult',
  'ellipsometry_index',
  'ellipsometry_rho',
  'retrieve_sparameters',
]
