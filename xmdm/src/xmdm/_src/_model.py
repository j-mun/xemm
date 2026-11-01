"""JAX-compatible optical material dispersion models."""

from __future__ import annotations

import math
import os
from typing import Any

import jax
import jax.numpy as jp
import xser
from ..db.validation import numeric_parameter

from ._tabulated import _convert_unit
from ..db.database import (
  available_model_materials,
  available_records,
  load_record,  
)

Array = jax.Array


def _energy_eV(frequency: Array, unit: str) -> Array:
  """Convert a spectral coordinate to photon energy in eV."""
  return _convert_unit(frequency, unit, 'eV')


def _available_model_entries(
    model: str,
    name: str | None,
    db: str | os.PathLike[str] | None,
) -> list[str]:
  if name is None:
    return available_model_materials(model, db)
  return available_records(name, model, db)


def _metadata(record: dict[str, Any], material_name: str) -> dict[str, str | None]:
  source = record.get('metadata', {}).get('source')
  return {
    'name': material_name,
    'ref': source if isinstance(source, str) else None,
  }


def _numeric_parameter(
    value: Any,
    name: str,
    *,
    array: bool = False,
) -> Array:
  return jp.asarray(
    numeric_parameter(value, name, array=array), dtype=jp.float32,
  )


class Drude(xser.SpecNode):
  """Free-carrier dispersion model with parameters expressed in eV."""

  _data = ('eps_inf', 'omega_p', 'gamma')
  _meta = ('name', 'ref')

  eps_inf: Array
  omega_p: Array
  gamma: Array
  name: str | None
  ref: str | None

  @classmethod
  def avail(
      cls,
      name: str | None = None,
      db: str | os.PathLike[str] | None = None,
  ) -> list[str]:
    """List materials or Drude record names in the selected JSON database."""
    return _available_model_entries('drude', name, db)

  @classmethod
  def from_db(
      cls, name: str, db: str | os.PathLike[str] | None = None
  ) -> Drude:
    """Load a material/name record from the material-first JSON database."""
    record, material_name = load_record(name, 'drude', db)
    try:
      parameters = {
        key: _numeric_parameter(record['data'][key], key)
        for key in ('eps_inf', 'omega_p', 'gamma')
      }
    except (KeyError, TypeError) as error:
      raise ValueError(f'invalid Drude parameters for {name!r}') from error
    return cls(**parameters, **_metadata(record, material_name))

  @classmethod
  def from_params(
      cls,
      eps_inf: Any,
      omega_p: Any,
      gamma: Any,
      *,
      name: str | None = None,
      ref: str | None = None,
  ) -> Drude:
    """Create a Drude model; frequency parameters are photon energies in eV."""
    return cls(
      eps_inf=jp.asarray(eps_inf),
      omega_p=jp.asarray(omega_p),
      gamma=jp.asarray(gamma),
      name=name,
      ref=ref,
    )

  def eps(self, frequency: Array, unit: str = 'eV') -> Array:
    energy = _energy_eV(frequency, unit)
    return self.eps_inf - self.omega_p**2 / (
      energy**2 + 1j * self.gamma * energy
    )

  def n(self, frequency: Array, unit: str = 'eV') -> Array:
    return jp.sqrt(self.eps(frequency, unit) + 0j)


class Lorentz(xser.SpecNode):
  """One or more damped Lorentz oscillators, with parameters in eV."""

  _data = ('eps_inf', 'omega_p', 'gamma', 'omega_0', 'f')
  _meta = ('name', 'ref')

  eps_inf: Array
  omega_p: Array
  gamma: Array
  omega_0: Array
  f: Array
  name: str | None
  ref: str | None

  @classmethod
  def avail(
      cls,
      name: str | None = None,
      db: str | os.PathLike[str] | None = None,
  ) -> list[str]:
    """List materials or Lorentz record names in the selected JSON database."""
    return _available_model_entries('lorentz', name, db)

  @classmethod
  def from_db(
      cls, name: str, db: str | os.PathLike[str] | None = None
  ) -> Lorentz:
    """Load a material/name record from the material-first JSON database."""
    record, material_name = load_record(name, 'lorentz', db)
    try:
      parameters = {
        'eps_inf': _numeric_parameter(record['data']['eps_inf'], 'eps_inf'),
        'omega_p': _numeric_parameter(record['data']['omega_p'], 'omega_p'),
        'gamma': _numeric_parameter(
          record['data']['gamma'], 'gamma', array=True
        ),
        'omega_0': _numeric_parameter(
          record['data']['omega_0'], 'omega_0', array=True
        ),
        'f': _numeric_parameter(record['data']['f'], 'f', array=True),
      }
    except (KeyError, TypeError) as error:
      raise ValueError(f'invalid Lorentz parameters for {name!r}') from error
    if not (
      parameters['f'].ndim == parameters['gamma'].ndim
      == parameters['omega_0'].ndim == 1
      and parameters['f'].shape == parameters['gamma'].shape
      == parameters['omega_0'].shape
    ):
      raise ValueError(f'invalid Lorentz oscillator arrays for {name!r}')
    return cls(**parameters, **_metadata(record, material_name))

  @classmethod
  def from_params(
      cls,
      eps_inf: Any,
      omega_p: Any,
      gamma: Any,
      omega_0: Any,
      f: Any = 1.0,
      *,
      name: str | None = None,
      ref: str | None = None,
  ) -> Lorentz:
    """Create a Lorentz model; oscillator energies and damping are in eV."""
    return cls(
      eps_inf=jp.asarray(eps_inf),
      omega_p=jp.asarray(omega_p),
      gamma=jp.asarray(gamma),
      omega_0=jp.asarray(omega_0),
      f=jp.asarray(f),
      name=name,
      ref=ref,
    )

  def eps(self, frequency: Array, unit: str = 'eV') -> Array:
    energy = _energy_eV(frequency, unit)
    denominator = (
      self.omega_0**2 - energy[..., None]**2
      - 1j * self.gamma * energy[..., None]
    )
    return self.eps_inf + jp.sum(
      self.f * self.omega_p**2 / denominator, axis=-1
    )

  def n(self, frequency: Array, unit: str = 'eV') -> Array:
    return jp.sqrt(self.eps(frequency, unit) + 0j)


class Sellmeier(xser.SpecNode):
  """Lossless Sellmeier dispersion model with wavelength coefficients."""

  _data = ('B', 'C')
  _meta = ('unit',)

  B: Array
  C: Array
  unit: str

  @classmethod
  def avail(
      cls,
      name: str | None = None,
      db: str | os.PathLike[str] | None = None,
  ) -> list[str]:
    """List materials or Sellmeier record names in the JSON database."""
    return _available_model_entries('sellmeier', name, db)

  @classmethod
  def from_db(
      cls, name: str, db: str | os.PathLike[str] | None = None
  ) -> Sellmeier:
    record, _ = load_record(name, 'sellmeier', db)
    data = record['data']
    try:
      B = _numeric_parameter(data['B'], 'B', array=True)
      C = _numeric_parameter(data['C'], 'C', array=True)
      unit = data.get('unit', 'um')
    except (KeyError, TypeError, ValueError) as error:
      raise ValueError(f'invalid Sellmeier parameters for {name!r}') from error
    if B.ndim != 1 or C.ndim != 1 or B.shape != C.shape or B.size == 0:
      raise ValueError(f'invalid Sellmeier coefficient arrays for {name!r}')
    if unit not in ('m', 'nm', 'um'):
      raise ValueError(f'unsupported Sellmeier wavelength unit: {unit!r}')
    return cls(B=B, C=C, unit=unit)

  @classmethod
  def from_params(
      cls, B: Any, C: Any, unit: str = 'um'
  ) -> Sellmeier:
    """Create a model; ``C`` is in the square of the selected wavelength unit."""
    if unit not in ('m', 'nm', 'um'):
      raise ValueError(f'unsupported Sellmeier wavelength unit: {unit!r}')
    return cls(B=jp.asarray(B), C=jp.asarray(C), unit=unit)

  def eps(self, frequency: Array, unit: str = 'um') -> Array:
    wavelength = _convert_unit(frequency, unit, self.unit)
    wavelength_squared = wavelength[..., None] ** 2
    return 1 + jp.sum(
      self.B * wavelength_squared / (wavelength_squared - self.C),
      axis=-1,
    )

  def n(self, frequency: Array, unit: str = 'um') -> Array:
    return jp.sqrt(self.eps(frequency, unit) + 0j)


class Cauchy(xser.SpecNode):
  """Cauchy refractive-index model with wavelength coefficients."""

  _data = ('A', 'B', 'C')
  _meta = ('unit',)

  A: Array
  B: Array
  C: Array
  unit: str

  @classmethod
  def avail(
      cls,
      name: str | None = None,
      db: str | os.PathLike[str] | None = None,
  ) -> list[str]:
    """List materials or Cauchy record names in the JSON database."""
    return _available_model_entries('cauchy', name, db)

  @classmethod
  def from_db(
      cls, name: str, db: str | os.PathLike[str] | None = None
  ) -> Cauchy:
    record, _ = load_record(name, 'cauchy', db)
    data = record['data']
    try:
      A = _numeric_parameter(data['A'], 'A')
      B = _numeric_parameter(data['B'], 'B')
      C = _numeric_parameter(data['C'], 'C')
    except (KeyError, TypeError) as error:
      raise ValueError(f'invalid Cauchy parameters for {name!r}') from error
    unit = data.get('unit', 'um')
    if unit not in ('m', 'nm', 'um'):
      raise ValueError(f'unsupported Cauchy wavelength unit: {unit!r}')
    return cls(A=A, B=B, C=C, unit=unit)

  @classmethod
  def from_params(
      cls, A: Any, B: Any, C: Any, unit: str = 'um'
  ) -> Cauchy:
    """Create a model; ``B`` and ``C`` use the square/fourth power of unit."""
    if unit not in ('m', 'nm', 'um'):
      raise ValueError(f'unsupported Cauchy wavelength unit: {unit!r}')
    return cls(
      A=jp.asarray(A),
      B=jp.asarray(B),
      C=jp.asarray(C),
      unit=unit,
    )

  def n(self, frequency: Array, unit: str = 'um') -> Array:
    wavelength = _convert_unit(frequency, unit, self.unit)
    wavelength_squared = wavelength**2
    return self.A + self.B / wavelength_squared + self.C / wavelength_squared**2

  def eps(self, frequency: Array, unit: str = 'um') -> Array:
    refractive_index = self.n(frequency, unit)
    return refractive_index**2


class RefractiveIndexFormula(xser.SpecNode):
  """Analytic refractive-index formulas used by RefractiveIndex.INFO."""

  _data = ('coefficients',)
  _meta = ('formula', 'unit', 'wavelength_range', 'name', 'ref')

  coefficients: Array
  formula: int
  unit: str
  wavelength_range: tuple[float, float] | None
  name: str | None
  ref: str | None

  @classmethod
  def avail(
      cls,
      name: str | None = None,
      db: str | os.PathLike[str] | None = None,
  ) -> list[str]:
    """List materials or RefractiveIndex.INFO formula record names."""
    return _available_model_entries('rii_formula', name, db)

  @classmethod
  def from_db(
      cls, name: str, db: str | os.PathLike[str] | None = None,
  ) -> RefractiveIndexFormula:
    record, material_name = load_record(name, 'rii_formula', db)
    data = record['data']
    try:
      formula = data['formula']
      coefficients = _numeric_parameter(
        data['coefficients'], 'coefficients', array=True,
      )
      unit = data.get('unit', 'um')
      range_value = data.get('wavelength_range')
      wavelength_range = (
        tuple(float(value) for value in range_value)
        if range_value is not None else None
      )
    except (KeyError, TypeError, ValueError) as error:
      raise ValueError(
        f'invalid RefractiveIndex.INFO formula parameters for {name!r}',
      ) from error
    metadata = _metadata(record, material_name)
    return cls(
      coefficients=coefficients,
      formula=formula,
      unit=unit,
      wavelength_range=wavelength_range,
      **metadata,
    )

  @classmethod
  def from_params(
      cls,
      formula: int,
      coefficients: Any,
      unit: str = 'um',
      wavelength_range: tuple[float, float] | None = None,
      *,
      name: str | None = None,
      ref: str | None = None,
  ) -> RefractiveIndexFormula:
    """Create a model using a formula number and its ordered coefficients."""
    if isinstance(formula, bool) or not isinstance(formula, int) or not 1 <= formula <= 9:
      raise ValueError('formula must be an integer from 1 to 9')
    if unit not in ('m', 'nm', 'um'):
      raise ValueError('RefractiveIndex.INFO formulas require a wavelength unit')
    values = numeric_parameter(coefficients, 'coefficients', array=True)
    if not 1 <= len(values) <= 17:
      raise ValueError('formula coefficients must contain 1 to 17 values')
    parsed_range = wavelength_range
    if parsed_range is not None and (
      len(parsed_range) != 2
      or not all(math.isfinite(value) for value in parsed_range)
      or parsed_range[0] <= 0
      or parsed_range[1] <= parsed_range[0]
    ):
      raise ValueError('wavelength_range must be two increasing positive values')
    return cls(
      coefficients=_numeric_parameter(values, 'coefficients', array=True),
      formula=formula,
      unit=unit,
      wavelength_range=parsed_range,
      name=name,
      ref=ref,
    )

  def n(self, frequency: Array, unit: str = 'um') -> Array:
    wavelength = _convert_unit(frequency, unit, self.unit)
    wavelength_squared = wavelength**2
    coefficients = self.coefficients
    formula = self.formula

    if formula in (1, 2):
      if coefficients.size < 3 or coefficients.size % 2 == 0:
        raise ValueError(
          f'RefractiveIndex.INFO formula {formula} has an incomplete '
          'coefficient list',
        )
      n_squared = 1 + coefficients[0]
      for index in range(1, coefficients.size - 1, 2):
        pole = coefficients[index + 1]
        if formula == 1:
          pole = pole**2
        n_squared = n_squared + (
          coefficients[index] * wavelength_squared
          / (wavelength_squared - pole)
        )
      return jp.sqrt(n_squared + 0j)

    if formula == 3:
      if coefficients.size % 2 == 0:
        raise ValueError('RefractiveIndex.INFO formula 3 has incomplete coefficients')
      n_squared = jp.zeros_like(wavelength) + coefficients[0]
      for index in range(1, coefficients.size - 1, 2):
        n_squared = n_squared + (
          coefficients[index] * wavelength**coefficients[index + 1]
        )
      return jp.sqrt(n_squared + 0j)

    if formula == 4:
      if coefficients.size < 9:
        raise ValueError('RefractiveIndex.INFO formula 4 needs at least 9 coefficients')
      n_squared = jp.zeros_like(wavelength) + coefficients[0]
      for index in range(1, min(coefficients.size, 9), 4):
        n_squared = n_squared + (
          coefficients[index] * wavelength**coefficients[index + 1]
          / (
            wavelength_squared
            - coefficients[index + 2]**coefficients[index + 3]
          )
        )
      for index in range(9, coefficients.size - 1, 2):
        n_squared = n_squared + (
          coefficients[index] * wavelength**coefficients[index + 1]
        )
      return jp.sqrt(n_squared + 0j)

    if formula == 5:
      if coefficients.size % 2 == 0:
        raise ValueError('RefractiveIndex.INFO formula 5 has incomplete coefficients')
      refractive_index = jp.zeros_like(wavelength) + coefficients[0]
      for index in range(1, coefficients.size - 1, 2):
        refractive_index = refractive_index + (
          coefficients[index] * wavelength**coefficients[index + 1]
        )
      return refractive_index + 0j

    if formula == 6:
      if coefficients.size < 3 or coefficients.size % 2 == 0:
        raise ValueError('RefractiveIndex.INFO formula 6 has incomplete coefficients')
      refractive_index = 1 + coefficients[0]
      for index in range(1, coefficients.size - 1, 2):
        refractive_index = refractive_index + (
          coefficients[index]
          / (coefficients[index + 1] - wavelength**-2)
        )
      return refractive_index + jp.zeros_like(wavelength, dtype=jp.complex64)

    if formula == 7:
      if coefficients.size < 2:
        raise ValueError('RefractiveIndex.INFO formula 7 needs at least 2 coefficients')
      refractive_index = jp.zeros_like(wavelength) + coefficients[0]
      shifted_square = wavelength_squared - 0.028
      for index in range(1, coefficients.size):
        if index == 1:
          term = 1 / shifted_square
        elif index == 2:
          term = 1 / shifted_square**2
        else:
          term = wavelength**(2 * (index - 2))
        refractive_index = refractive_index + coefficients[index] * term
      return refractive_index + 0j

    if formula == 8:
      if coefficients.size != 4:
        raise ValueError('RefractiveIndex.INFO formula 8 needs 4 coefficients')
      ratio = (
        coefficients[0]
        + coefficients[1] * wavelength_squared
        / (wavelength_squared - coefficients[2])
        + coefficients[3] * wavelength_squared
      )
      return jp.sqrt((1 + 2 * ratio) / (1 - ratio) + 0j)

    if formula == 9:
      if coefficients.size != 6:
        raise ValueError('RefractiveIndex.INFO formula 9 needs 6 coefficients')
      shifted = wavelength - coefficients[4]
      n_squared = (
        coefficients[0]
        + coefficients[1] / (wavelength_squared - coefficients[2])
        + coefficients[3] * shifted / (shifted**2 + coefficients[5])
      )
      return jp.sqrt(n_squared + 0j)

    raise ValueError(f'unsupported RefractiveIndex.INFO formula: {formula}')

  def eps(self, frequency: Array, unit: str = 'um') -> Array:
    refractive_index = self.n(frequency, unit)
    return refractive_index**2


__all__ = [
  'Cauchy',
  'Drude',
  'Lorentz',
  'RefractiveIndexFormula',
  'Sellmeier',
]
