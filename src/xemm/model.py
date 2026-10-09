"""JAX-compatible optical material dispersion models."""

from __future__ import annotations

import os
import re
import unicodedata
from typing import Any

import jax
import jax.numpy as jp
import yaml
import xser

from .tabulated import _convert_unit
from .paths import resolve_model_file

Array = jax.Array


def _energy_eV(frequency: Array, unit: str) -> Array:
  """Convert a spectral coordinate to photon energy in eV."""
  return _convert_unit(frequency, unit, 'eV')


def _normalized(value: str) -> str:
  return ''.join(
    character for character in unicodedata.normalize('NFKD', value).casefold()
    if not unicodedata.combining(character)
  )


def _model_records(
    filename: str,
    db: str | os.PathLike[str] | None,
    *,
    missing_ok: bool = False,
) -> tuple[str | None, list[dict[str, Any]]]:
  path = resolve_model_file(filename, db, missing_ok=missing_ok)
  if path is None:
    return None, []
  with path.open(encoding='utf-8') as stream:
    raw = yaml.safe_load(stream)

  records = raw.get('materials') if isinstance(raw, dict) else None
  if not isinstance(records, list) or not all(
    isinstance(record, dict) for record in records
  ):
    raise ValueError(f'invalid model database file: {str(path)!r}')
  return str(path), records


def _material_label(record: dict[str, Any]) -> str | None:
  value = record.get('name')
  if not isinstance(value, str):
    return None
  match = re.search(r'\(([^()]+)\)\s*$', value)
  return match.group(1).strip() if match else value


def _source_label(record: dict[str, Any]) -> str | None:
  value = record.get('ref')
  if not isinstance(value, str):
    return None
  source = value.split('(', maxsplit=1)[0].rstrip(' ,;.')
  source = re.sub(r'\s+et\s+al\.?$', '', source, flags=re.IGNORECASE).strip()
  return source or value


def _available_model_entries(
    filename: str,
    name: str | None,
    db: str | os.PathLike[str] | None,
    *,
    missing_ok: bool = False,
) -> list[str]:
  _, records = _model_records(filename, db, missing_ok=missing_ok)
  if name is None:
    return sorted(
      {
        label
        for record in records
        if (label := _material_label(record)) is not None
      },
      key=str.casefold,
    )

  material_query = _normalized(name)
  matching_records = [
    record for record in records
    if (
      (label := _material_label(record)) is not None
      and material_query in _normalized(label)
    ) or (
      isinstance(record.get('name'), str)
      and material_query in _normalized(record['name'])
    )
  ]
  if not matching_records:
    return []
  sources = {
    source
    for record in matching_records
    if (source := _source_label(record)) is not None
  }
  return sorted(sources, key=str.casefold)


def _model_record(
    name: str,
    filename: str,
    db: str | os.PathLike[str] | None,
) -> dict[str, Any]:
  """Load one record from the current model-database YAML layout."""
  parts = name.split('/', maxsplit=1)
  if len(parts) != 2 or not all(parts):
    raise ValueError("model name must have the form 'material/source'")
  material_query, source_query = (_normalized(part) for part in parts)

  path, records = _model_records(filename, db)
  if path is None:
    raise ValueError(f'model database file does not exist: {filename!r}')

  matches = [
    record for record in records
    if material_query in _normalized(str(record.get('name', '')))
    and source_query in _normalized(str(record.get('ref', '')))
  ]
  if not matches:
    raise ValueError(f'model entry {name!r} not found in {path!r}')
  if len(matches) > 1:
    raise ValueError(f'model entry {name!r} is ambiguous in {path!r}')
  return matches[0]


def _metadata(record: dict[str, Any]) -> dict[str, str | None]:
  name = record.get('name')
  ref = record.get('ref')
  return {
    'name': name if isinstance(name, str) else None,
    'ref': ref if isinstance(ref, str) else None,
  }


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
    """List materials or Drude data sources in the selected model database."""
    return _available_model_entries('drude.yml', name, db)

  @classmethod
  def from_db(
      cls, name: str, db: str | os.PathLike[str] | None = None
  ) -> Drude:
    """Load a material/source record from the current ``drude.yml`` database."""
    record = _model_record(name, 'drude.yml', db)
    try:
      parameters = {
        key: jp.asarray(record[key], dtype=jp.float32)
        for key in ('eps_inf', 'omega_p', 'gamma')
      }
    except (KeyError, TypeError, ValueError) as error:
      raise ValueError(f'invalid Drude parameters for {name!r}') from error
    return cls(**parameters, **_metadata(record))

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
    """List materials or Lorentz data sources in the selected model database."""
    return _available_model_entries('lorentz.yml', name, db)

  @classmethod
  def from_db(
      cls, name: str, db: str | os.PathLike[str] | None = None
  ) -> Lorentz:
    """Load a material/source record from the current ``lorentz.yml`` database."""
    record = _model_record(name, 'lorentz.yml', db)
    try:
      parameters = {
        'eps_inf': jp.asarray(record['eps_inf'], dtype=jp.float32),
        'omega_p': jp.asarray(record['omega_p'], dtype=jp.float32),
        'gamma': jp.asarray(record['gamma'], dtype=jp.float32),
        'omega_0': jp.asarray(record['omega'], dtype=jp.float32),
        'f': jp.asarray(record['f'], dtype=jp.float32),
      }
    except (KeyError, TypeError, ValueError) as error:
      raise ValueError(f'invalid Lorentz parameters for {name!r}') from error
    return cls(**parameters, **_metadata(record))

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
    """List materials or Sellmeier data sources from ``sellmeier.yml``."""
    return _available_model_entries(
      'sellmeier.yml', name, db, missing_ok=True
    )

  @classmethod
  def from_db(cls, name:str, db:str|None=None):
    ...

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


__all__ = ['Drude', 'Lorentz', 'Sellmeier']
