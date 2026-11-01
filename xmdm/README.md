# XMDM

`xmdm` provides JAX-compatible optical material data, dispersion models, and a
bundled database of tabulated material properties. The HTTP, MCP, and command
line interfaces are being developed separately in `xmdm-server`.

## Installation

Install the package and its bundled material database with pip:

```bash
cd /path/to/xmdm
python -m pip install .
```

For development, install the test dependencies with
`python -m pip install '.[dev]'`.

## Quick start

Load Johnson and Christy silver data and interpolate its refractive index:

```python
import jax.numpy as jnp

from xmdm import Material

silver = Material.from_db("Ag/Johnson", unit="nm", kind="n", verbose=False)
wavelength_nm = jnp.array([450.0, 550.0, 650.0])
index = silver.interp(
    wavelength_nm,
    unit="nm",
    kind="n",
    interp="cubic",
)
```

`Material.from_db()` accepts a `material/record` selector. Its `unit` and
`kind` arguments optionally convert the source data while loading.

## Coordinates and parameters

Supported spectral coordinates are wavelength (`m`, `nm`, `um`), frequency
(`Hz`, `GHz`, `THz`), wavenumber (`cm-1`), and photon energy (`eV`). Unit names
are case-sensitive. `kind="n"` (also `"nk"`) selects complex refractive index;
`kind="e"` (also `"eps"`) selects complex relative permittivity. For tabulated
records, `kind="k"` selects the extinction coefficient and `kind="n2"` selects
the nonlinear refractive-index coefficient; these properties are not
interconverted with `n` or `e`.

Interpolation supports `interp="linear"` and `interp="cubic"`. Out-of-range
coordinates are clipped to the data endpoints by default; pass `extrap=True`
to extrapolate. The interpolation operations use JAX and support
transformations such as `jax.jit` and `jax.grad`.

## Dispersion models

The package exports `Drude`, `Lorentz`, `Sellmeier`, `Cauchy`, and
`RefractiveIndexFormula` models.
Each model can be built from parameters or loaded from the bundled database:

```python
from xmdm import Drude

silver_model = Drude.from_db("Ag/Ordal")
epsilon = silver_model.eps(2.0, unit="eV")
```

`RefractiveIndexFormula` evaluates analytic formulae 1–9 used by
RefractiveIndex.INFO, preserving the original coefficient order and optional
wavelength range. Its wavelength units default to micrometres.

See the [optical model guide](docs/optics_models.md) for equations and
parameter conventions.

## Custom databases

Pass `db` to load a material-first JSON database from another directory:

```python
silicon = Material.from_db(
    "Si/custom-record",
    db="/path/to/material-database",
    unit="um",
)
```

A tiny synthetic database with tabulated and Cauchy records is available in
[tests/custom-db](tests/custom-db). It is exercised by
[test_custom_db.py](tests/test_custom_db.py), including material/source
availability, alias lookup, interpolation, unit conversion, and missing-record
errors.

Record files and catalog record references use `"physics": "optics"` for
linear optical data and `"physics": "nlo"` for tabulated nonlinear `n2`
coefficients. This metadata leaves room for future thermal or other material
properties. The bundled RefractiveIndex.INFO data is a static, one-time import,
not a continuously synchronized database.
See the [database schema](src/xmdm-db/README.md) for the JSON layout.
The [database guide](docs/database.md) explains the bundled catalog, lookup,
and provenance.

## Retrieval helpers

`ellipsometry_rho()`, `ellipsometry_index()`, and
`retrieve_sparameters()` provide JAX-compatible conversions and pointwise
retrieval of optical properties from measured data. See the guides for
[ellipsometry](docs/ellipsometry.md),
[S-parameter effective index](docs/effective_index.md), and the
[Kramers-Kronig relations](docs/kramers_kronig.md).
