# jaX ElectroMagnetic Materials (XEMM)

`xemm` provides tabulated optical material properties as JAX arrays. It loads
refractive-index or relative-permittivity data from YAML files, converts between
common spectral coordinates, and interpolates the complex material response in
JAX-compatible calculations.

## Features

- A bundled database of tabulated optical properties for metals,
	semiconductors, dielectrics, and other materials
- Linear and not-a-knot cubic interpolation implemented with `jax.numpy`
- Conversion between wavelength, frequency, wavenumber, and photon energy
- Conversion between complex refractive index and relative permittivity
- Support for custom material databases using a small YAML schema

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

silver = MaterialData.from_file(
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

`MaterialData.from_file()` accepts a path relative to the bundled database.
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
silver = MaterialData.from_file("Ag/Johnson", unit="eV", parm="eps")
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

silver = MaterialData.from_file("Ag/Johnson", verbose=False)

@jax.jit
def epsilon_at(wavelength_m):
	return silver.interp(wavelength_m, unit="m", parm="eps")
```

## Custom material data

Pass `db` to load from another database root:

```python
material = MaterialData.from_file(
	"Si/custom-model",
	db="/path/to/material-database",
	unit="um",
	parm="n",
)
```

The corresponding file may be
`/path/to/material-database/Si/custom-model.yml` and must use this structure:

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

