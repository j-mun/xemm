"""


"""

from __future__ import annotations
__all__ = [
  'MaterialData',
]

from functools import cache
import yaml
import numpy as np
import jax.numpy as jp
from . import interp
from .paths import (
  available_tabulated_materials,
  available_tabulated_models,
  resolve_tabulated_file,
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
    file:str
  ):
  """load raw material property data from a file
  
  Args:
    file: file name

  Returns:
    f: frequency
    re: real part of material property
    im: imaginary part of material property
    unit: frequency units
    parm: material property {'n' or 'e'}
    name: material name
  """
  with open(file, 'r') as f:
    raw = yaml.safe_load(f)
    data = raw['DATA'][0]
    unit = data["unit"]
    parm = data["parm"]
    dat = np.fromstring(data['data'].replace(',',' '), dtype=np.float32, sep=' ').reshape(-1,3)
    f = dat[:,0]
    re = dat[:,1]
    im = dat[:,2]
    name = raw["NAME"]
  return f, re, im, unit, parm, name


#--- interface
class MaterialData(xser.SpecNode):
  '''
  import material property data (static)


  Attributes:

  
  '''
  _data = ()
  _meta = ('f', 're', 'im', 'unit', 'parm', 'name')

  f: Array  # (static) frequency array
  re: Array # (static) real part of material property
  im: Array # (static) imaginary part of material property
  unit: str # frequency unit
  parm: str # material property {'n' or 'e'}
  name: str # material name

  @classmethod
  def avail(cls, name: str | None = None, db: str | None = None) -> list[str]:
    """List materials, or tabulated sources for ``name``."""
    if name is None:
      return available_tabulated_materials(db)
    return available_tabulated_models(name, db)

  @classmethod
  def from_db(cls, file:str, db:str|None=None, 
      unit:str|None=None, parm:str|None=None, verbose:bool=True):
    '''
    Returns:
      MaterialData instance

    Args:
      file: material data file name
      db: database root, if None, use the vendored tabulated database
      unit: frequency unit, if None, use the unit in the file
      parm: material property, if None, use the property in the file
      verbose: whether to print the material name
    '''
    filename = resolve_tabulated_file(file, db)
    f, re, im, raw_unit, raw_parm, name = _load_material_data(filename)
    unit = raw_unit if unit is None else unit
    parm = raw_parm if parm is None else parm

    f = _convert_unit(f, raw_unit, unit)
    re, im = _convert_parm(re, im, raw_parm, parm)
    order = jp.argsort(f)
    material = cls(f=f[order], re=re[order], im=im[order], unit=unit, parm=parm, name=name)
    if verbose:
      print(f'  importing... {name}')
    return material

  @property
  def complex(c):
    return c.re + 1j*c.im

  def interp(c, f: Array, unit:str='m', parm:str='n', 
      kind:str='linear', extrap:bool=False
    ) -> Array:
    '''
    Interpolate material property data to the given frequency array.

    
    differentiable interpolation


    Args:
      f: frequency array
      unit: frequency units
      parm: material property ('n' for refractive index, 'e' for permittivity)
      kind: interpolation kind ('linear', 'cubic', etc.)
      extrap: whether to allow extrapolation beyond the given frequency range

    Returns:
      interpolated complex material property array
    '''

    f = _convert_unit(f, unit, c.unit)
    interpolators = {'linear': interp.linear, 'cubic': interp.cubic}
    try:
      interpolate = interpolators[kind]
    except KeyError as error:
      raise ValueError(f'unsupported interpolation kind: {kind!r}') from error

    real = interpolate(f, c.f, c.re, extrap=extrap)
    imaginary = interpolate(f, c.f, c.im, extrap=extrap)
    real, imaginary = _convert_parm(real, imaginary, c.parm, parm)
    return real + 1j * imaginary

  def eps(c, f: Array, unit:str='m', kind:str='linear', extrap:bool=False) -> Array:
    return c.interp(f, unit=unit, parm='e', kind=kind, extrap=extrap)

  def n(c, f: Array, unit:str='m', kind:str='linear', extrap:bool=False) -> Array:
    return c.interp(f, unit=unit, parm='n', kind=kind, extrap=extrap)