# XMDM Plan



## Installation

```bash
cd /path/to/xmdm
pip install .
```


## Quick Start


Load the Johnson and Christy data for silver and evaluate its complex
refractive index at several wavelengths:

```python
import jax.numpy as jnp

from xmdm import Material

Ag = Material.from_db("Ag/Johnson", unit="nm", kind="n", verbose=False)

wavelength_nm = jnp.array([450.0, 550.0, 650.0])
n = Ag.interp(
	wavelength_nm,
	unit="nm",
	kind="n",
	interp="cubic",
  extrap=False
)

print(n)
```



Refer custom-db
```python
mat = Material.from_db(
	"<material>/<tag>",
	db="/path/to/custom-db",
)
```



fitting for other uses (e.g., FDTD)
- passivity, ...






