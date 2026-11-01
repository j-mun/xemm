"""Model payload validation without allocating numerical device arrays."""

from __future__ import annotations

import math
from typing import Any

from .database import tabulated_arrays


def numeric_parameter(value: Any, name: str, *, array: bool = False) -> Any:
  if array and (not isinstance(value, list) or not value):
    raise ValueError(f'{name} must be a non-empty numeric array')
  values = value if array else [value]
  if any(
    isinstance(item, bool)
    or not isinstance(item, (int, float))
    or not math.isfinite(item)
    for item in values
  ):
    raise ValueError(f'{name} must contain finite numeric values')
  return value


def validate_record_data(record: dict[str, Any]) -> None:
  model = record['model']
  data = record['data']
  if model == 'tabulated':
    tabulated_arrays(record)
    return
  scalars = {
    'drude': ('eps_inf', 'omega_p', 'gamma'),
    'lorentz': ('eps_inf', 'omega_p'),
    'sellmeier': (),
    'cauchy': ('A', 'B', 'C'),
    'rii_formula': (),
  }
  arrays = {
    'lorentz': ('f', 'gamma', 'omega_0'),
    'sellmeier': ('B', 'C'),
    'rii_formula': ('coefficients',),
  }
  if model == 'rii_formula':
    formula = data.get('formula')
    if isinstance(formula, bool) or not isinstance(formula, int) or not 1 <= formula <= 9:
      raise ValueError('RefractiveIndex.INFO formula must be an integer from 1 to 9')
    wavelength_range = data.get('wavelength_range')
    if wavelength_range is not None:
      if (
        not isinstance(wavelength_range, list)
        or len(wavelength_range) != 2
        or any(
          isinstance(value, bool)
          or not isinstance(value, (int, float))
          or not math.isfinite(value)
          for value in wavelength_range
        )
        or wavelength_range[0] <= 0
        or wavelength_range[1] <= wavelength_range[0]
      ):
        raise ValueError('wavelength_range must be two increasing positive values')
    if data.get('unit', 'um') not in ('m', 'nm', 'um'):
      raise ValueError('unsupported RefractiveIndex.INFO formula wavelength unit')
  if model not in scalars:
    raise ValueError(f'unsupported model: {model!r}')
  for field in scalars[model]:
    numeric_parameter(data.get(field), field)
  fields = arrays.get(model, ())
  for field in fields:
    numeric_parameter(data.get(field), field, array=True)
  if fields and len({len(data[field]) for field in fields}) != 1:
    raise ValueError(f'{model} coefficient array lengths differ')
  if model in ('sellmeier', 'cauchy') and data.get('unit', 'um') not in (
    'm', 'nm', 'um',
  ):
    raise ValueError(f'unsupported {model} wavelength unit')
