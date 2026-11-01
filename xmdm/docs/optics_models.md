# Optical material models

XMDM represents optical material response either as measured tabulated data
(`Material`) or as an analytic dispersion model. The analytic classes expose
`eps(wavelength_or_frequency, unit=...)` and/or
`n(wavelength_or_frequency, unit=...)`; their coordinate argument is converted
to the units used by each model's parameters.

The accepted coordinate units are `m`, `nm`, `um`, `Hz`, `GHz`, `THz`,
`cm-1`, and `eV`. Unit strings are case-sensitive. Wavelength-parameter
models (`Sellmeier`, `Cauchy`, and `RefractiveIndexFormula`) accept only
`m`, `nm`, or `um` for their coefficient unit. `Drude` and `Lorentz` store
their energy parameters in eV. The input coordinate can use any supported
spectral unit and is converted internally.

## Tabulated data

`Material.from_db("material/record")` loads a tabulated record. `f` is the
record's independent spectral coordinate; `re` and `im` are its two stored
columns. `kind="n"` gives complex refractive index, `kind="e"` gives complex
relative permittivity, `kind="k"` selects the extinction coefficient, and
`kind="n2"` selects the tabulated nonlinear index coefficient:

```python
from xmdm import Material

gold = Material.from_db("Au/Johnson", unit="nm", kind="n", verbose=False)
wavelength_nm = [450.0, 550.0, 650.0]
n_complex = gold.interp(
  wavelength_nm, unit="nm", kind="n", interp="cubic",
)
k = gold.k(wavelength_nm, unit="nm")
```

`interp()` supports `interp="linear"` and `interp="cubic"`. Out-of-range
coordinates are clipped to the table endpoints by default; set `extrap=True`
to extrapolate. For a singleton table, the point is available only at its
stored coordinate. The interpolation functions use JAX arrays and support
JAX transformations such as `jit` and `grad`.

For complex refractive index $N=n+ik$, the stored `n`/`nk` convention is
`re = n` and `im = k`. The corresponding relative permittivity is
$\varepsilon=N^2=(n^2-k^2)+i\,2nk$. The `k` and `n2` property tables are
not interchangeable with $N$ or $\varepsilon$.

Nonlinear `n2` records and their catalog references use `physics="nlo"`,
distinct from the `physics="optics"` classification of linear optical data.
The `n2` label means the nonlinear coefficient $n_2$, not the square of the
linear refractive index.

## Drude model

`Drude` models a free-carrier contribution. Its energy variable and parameters
are in eV:

$$
\varepsilon(E)=\varepsilon_\infty-
\frac{E_p^2}{E^2+i\Gamma E},
\qquad
N(E)=\sqrt{\varepsilon(E)}.
$$

Here $E_p$ is the plasma energy and $\Gamma$ is the damping energy.
`Drude.from_params(eps_inf, omega_p, gamma)` creates a model;
`Drude.from_db("Ag/Ordal")` loads one. The returned square root is complex.

## Lorentz model

The implemented `Lorentz` model sums one or more damped oscillators:

$$
\varepsilon(E)=\varepsilon_\infty+
\sum_j \frac{f_j E_p^2}
{E_{0,j}^2-E^2-i\Gamma_j E},
\qquad
N(E)=\sqrt{\varepsilon(E)}.
$$

All energies are in eV. The scalar $E_p$ is shared by the oscillators;
$f_j$, $E_{0,j}$, and $\Gamma_j$ are one-dimensional arrays of matching
length. `Lorentz.from_params(eps_inf, omega_p, gamma, omega_0, f=1.0)` accepts
the parameters, with `f` defaulting to one. In this implementation, the
Lorentz formula is the oscillator sum shown above; it does not add a separate
Drude term.

## Sellmeier model

`Sellmeier` is a lossless wavelength dispersion model:

$$
n^2(\lambda)=1+\sum_j
\frac{B_j\lambda^2}{\lambda^2-C_j}.
$$

The wavelength is converted to the model's `unit` (default `um`). $B_j$ is
dimensionless and $C_j$ has units of the model wavelength squared. The
coefficient arrays `B` and `C` must be non-empty, one-dimensional, and the same
length. The implementation returns the complex square root of the modeled
$n^2$, which allows evaluation when the radicand is negative.

## Cauchy model

`Cauchy` models refractive index directly:

$$
n(\lambda)=A+\frac{B}{\lambda^2}+\frac{C}{\lambda^4}.
$$

The wavelength is converted to the coefficient unit (default `um`); $B$
and $C$ therefore carry units of wavelength squared and wavelength to the
fourth power, respectively. `eps()` returns $n^2$.

## RefractiveIndex.INFO formulas

`RefractiveIndexFormula` evaluates the analytic formula families numbered 1
through 9. `from_params(formula, coefficients, unit="um",
wavelength_range=None)` stores the ordered coefficient vector and optional
range. `from_db("material/record")` loads the same fields from the database.
The wavelength range is metadata on the model: direct calls to `n()` do not
clip or reject wavelengths outside it. The XMDM server's range-aware
evaluation endpoint applies its own configured range policy.

Let $c_0,c_1,\ldots$ denote the ordered coefficients and $\lambda$ the
wavelength in the coefficient unit. Formulae are evaluated as follows:

1. **Formula 1 (Sellmeier-type)**:
   $$
   n^2=1+c_0+\sum_{j=1,3,\ldots}
   \frac{c_j\lambda^2}{\lambda^2-c_{j+1}^2}.
   $$
2. **Formula 2 (Sellmeier-type)**:
   $$
   n^2=1+c_0+\sum_{j=1,3,\ldots}
   \frac{c_j\lambda^2}{\lambda^2-c_{j+1}}.
   $$
3. **Formula 3 (power series for $n^2$)**:
   $$
   n^2=c_0+\sum_{j=1,3,\ldots}c_j\lambda^{c_{j+1}}.
   $$
4. **Formula 4 (Sellmeier terms and power terms for $n^2$)**:
   $$
   n^2=c_0+
   \sum_{j\in\{1,5\}}
   \frac{c_j\lambda^{c_{j+1}}}
   {\lambda^2-c_{j+2}^{c_{j+3}}}
   +\sum_{j=9,11,\ldots}c_j\lambda^{c_{j+1}}.
   $$
   The first sum uses complete four-coefficient blocks after $c_0$;
   additional pairs beginning at $c_9$ are power terms.
5. **Formula 5 (power series for $n$)**:
   $$
   n=c_0+\sum_{j=1,3,\ldots}c_j\lambda^{c_{j+1}}.
   $$
6. **Formula 6 (inverse-wavelength terms for $n$)**:
   $$
   n=1+c_0+\sum_{j=1,3,\ldots}
   \frac{c_j}{c_{j+1}-\lambda^{-2}}.
   $$
7. **Formula 7 (Sellmeier-type expansion for $n$)**:
   $$
   n=c_0+\frac{c_1}{\lambda^2-0.028}
   +\frac{c_2}{(\lambda^2-0.028)^2}
   +\sum_{j=3}^{m} c_j\lambda^{2(j-2)}.
   $$
   The constant `0.028` is used as written in the formula's wavelength-unit
   convention; the bundled RefractiveIndex.INFO records use micrometres.
8. **Formula 8 (Lorentz-Lorenz form)**: define
   $$
   R=c_0+\frac{c_1\lambda^2}{\lambda^2-c_2}
   +c_3\lambda^2,
   \qquad
   n^2=\frac{1+2R}{1-R}.
   $$
9. **Formula 9 (resonance form)**:
   $$
   n^2=c_0+\frac{c_1}{\lambda^2-c_2}
   +\frac{c_3(\lambda-c_4)}
   {(\lambda-c_4)^2+c_5}.
   $$

For formulae that define $n^2$, XMDM takes the complex square root. The
formula number, coefficient vector, and wavelength unit must match the source
record; do not reorder or infer coefficients. Evaluation raises an error for
coefficient lists that are structurally incomplete. For example, formula 2
requires an odd coefficient count of at least three. In the bundled RII
snapshot, `AgGaSe2/Boyd-o` has a four-value list; its source values remain
unchanged and the model reports an incomplete formula-2 coefficient list.

## Numerical and physical considerations

The analytic expressions are phenomenological fits, not guarantees of valid
response at every wavelength. Prefer the fitted range from the source record.
Avoid evaluating at poles or singular denominators, and check model outputs
for finite values. The package uses JAX-compatible array operations; analytic
models can be differentiated and transformed where the selected expression
is defined.