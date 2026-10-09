# jaX ElectroMagnetic Materials (XEMM)

`xemm` provides tabulated and model-based optical material properties as JAX
arrays. Tabulated refractive-index or relative-permittivity data are loaded from
YAML files, converted between common spectral coordinates, and interpolated
for JAX-compatible calculations. Dispersion models provide differentiable
material responses.

## Features

- A bundled database of tabulated optical properties for metals,
	semiconductors, dielectrics, and other materials
- Linear and not-a-knot cubic interpolation implemented with `jax.numpy`
- Conversion between wavelength, frequency, wavenumber, and photon energy
- Conversion between complex refractive index and relative permittivity
- Support for custom material databases using a small YAML schema
- JAX-compatible Drude, Lorentz, and Sellmeier material models

## Installation

`xemm` can be installed using `pip`.

```bash
cd /path/to/xemm
python -m pip install .
```

```bash
python -m pip install git+https://github.com/j-mun/xemm.git
```

## Quick start

Load the Johnson and Christy data for silver and evaluate its complex
refractive index at several wavelengths:

```python
import jax.numpy as jnp

from xemm import MaterialData

silver = MaterialData.from_db(
	"Ag/Johnson",
	unit="nm",
	parm="n",
	verbose=False,
)

wavelength_nm = jnp.array([450.0, 550.0, 650.0])
refractive_index = silver.interp(
	wavelength_nm,
	unit="nm",
	parm="n",
	kind="cubic",
)

print(refractive_index)
```

`MaterialData.from_db()` accepts a path relative to the bundled tabulated
database (`xemm-db/tabulated`).
The `.yml` or `.yaml` extension is optional. The returned object exposes the
sorted sample coordinates as `f`, the real and imaginary samples as `re` and
`im`, and the original description as `name`. Its `complex` property returns
`re + 1j * im`.

## Spectral coordinates

The `unit` argument controls the coordinate represented by `f`:

| Unit | Coordinate |
| --- | --- |
| `m`, `nm`, `um` | Vacuum wavelength |
| `Hz`, `GHz`, `THz` | Frequency |
| `cm-1` | Wavenumber |
| `eV` | Photon energy |

Unit names are case-sensitive. Data are sorted after conversion, so a source
tabulated by wavelength can be queried naturally after conversion to frequency
or energy.

## Optical parameters

Use `parm="n"` (or `"nk"`) for complex refractive index
$\tilde{n} = n + ik$, and use `parm="e"` (or `"eps"`) for complex relative
permittivity $\epsilon_r$. XEMM converts between them using

$$
\epsilon_r = \tilde{n}^2.
$$

The representation can be selected both when loading and when interpolating:

```python
silver = MaterialData.from_db("Ag/Johnson", unit="eV", parm="eps")
epsilon = silver.interp(2.0, unit="eV", parm="eps")
```

## Interpolation

`MaterialData.interp()` supports `kind="linear"` and `kind="cubic"`. Cubic
interpolation requires at least four source samples. By default, queries beyond
the tabulated interval are clipped to its endpoints. Pass `extrap=True` to
continue the first or last interpolation segment beyond the data interval.

Interpolation is expressed with JAX operations and can participate in JAX
transformations:

```python
import jax

silver = MaterialData.from_db("Ag/Johnson", verbose=False)

@jax.jit
def epsilon_at(wavelength_m):
	return silver.interp(wavelength_m, unit="m", parm="eps")
```

## Custom material data

Pass `db` to load from another database root:

```python
material = MaterialData.from_db(
	"Si/custom-model",
	db="/path/to/material-database/tabulated",
	unit="um",
	parm="n",
)
```

The corresponding file may be
`/path/to/material-database/tabulated/Si/custom-model.yml` and must use this
structure:

```yaml
NAME: Silicon, custom model
REFERENCES: Source or publication
COMMENTS: Optional notes
DATA:
	- type: tabulated
		parm: n
		unit: um
		data: |
			0.40  5.57  0.39
			0.50  4.30  0.07
			0.60  3.94  0.02
			0.70  3.77  0.01
```

Each data row contains the spectral coordinate, real part, and imaginary part.
The first entry in `DATA` is loaded. Its `parm` may be `n`, `nk`, `e`, or
`eps`, and its `unit` must be one of the supported spectral units above.

## Material models

Model parameters and database values currently use photon-energy units of eV.
The frequency argument to `eps()` and `n()` can use any spectral coordinate
supported by `MaterialData`:

```python
from xemm import Drude

silver = Drude.from_db("Ag/Ordal")
epsilon = silver.eps(2.0, unit="eV")
index = silver.n(550.0, unit="nm")
```

`Drude.from_db()` and `Lorentz.from_db()` read the current provisional model
records from `xemm-db/drude.yml` and `xemm-db/lorentz.yml`; this database layout
is subject to change. Pass `db` to use another model-database directory.
Models can also be created directly with `from_params()`. `Sellmeier` accepts
dimensionless `B` coefficients and `C` coefficients in the square of its
selected wavelength unit (default `um`).

Use `MaterialData.avail()` to list tabulated materials and
`MaterialData.avail("Ag")` to list that material's tabulated sources.
`Drude.avail()` and `Lorentz.avail()` list materials in their respective model
databases; passing a material name lists the available sources. For example,
`Drude.avail("Ag")` returns source labels that can be used with
`Drude.from_db("Ag/<source>")`. Pass `db` to list entries from a custom
database; for tabulated data it points to the tabulated database directory,
while for model data it points to the directory containing the model YAML
files.

## Measurement retrieval

For a homogeneous slab at normal incidence, retrieve effective relative
refractive index, impedance, permittivity, and permeability from measured
S-parameters:

```python
from xemm import retrieve_sparameters

result = retrieve_sparameters(
	s11, s21, thickness=1e-3, frequency=frequency_hz, unit="Hz",
	s22=s22, s12=s12,
)
index = result.n
```

The result uses a selectable phase branch and can unwrap phase over the last
frequency axis. Branch selection is ambiguous, so choose `branch` using sample
thickness and prior knowledge; retrieval assumes calibrated reference planes
at the slab faces.

For a bare, isotropic, semi-infinite interface, `ellipsometry_rho(psi, delta)`
converts ellipsometric angles to the complex reflection ratio, and
`ellipsometry_index(psi, delta, incidence_angle)` returns the pseudo-index.
This pointwise inversion does not apply to layered samples; those require a
layered forward model and parameter fit.

## Physical constants

Common electromagnetic and atomic constants are available from `xemm.const`:

```python
from xemm.const import c, eps0, hbar, mu0
```

Values are in SI units unless indicated by the constant's documentation.

## Development

Run the test suite from the repository root:

```bash
pytest
```

`xemm` is distributed under the MIT License.
