"""
jaX ElectroMagnetic Materials (XEMM)
"""

__version__ = '2026.0.0'
__author__ = 'Jungho Mun'
__email__ = 'mjh92@postech.ac.kr'
from .tabulated import *
from .model import Drude, Lorentz, Sellmeier
from .retrieval import (
  ellipsometry_index,
  ellipsometry_rho,
  retrieve_sparameters,
)

__all__ = [
  'MaterialData',
  'Drude',
  'Lorentz',
  'Sellmeier',
  'ellipsometry_index',
  'ellipsometry_rho',
  'retrieve_sparameters',
]