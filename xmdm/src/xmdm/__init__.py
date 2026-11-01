"""JAX-compatible material data and optical dispersion models."""

__version__ = '2026.1.0'
__author__ = 'Jungho Mun'
__email__ = 'mjh92@postech.ac.kr'
__schema_version__ = '1'

from ._src import (
  Cauchy,
  Drude,
  Lorentz,
  Material,
  RefractiveIndexFormula,
  Sellmeier,
)
from .db import (
  available_materials,
  available_model_materials,
  available_records,
  database_directory,
  load_index,
  load_record,
)
from .retrieval import (
  SParameterResult,
  ellipsometry_index,
  ellipsometry_rho,
  retrieve_sparameters,
)
from .db.validation import validate_record_data

__all__ = [
  'Material',
  'Cauchy',
  'Drude',
  'Lorentz',
  'RefractiveIndexFormula',
  'Sellmeier',
  'SParameterResult',
  'available_materials',
  'available_model_materials',
  'available_records',
  'database_directory',
  'ellipsometry_index',
  'ellipsometry_rho',
  'load_index',
  'load_record',
  'retrieve_sparameters',
  'validate_record_data',
]