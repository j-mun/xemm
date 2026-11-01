# Ellipsometry and pointwise index retrieval

Ellipsometry measures the complex ratio between p- and s-polarized reflection
coefficients. XMDM provides `ellipsometry_rho()` to construct this ratio from
measured $\Psi,\Delta$, and `ellipsometry_index()` for the pointwise
inversion of one bare interface.

## Ellipsometric ratio

Using the convention

$$
\rho=\frac{r_p}{r_s}=\tan(\Psi)e^{i\Delta},
$$

the measured angles are $\Psi=\arctan|\rho|$ and
$\Delta=\arg(\rho)$. The default input angle unit is degrees; pass
`angle_unit="rad"` if \(\Psi\), \(\Delta\), and the incidence angle are all in
radians.

```python
from xmdm import ellipsometry_rho

rho = ellipsometry_rho(psi, delta)  # angles in degrees by default
```

The function converts the input angles to radians before evaluating the
expression, and works pointwise with broadcast-compatible JAX arrays.

## Bare-interface inversion

For an isotropic, semi-infinite sample with a known real ambient refractive
index $n_0$, incidence angle $\theta$, and no intervening films, define

$$
q=\frac{1-\rho}{1+\rho}.
$$

The pseudo-dielectric function is

$$
\varepsilon_{\mathrm{pseudo}}=
n_0^2\sin^2\theta\left(1+\tan^2\theta\,q^2\right),
\qquad
N_{\mathrm{pseudo}}=\sqrt{\varepsilon_{\mathrm{pseudo}}}.
$$

The implementation chooses the sign of the square root so that
$|\operatorname{Im}(N_{\mathrm{pseudo}})\geq0$. The incident medium is air
by default (`ambient_index=1.0`).

```python
from xmdm import ellipsometry_index

index = ellipsometry_index(
  psi=psi,
  delta=delta,
  incidence_angle=70.0,
  ambient_index=1.0,
  angle_unit="deg",
)
```

The result is a complex pseudo-index at each measured point. Its spectral
coordinate is not supplied to this function: pass the measured angle arrays
and incidence angle, then associate the result with the instrument's
wavelength or frequency axis.

## Scope and cautions

This closed-form inversion is not a general ellipsometry solver. It assumes
one bare interface, an isotropic homogeneous semi-infinite sample, and a
known real ambient index. It does not model thin-film stacks, substrates,
surface roughness, anisotropy, depolarization, or finite-thickness effects.
For those systems, fit a suitable optical stack model to $\Psi,\Delta$
rather than interpreting the pointwise pseudo-index as an intrinsic bulk
index.

The inversion is ill-conditioned near $\rho=-1$, where $1+\rho$ is zero,
and the square root has a branch choice. Validate the output and compare the
assumptions with the measurement geometry. This API computes values; it does
not fit parameters or estimate uncertainty.