# Effective index from S-parameters

`retrieve_sparameters()` converts complex scattering parameters for a
homogeneous slab into effective refractive index, impedance, permittivity, and
permeability. It implements a normal-incidence, one-dimensional transfer
matrix inversion. It does not retrieve a unique material response without
choices about phase branch, reference planes, and sample geometry.

## Inputs and assumptions

The function accepts `s11` and `s21`, slab `thickness`, and a spectral
coordinate named `frequency`:

```python
from xmdm import retrieve_sparameters

result = retrieve_sparameters(
  s11=s11,
  s21=s21,
  thickness=0.005,       # metres
  frequency=10.0,        # GHz
  unit="GHz",
  unwrap=False,
)
n_eff = result.n
z_eff = result.z
eps_eff = result.eps
mu_eff = result.mu
```

The `frequency` parameter name reflects the common use of frequency-domain
S-data, but its coordinate accepts all XMDM spectral units:
`m`, `nm`, `um`, `Hz`, `GHz`, `THz`, `cm-1`, or `eV`. Wavelength inputs are
converted to vacuum wavelength. Thickness is always in metres. Arrays for S
parameters are broadcast together; for a frequency sweep, the last axis is
the phase-unwrapping axis.

By default, the slab is treated as symmetric: `s22=s11` and `s12=s21`.
Supply `s22` for asymmetric reflection and `s12` for non-reciprocal
transmission data. The inversion assumes homogeneous effective properties,
normal incidence, and a consistent calibration/reference-plane convention.

## Transfer-matrix inversion

Let $r_1=S_{11}$, $t_{21}=S_{21}$, $r_2=S_{22}$, and $t_{12}=S_{12}$.
The implementation forms:

$$
  A=\frac{(1+r_1)(1-r_2)+t_{12}t_{21}}{2t_{21}},\qquad
  B=\frac{(1+r_1)(1+r_2)-t_{12}t_{21}}{2t_{21}},
$$
$$
  C=\frac{(1-r_1)(1-r_2)-t_{12}t_{21}}{2t_{21}},\qquad
  D=\frac{(1-r_1)(1+r_2)+t_{12}t_{21}}{2t_{21}}.
$$

The slab phase is obtained from the transfer-matrix trace:

$$
\delta=\cos^{-1}\left(\frac{A+D}{2}\right).
$$

The implementation selects the sign with non-negative imaginary part,
optionally unwraps the real phase along the last axis, and adds the integer
branch offset:

$$
\delta_{\text{selected}}=\delta+2\pi m,
\qquad m=\texttt{branch}.
$$

With vacuum wavenumber $k_0=2\pi/\lambda_0$ and thickness $d$, the
effective parameters returned by the function are:

$$
n_{\mathrm{eff}}=\frac{\delta_{\mathrm{selected}}}{k_0d},
\qquad
z_{\mathrm{eff}}=\sqrt{\frac{B}{C}},
$$
$$
\varepsilon_{\mathrm{eff}}=\frac{n_{\mathrm{eff}}}{z_{\mathrm{eff}}},
\qquad
\mu_{\mathrm{eff}}=n_{\mathrm{eff}}z_{\mathrm{eff}}.
$$

The impedance square-root sign is selected so that its real part is
non-negative. These definitions use relative effective $\varepsilon$ and
$\mu$ and impedance normalized to vacuum.

## Branch choice and limitations

The inverse cosine is multivalued: adding $2\pi m$ changes the retrieved
index by an integer multiple of $\lambda_0/d$. `branch` selects this
integer. `unwrap=True` (the default) unwraps only the real phase along the
last array axis; it is not a physical branch solver and cannot establish the
globally correct branch from a single frequency sample. Select and document
the branch using continuity, passivity, thickness, and independent physical
knowledge appropriate to the experiment.

The calculation divides by $S_{21}$ and by $C$, and can be ill-conditioned
near transmission zeros or singular transfer-matrix values. The inverse
cosine and square root also have branch cuts. Check the returned values for
finite, physically plausible results; this function does not perform
uncertainty analysis, reference-plane correction, or multilayer fitting.

`SParameterResult` is a named tuple with fields `n`, `z`, `eps`, and `mu`.
The numerical implementation uses JAX arrays and is compatible with JAX
transformations for well-conditioned inputs.