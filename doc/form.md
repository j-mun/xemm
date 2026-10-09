# Material formulations

XEMM aims to describe optical materials with both measured tables and
physics-based models, then use those descriptions to predict or retrieve
material properties from electromagnetic measurements.

## Current scope

`MaterialData` loads tabulated refractive index or relative permittivity and
provides JAX-compatible linear and cubic interpolation. The
`xemm.model` module also implements JAX-compatible Drude, Lorentz, and
Sellmeier dispersion models. The current Drude and Lorentz database loaders
use provisional YAML records under `xemm-db/`; that format may change.
`xemm.retrieval` implements effective-parameter retrieval for homogeneous
slabs from S-parameters and pseudo-index retrieval for bare, isotropic
interfaces from ellipsometric angles. Composite-medium calculations, layered
ellipsometry, and model fitting remain future functionality.

## Conventions

Use angular frequency $\omega = 2\pi c/\lambda$ and the time dependence
$e^{-i\omega t}$. The complex refractive index is
$\tilde{n}=n+ik$, and relative permittivity is
$\epsilon_r=\tilde{n}^{\,2}$. For a passive material, this convention gives
$\operatorname{Im}(\epsilon_r)\geq 0$.

Model parameters and spectral coordinates must use consistent units. In
particular, wavelength in empirical dispersion equations is typically given
in the unit used to fit their coefficients.

In the current API, Drude and Lorentz parameters are expressed as photon
energies in eV. Sellmeier `B` coefficients are dimensionless, and `C`
coefficients use the square of the wavelength unit selected when creating the
model.

## Physical admissibility

Material models and retrieved effective parameters should satisfy reality,
causality, passivity, and—where applicable—reciprocity. These conditions are
not merely optional physical interpretations: they constrain the allowed
complex response and provide useful diagnostics for measured data, fitted
models, and inverse-design results.

### Reality condition

A material response in the time domain is real: a real electric field produces
a real displacement field. For a linear, time-invariant medium, this implies
the reality condition

$$
\epsilon_r(-\omega)=\epsilon_r^*(\omega),
$$

or, equivalently,

$$
\operatorname{Re}\epsilon_r(-\omega)
=
\operatorname{Re}\epsilon_r(\omega),
\qquad
\operatorname{Im}\epsilon_r(-\omega)
=
-\operatorname{Im}\epsilon_r(\omega).
$$

Thus, for real frequencies, the real part of $\epsilon_r$ is even in
$\omega$, while the imaginary part is odd. The same reality condition applies
to $\mu_r$, conductivity, susceptibility, and other linear response
functions.

In practice, most optical material models are evaluated only for $\omega>0$.
Nevertheless, their mathematical form should be consistent with the
negative-frequency extension. A model that violates this condition may appear
useful over a narrow positive-frequency interval but cannot represent a real,
time-domain material response.

### Causality and Kramers-Kronig relations

Causality requires that a material cannot respond before an applied field
arrives. For a linear, causal, time-invariant medium, $\epsilon_r(\omega)$
is analytic in the upper half of the complex-$\omega$ plane, subject to the
usual high-frequency decay condition. This analyticity implies the
Kramers–Kronig relations between the real and imaginary parts of the
response. [37][45][46]

For a passive medium under the $e^{-i\omega t}$ convention,

$$
\epsilon_r(\omega)
=
\epsilon_r'(\omega)+i\epsilon_r''(\omega),
\qquad
\epsilon_r''(\omega)\ge0
\quad\text{for }\omega>0.
$$

The real and imaginary parts are then related by

$$
\epsilon_r'(\omega)
=
\epsilon_\infty
+
\frac{2}{\pi}
\mathcal P
\int_0^\infty
\frac{\Omega\epsilon_r''(\Omega)}
{\Omega^2-\omega^2}\,d\Omega,
$$

and, when the required subtraction or conductivity treatment is specified,

$$
\epsilon_r''(\omega)
=
-\frac{2\omega}{\pi}
\mathcal P
\int_0^\infty
\frac{\epsilon_r'(\Omega)-\epsilon_\infty}
{\Omega^2-\omega^2}\,d\Omega.
$$

Here $\mathcal P$ denotes the Cauchy principal value. The Kramers–Kronig
relations mean that dispersion and absorption are not independent: an
absorption feature must be accompanied by a causally consistent change in the
real part of the permittivity. [37][46][50]

For materials with free-carrier conduction, it is often preferable to apply
the Kramers–Kronig relations to $\omega[\epsilon_r(\omega)-\epsilon_\infty]$
or to the optical conductivity, rather than directly to $\epsilon_r$. The
appropriate formulation depends on whether the DC conductivity is included in
$\epsilon_r''$ or treated separately; this choice must be stated explicitly.

### Passivity

A passive material does not supply energy to the field. Under the
$e^{-i\omega t}$ convention, passivity requires

$$
\operatorname{Im}\epsilon_r(\omega)\ge0,
\qquad
\operatorname{Im}\mu_r(\omega)\ge0,
\qquad
\text{for }\omega>0.
$$

For an isotropic medium with complex refractive index
$\tilde n=n+ik$, this implies $k\ge0$, so a forward-propagating plane wave
decays rather than grows. The corresponding relative permittivity is

$$
\epsilon_r=\tilde n^2,
$$

and its imaginary part is nonnegative for a passive material.

Passivity should be checked after interpolation, mixing, fitting, and
parameter transformation. For example, an interpolated table can produce a
small negative $\operatorname{Im}\epsilon_r$ between measured points, and an
effective-medium rule can produce an unphysical result if its inputs or branch
choices are inconsistent.

### Reciprocity

A reciprocal medium has the same response when source and observer positions
are exchanged. In a source-free region with no time-reversal-breaking bias,
such as a static magnetic field or a nonlinear operating point, the material
tensors satisfy
$$
\epsilon_{ij}=\epsilon_{ji},\\
\mu_{ij}=\mu_{ji}.
$$
For a reciprocal two-port sample, the scattering matrix is symmetric:
$$
S_{12}=S_{21}.
$$
This does **not** imply $S_{11}=S_{22}$. A reciprocal slab can still be
geometrically or materially asymmetric, so its forward and backward reflection
coefficients may differ. Therefore, S-parameter retrieval should preserve the
distinction between reciprocity and symmetry:

- **Reciprocity:** $S_{21}=S_{12}$.
- **Mirror symmetry:** $\Gamma_+=\Gamma_-$, and consequently $S_{11}=S_{22}$.

Nonreciprocal materials, including magnetized media with nonzero cyclotron
frequency, can violate the usual reality condition in their circular
polarization basis. Such materials require an explicitly nonreciprocal
material formulation and should not be represented by a simple symmetric
scalar \(\epsilon_r\) or \(\mu_r\). [41][42]

### Validation checks

A material or retrieval workflow should provide diagnostics for:

-- **Reality:** $\epsilon_r(-\omega)=\epsilon_r^*(\omega)$.
- **Passivity:** $\operatorname{Im}\epsilon_r\ge0$ and $\operatorname{Im}\mu_r\ge0$ for $\omega>0$.
- **Causality:** Kramers–Kronig consistency over the available spectral band, with explicit treatment of finite bandwidth, DC conductivity, and high-frequency subtraction.
- **Reciprocity:** $S_{21}=S_{12}$ for reciprocal samples.
- **Symmetry:** $S_{11}=S_{22}$ only for mirror-symmetric samples.
- **Numerical robustness:** Continuous branch selection, phase unwrapping, and stable interpolation across the spectral grid.

These checks should be reported alongside fitted parameters. A good fit to
$(\Psi,\Delta)$ or $S$-parameters does not by itself establish that the
retrieved material is causal, passive, reciprocal, or physically unique.

## Material response models

Dispersive models return complex permittivity as a function of frequency (or
complex refractive index derived from it).

### Drude

Free carriers are represented by a plasma frequency $\omega_p$ and damping
$\gamma$:

$$
\epsilon_r(\omega)=\epsilon_\infty-
\frac{\omega_p^2}{\omega^2+i\gamma\omega}.
$$

This is a compact model for conductive materials over spectral ranges where
bound-electron resonances can be neglected.

### Lorentz and Lorentz-Drude

Bound-electron resonances are represented by damped oscillators:

$$
\epsilon_r(\omega)=\epsilon_\infty+
\sum_j \frac{f_j\omega_{p,j}^2}
{\omega_{0,j}^2-\omega^2-i\gamma_j\omega}.
$$

The Drude-Lorentz form includes a zero-resonance (free-carrier) contribution.
An extended Lorentz-Drude form may add oscillator types or constraints; its
parameterization should be specified before it becomes a public model.

### Cauchy and Sellmeier

These compact dispersion equations are useful primarily for transparent
materials. The Cauchy equation approximates refractive index directly:
$$
n(\lambda)=A+\frac{B}{\lambda^2}+\frac{C}{\lambda^4}+\cdots.
$$

The Sellmeier equation models squared refractive index with resonant terms:
$$
n^2(\lambda)=1+\sum_j\frac{B_j\lambda^2}{\lambda^2-C_j}.
$$

Neither equation by itself describes absorption reliably near an absorption
band.

### Brendel-Bormann

The Brendel-Bormann model describes broadened interband transitions by
convolving Lorentz oscillators with a Gaussian distribution of resonance
frequencies. It is a candidate model for metallic optical constants.

### Tauc-Lorentz

The Tauc-Lorentz model combines a Tauc absorption edge with a Lorentz
oscillator. Its imaginary permittivity vanishes below the optical gap and is
causally paired with the real part through a Kramers-Kronig relation. An
extended variant may combine multiple transitions; the exact extension must
be documented rather than treated as a single universal formula.

## Composite materials

Effective-medium approximations estimate a bulk permittivity from constituent
permittivities $\epsilon_i$ and volume fractions $f_i$, with
$\sum_i f_i=1$. Their validity depends on inclusion geometry, scale, and
connectivity; they are not interchangeable mixing rules.

### Maxwell-Garnett

For spherical inclusions with permittivity $\epsilon_i$ in a continuous host
$\epsilon_h$, at inclusion fraction $f$:

$$
  \epsilon_{\mathrm{eff}}=\epsilon_h
  \frac{\epsilon_i+2\epsilon_h+2f(\epsilon_i-\epsilon_h)}
  {\epsilon_i+2\epsilon_h-f(\epsilon_i-\epsilon_h)}.
$$

This asymmetric approximation distinguishes the host from the inclusions and
is most appropriate at relatively low inclusion fractions.

### Bruggeman

The symmetric spherical-inclusion approximation defines $\epsilon_{\mathrm{eff}}$
implicitly:

$$
  \sum_i f_i
  \frac{\epsilon_i-\epsilon_{\mathrm{eff}}}
  {\epsilon_i+2\epsilon_{\mathrm{eff}}}=0.
$$

Computing it requires selecting a physically continuous solution branch across
the spectrum.

### Looyenga

The Looyenga rule mixes the cube roots of the constituent permittivities:

$$
  \epsilon_{\mathrm{eff}}^{1/3}=\sum_i f_i\epsilon_i^{1/3}.
$$

For complex inputs, the cube-root branch must be chosen consistently. Any
asymmetric Looyenga or Bruggeman variant should state its host and inclusion
assumptions explicitly.

## Forward measurement models

Forward models predict measured quantities from material properties and
experiment configuration. They should make geometry, layer thickness,
incidence angle, polarization, substrate, and spectral convention explicit.

### Ellipsometry

Ellipsometry measures the change in polarization of light upon reflection
from, or transmission through, a sample. For a non-depolarizing sample, the
fundamental response is the complex ratio of the Fresnel reflection
coefficients for $p$- and $s$-polarized light:

$$
\rho \equiv \frac{r_p}{r_s}
=
\frac{|r_p|}{|r_s|}e^{i(\phi_p-\phi_s)}
=
\tan(\Psi)e^{i\Delta}.
$$

Thus,

$$
\Psi=\arctan\left(\frac{|r_p|}{|r_s|}\right),
\qquad
\Delta=\arg(r_p)-\arg(r_s).
$$

Here $r_p$ and $r_s$ are the complex Fresnel reflection coefficients for
electric fields parallel and perpendicular to the plane of incidence,
respectively. $\Psi$ describes the $p$-to-$s$ amplitude ratio, while $\Delta$
describes their relative phase.

An ellipsometer does not measure $n$, $k$, or $\epsilon_r$ directly. A
polarizer prepares a known input polarization state. After interaction with
the sample, a rotating analyzer, rotating compensator, or phase modulator
converts the output polarization state into a time-varying detector
intensity. The Fourier components of this intensity are then used to recover
the sample polarization response.

For a rotating-analyzer ellipsometer, the detector intensity has the form

$$
I(A)=I_0+I_C\cos(2A)+I_S\sin(2A),
$$

where $A$ is the analyzer angle. The measured Fourier coefficients are

$$
\alpha=\frac{I_C}{I_0},
\qquad
\beta=\frac{I_S}{I_0}.
$$

These coefficients are related to the ellipsometric angles by

$$
N=\cos(2\Psi),
\qquad
S=\sin(2\Psi)\cos\Delta,
\qquad
C=\sin(2\Psi)\sin\Delta.
$$

Depending on the instrument architecture, the raw data may therefore be
reported as $(\Psi,\Delta)$, $(\alpha,\beta)$, or $(N,S,C)$. Rotating
analyzer, rotating polarizer, rotating-compensator, and phase-modulation
ellipsometers differ in how the polarization state is encoded into the
detector signal, but all ultimately measure a polarization change rather than
a material property directly.

For a stratified sample, the forward model computes the effective $p$ and $s$
reflection coefficients of the complete stack from the complex refractive
indices, layer thicknesses, wavelength, incidence angle, substrate, and
ambient medium. It then predicts

$$
\rho_{\mathrm{model}}(\lambda,\theta_i;\boldsymbol{\theta})
=
\frac{r_{p,\mathrm{model}}}{r_{s,\mathrm{model}}},
$$

and compares either $(\Psi_{\mathrm{model}},\Delta_{\mathrm{model}})$ or
$(N_{\mathrm{model}},S_{\mathrm{model}},C_{\mathrm{model}})$ with the
corresponding measurements.

A practical fitting objective is

$$
L(\boldsymbol{\theta})
=
\sum_{\lambda}\sum_{\theta_i}
\left[
w_\Psi\left|\Psi_{\mathrm{model}}-\Psi_{\mathrm{meas}}\right|^2
+
w_\Delta\left|\Delta_{\mathrm{model}}-\Delta_{\mathrm{meas}}\right|^2
\right].
$$

When measurement uncertainties are available, a weighted objective is
preferable:

$$
L(\boldsymbol{\theta})
=
\sum_{\lambda}\sum_{\theta_i}
\left[
\frac{\left|\Psi_{\mathrm{model}}-\Psi_{\mathrm{meas}}\right|^2}
{\sigma_\Psi^2}
+
\frac{\left|\Delta_{\mathrm{model}}-\Delta_{\mathrm{meas}}\right|^2}
{\sigma_\Delta^2}
\right].
$$

Measurements at multiple incidence angles and wavelengths constrain thickness,
interface roughness, and dispersion parameters, but do not guarantee a unique
solution. Correlated parameters, film-thickness/index ambiguity, and multiple
local minima remain possible. Ellipsometry should therefore be treated as
model-based fitting rather than pointwise conversion of $\rho$ into
$\tilde n$.

Practical ellipsometric measurements should record:

- The wavelength or photon-energy grid.
- Incidence angle or angles.
- Polarization convention and plane-of-incidence definition.
- Ambient medium, substrate, and assumed layer stack.
- Polarizer/analyzer calibration and compensator retardance, if applicable.
- Roughness, depolarization, or Mueller-matrix treatment when required.
- Fitted parameters, bounds, residuals, and uncertainty estimates.

### S-parameter retrieval

Assume a homogeneous slab of thickness $d$, surrounded by a known medium, with
plane-wave illumination at normal incidence. Let $k_0=\omega/c$, and define
the one-way propagation factor

$$
P=e^{i\tilde n k_0d},
$$

where $\tilde n$ is the complex refractive index relative to the surrounding
medium.

#### Symmetric slab

For a symmetric slab, the reflection coefficient seen from either side is the
same:

$$
\Gamma_1=\Gamma_2\equiv\Gamma.
$$

Summing the internal multiple reflections gives

$$
S_{11}
=
\frac{\Gamma(1-P^2)}{1-\Gamma^2P^2},
\qquad
S_{21}
=
\frac{P(1-\Gamma^2)}{1-\Gamma^2P^2}.
$$

Define the Nicolson–Ross–Weir combinations

$$
V_1=S_{21}+S_{11},
\qquad
V_2=S_{21}-S_{11}.
$$

Then, up to branch choices,

$$
\Gamma
=
X\pm\sqrt{X^2-1},
\qquad
X=
\frac{1-V_1^2+V_2^2}{2V_1}.
$$

The normalized wave impedance is

$$
z
=
\pm
\sqrt{
\frac{(1+V_1)(1+V_2)}
{(1-V_1)(1-V_2)}
}.
$$

The relative refractive index follows from the propagation phase:

$$
\tilde n
=
\frac{1}{k_0d}
\left[
\pm\arccos\left(\frac{1-V_1^2+V_2^2}{2V_1}\right)
+2\pi m
\right],
\qquad m\in\mathbb Z.
$$

For an isotropic effective medium,

$$
\epsilon_{r,\mathrm{eff}}=\frac{\tilde n}{z},
\qquad
\mu_{r,\mathrm{eff}}=\tilde n z.
$$

The signs in the expressions for $\Gamma$, $z$, and $\tilde n$ are not
independent. They must be selected so that $\operatorname{Im}\tilde n\ge0$ for
a passive material under the $e^{-i\omega t}$ convention, the impedance has
the correct passive sign, and the retrieved branch varies continuously with
frequency. Phase unwrapping through the integer $m$ is essential for optically
thick samples or large refractive indices.

#### Asymmetric slab

For an asymmetric slab, the air-to-slab and slab-to-air reflection
coefficients differ:

$$
\Gamma_+\ne\Gamma_-,
$$

while reciprocity still gives equal transmission in both directions. The
forward and backward measurements are

$$
S_{11}
=
\frac{\Gamma_+(1-P^2)}
{1-\Gamma_+\Gamma_-P^2},
\qquad
S_{22}
=
\frac{\Gamma_-(1-P^2)}
{1-\Gamma_+\Gamma_-P^2},
$$

$$
S_{21}=S_{12}
=
\frac{P(1-\Gamma_+\Gamma_-)}
{1-\Gamma_+\Gamma_-P^2}.
$$

Thus, $S_{11}$ and $S_{22}$ contain distinct physical information. Reducing an
asymmetric sample to a symmetric effective-medium model using only $S_{11}$
can produce biased or nonphysical parameters.

A common effective-symmetric approximation averages the two reflection
coefficients:

$$
\Gamma_{\mathrm{avg}}
=
\frac{\Gamma_++\Gamma_-}{2}.
$$

One then substitutes $\Gamma_{\mathrm{avg}}$ into the symmetric
Nicolson–Ross–Weir inversion. This approximation is appropriate only when the
goal is an effective symmetric description and the reflection asymmetry is
moderate; it is not a unique inversion of the full asymmetric scattering
matrix.

For a full asymmetric retrieval, solve directly for $\Gamma_+$, $\Gamma_-$,
and $P$ from measured $S_{11}$, $S_{22}$, and $S_{21}$. From the transmission
equation,

$$
P
=
\frac{S_{21}}
{1-\Gamma_+\Gamma_-P},
$$

or equivalently,

$$
\Gamma_+\Gamma_-
=
\frac{1}{P}
-
\frac{1}{S_{21}P^2}.
$$

The reflection equations give

$$
\frac{\Gamma_+}{\Gamma_-}
=
\frac{S_{11}}{S_{22}}.
$$

Given a branch choice for $P$,

$$
\Gamma_+
=
\pm
\sqrt{
\frac{S_{11}}{S_{22}}
\left(
\frac{1}{P}
-
\frac{1}{S_{21}P^2}
\right)
},
\qquad
\Gamma_-
=
\frac{S_{22}}{S_{11}}\Gamma_+.
$$

The propagation factor satisfies

$$
P=e^{i\tilde n k_0d},
$$

so

$$
\tilde n
=
\frac{1}{ik_0d}\log P.
$$

The logarithm branch must be selected to give a continuous $\tilde n(\omega)$
and $\operatorname{Im}\tilde n\ge0$ for a passive sample. In practice, this
inversion is usually implemented as a constrained nonlinear least-squares fit
rather than a closed-form pointwise formula, because the correct phase branch
and passive-sign choices are coupled.

#### Measurement caveats

- **Reference planes:** $S_{11}$, $S_{21}$, and $S_{22}$ must be de-embedded to the physical sample faces. VNA calibration reference planes, fixture phase, and cable or connector delays can otherwise introduce large retrieval errors.
- **Thickness:** The sample thickness $d$ must be known accurately, since it sets the phase scale in $P$.
- **Phase unwrapping:** The correct branch of $\tilde n$, equivalently the integer $m$, should be selected using a low-frequency or thin-sample limit, prior knowledge, or continuity across frequency.
- **Homogeneity:** Retrieval assumes an effectively homogeneous slab. Strong spatial dispersion, grating diffraction, or a unit cell comparable to the wavelength invalidates a simple $(\epsilon_r,\mu_r)$ interpretation.
- **Loss and passivity:** For a passive material under $e^{-i\omega t}$, enforce $\operatorname{Im}\epsilon_r\ge0$, $\operatorname{Im}\mu_r\ge0$, and appropriate signs for $\operatorname{Re}\tilde n$ and impedance.
- **Asymmetry:** Report both $S_{11}$ and $S_{22}$ whenever the sample is not mirror-symmetric. An averaged-reflection retrieval should be labeled as an effective symmetric approximation, not as a unique material inversion.

## Fitting and differentiability

Given observations $y$ and a differentiable forward model $g(\theta)$, fit
model parameters $\theta$ by minimizing a weighted residual objective such as

$$
  L(\theta)=\sum_j w_j\left|g_j(\theta)-y_j\right|^2.
$$

JAX transformations can provide gradients and support optimization, but do
not remove physical constraints or inverse-problem ambiguities. A fitting API
should make parameter bounds or transforms, weighting, initialization,
uncertainty, and convergence status explicit. Gradients should be checked
against finite differences on representative parameter sets.

## References

- M. A. Ordal et al., “Optical properties of the metals Al, Co, Cu, Au, Fe,
  Pb, Ni, Pd, Pt, Ag, Ti, and W in the infrared and far infrared,” *Applied
  Optics* 22, 1099–1119 (1983).
- A. B. Djurišić and E. H. Li, “Modeling the optical constants of
  semiconductors using the Tauc-Lorentz model,” *Applied Physics Letters* 73,
  1058–1060 (1998).
- O. Stenzel, *The Physics of Thin Film Optical Spectra: An Introduction*,
  Springer (2005).
