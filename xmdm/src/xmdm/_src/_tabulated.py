"""


"""

from __future__ import annotations
__all__ = [
  'Material',
]

from functools import cache
import os
import numpy as np
import jax.numpy as jp
from . import _interp
from ..db.database import (
  available_model_materials,
  available_records,
  load_record,
  tabulated_arrays,
)
import xser

Array = jp.ndarray | np.ndarray

_C = 299792458.0
_HBAR_EV = 6.582119569e-16


def _convert_unit(f: Array, source: str, target: str) -> Array:
  """Convert wavelength, frequency, wavenumber, or photon-energy coordinates."""
  f = jp.asarray(f)
  aliases = {'m': 'm', 'nm': 'nm', 'um': 'um', 'Hz': 'Hz', 'GHz': 'GHz',
             'THz': 'THz', 'cm-1': 'cm-1', 'eV': 'eV'}
  if source not in aliases or target not in aliases:
    raise ValueError(f'unsupported frequency unit conversion: {source!r} -> {target!r}')
  if source == target:
    return f

  to_meters = {
    'm': lambda value: value,
    'nm': lambda value: value * 1e-9,
    'um': lambda value: value * 1e-6,
    'Hz': lambda value: _C / value,
    'GHz': lambda value: 1e-9 * _C / value,
    'THz': lambda value: 1e-12 * _C / value,
    'cm-1': lambda value: 100.0 / value,
    'eV': lambda value: 2 * jp.pi * _C * _HBAR_EV / value,
  }
  from_meters = {
    'm': lambda value: value,
    'nm': lambda value: value * 1e9,
    'um': lambda value: value * 1e6,
    'Hz': lambda value: _C / value,
    'GHz': lambda value: 1e-9 * _C / value,
    'THz': lambda value: 1e-12 * _C / value,
    'cm-1': lambda value: 100.0 / value,
    'eV': lambda value: 2 * jp.pi * _C * _HBAR_EV / value,
  }
  return from_meters[target](to_meters[source](f))


def _convert_parm(re: Array, im: Array, source: str, target: str) -> tuple[Array, Array]:
  """Convert refractive index ``n``/``nk`` and permittivity ``e``/``eps``."""
  aliases = {'n': 'n', 'nk': 'n', 'e': 'e', 'eps': 'e'}
  if source not in aliases or target not in aliases:
    raise ValueError(f'unsupported material parameter conversion: {source!r} -> {target!r}')
  source = aliases[source]
  target = aliases[target]
  re = jp.asarray(re)
  im = jp.asarray(im)
  if source == target:
    return re, im
  if source == 'n':
    return re ** 2 - im ** 2, 2 * re * im
  value = jp.sqrt(re + 1j * im)
  return jp.real(value), jp.imag(value)

@cache
def _load_material_data(
    file: str,
    db: str | None,
  ):
  """Load and validate tabulated data from its JSON database record."""
  record, material_name = load_record(file, 'tabulated', db)
  f, real, imaginary, unit, kind = tabulated_arrays(record)
  return (
    np.asarray(f, dtype=np.float32),
    np.asarray(real, dtype=np.float32),
    np.asarray(imaginary, dtype=np.float32),
    unit,
    kind,
    material_name,
  )


#--- interface
class Material(xser.SpecNode):
  '''
  tabulated electromagnetic material property data

  Attributes:
    name(str): material name
    unit(str): frequency unit
    kind(str): material property {'n' or 'e'}
    f(Array): frequency array
    re(Array): real part of material property
    im(Array): imaginary part of material property
  '''
  _data = ()
  _meta = ('f', 're', 'im', 'unit', 'kind', 'name')

  f: Array  # (static) frequency array
  re: Array # (static) real part of material property
  im: Array # (static) imaginary part of material property
  unit: str # frequency unit
  kind: str # material property {'n' or 'e'}
  name: str # material name

  @classmethod
  def avail(
      cls,
      name: str | None = None,
      db: str | os.PathLike[str] | None = None,
  ) -> list[str]:
    """List materials, or tabulated sources for ``name``."""
    if name is None:
      return available_model_materials('tabulated', db)
    return available_records(name, 'tabulated', db)

  @classmethod
  def from_db(
      cls,
      file: str,
      db: str | os.PathLike[str] | None = None,
      unit: str | None = None,
      kind: str | None = None,
      verbose: bool = True,
  ) -> Material:
    '''
    Returns:
      Material instance

    Args:
      file: material record name in ``material/name`` form
      db: database root, if None, use the bundled JSON database
      unit: frequency unit, if None, use the unit in the file
      kind: material property, if None, use the property in the file
      verbose: whether to print the material name
    '''
    db_path = None if db is None else os.fspath(db)
    f, re, im, raw_unit, raw_kind, name = _load_material_data(file, db_path)
    unit = raw_unit if unit is None else unit
    kind = raw_kind if kind is None else kind

    f = _convert_unit(f, raw_unit, unit)
    if kind == 'k':
      if raw_kind in ('n', 'nk'):
        re, im = im, jp.zeros_like(im)
      elif raw_kind != 'k':
        raise ValueError(
          f'cannot convert material parameter {raw_kind!r} to {kind!r}'
        )
    elif kind == 'n2':
      if raw_kind != 'n2':
        raise ValueError(
          f'cannot convert material parameter {raw_kind!r} to {kind!r}'
        )
      im = jp.zeros_like(im)
    else:
      re, im = _convert_parm(re, im, raw_kind, kind)
    order = jp.argsort(f)
    material = cls(f=f[order], re=re[order], im=im[order], unit=unit, kind=kind, name=name)
    if verbose:
      print(f'  importing... {name}')
    return material

  @property
  def complex(c):
    return c.re + 1j*c.im

  def interp(c, f: Array, unit:str='m', kind:str='n', 
      interp:str='linear', extrap:bool=False
    ) -> Array:
    '''
    Interpolate material property data to the given frequency array.

    
    differentiable interpolation


    Args:
      f: frequency array
      unit: frequency units
      kind: material property ('n' for refractive index, 'e' for permittivity)
      interp: interpolation kind ('linear', 'cubic', etc.)
      extrap: whether to allow extrapolation beyond the given frequency range

    Returns:
      interpolated complex material property array
    '''

    f = _convert_unit(f, unit, c.unit)
    interpolators = {'linear': _interp.linear, 'cubic': _interp.cubic}
    try:
      interpolate = interpolators[interp]
    except KeyError as error:
      raise ValueError(f'unsupported interpolation kind: {interp!r}') from error

    if kind == 'k':
      if c.kind in ('n', 'nk'):
        real = interpolate(f, c.f, c.im, extrap=extrap)
      elif c.kind == 'k':
        real = interpolate(f, c.f, c.re, extrap=extrap)
      else:
        raise ValueError(f'cannot convert material parameter {c.kind!r} to {kind!r}')
      imaginary = jp.zeros_like(real)
    elif kind == 'n2':
      if c.kind != 'n2':
        raise ValueError(f'cannot convert material parameter {c.kind!r} to {kind!r}')
      real = interpolate(f, c.f, c.re, extrap=extrap)
      imaginary = jp.zeros_like(real)
    else:
      real = interpolate(f, c.f, c.re, extrap=extrap)
      imaginary = interpolate(f, c.f, c.im, extrap=extrap)
      real, imaginary = _convert_parm(real, imaginary, c.kind, kind)
    return real + 1j * imaginary

  def eps(c, f: Array, unit:str='m', interp:str='linear', extrap:bool=False) -> Array:
    return c.interp(f, unit=unit, kind='e', interp=interp, extrap=extrap)

  def n(c, f: Array, unit:str='m', interp:str='linear', extrap:bool=False) -> Array:
    return c.interp(f, unit=unit, kind='n', interp=interp, extrap=extrap)

  def k(c, f: Array, unit:str='m', interp:str='linear', extrap:bool=False) -> Array:
    return jp.real(c.interp(f, unit=unit, kind='k', interp=interp, extrap=extrap))

  def n2(c, f: Array, unit:str='m', interp:str='linear', extrap:bool=False) -> Array:
    return jp.real(c.interp(f, unit=unit, kind='n2', interp=interp, extrap=extrap))

__all__ = ['Material']