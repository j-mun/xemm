# Kramers-Kronig relations

The Kramers-Kronig (KK) relations connect the real and imaginary parts of a
causal linear response. They are consequences of causality and analyticity,
not independent empirical fitting equations.

## Convention and equations

Use the time dependence $e^{-i\omega t}$, consistent with the passive-loss
sign convention in XMDM's Drude and Lorentz expressions. For a causal response
$\chi(\omega)=\chi_1(\omega)+i\chi_2(\omega)$ that vanishes sufficiently
rapidly at high frequency, the full-frequency relations are

$$
\chi_1(\omega)=\frac{1}{\pi}\,\mathcal{P}
\int_{-\infty}^{\infty}
\frac{\chi_2(\Omega)}{\Omega-\omega}\,d\Omega,
$$
$$
\chi_2(\omega)=-\frac{1}{\pi}\,\mathcal{P}
\int_{-\infty}^{\infty}
\frac{\chi_1(\Omega)}{\Omega-\omega}\,d\Omega.
$$

$\mathcal{P}$ denotes a Cauchy principal value. For a real time-domain
$\chi_1$ is even and $\chi_2$ is odd. For positive
$\omega$, this gives

$$
\chi_1(\omega)=\frac{2}{\pi}\,\mathcal{P}
\int_0^\infty
\frac{\Omega\chi_2(\Omega)}{\Omega^2-\omega^2}\,d\Omega,
$$
$$
\chi_2(\omega)=-\frac{2\omega}{\pi}\,\mathcal{P}
\int_0^\infty
\frac{\chi_1(\Omega)}{\Omega^2-\omega^2}\,d\Omega.
$$

If the real part approaches a non-zero constant $\chi_\infty$, apply the
relations to the decaying response $\chi-\chi_\infty$. For relative
permittivity, the common high-frequency reference is $\varepsilon_\infty=1$
in vacuum; in a model with a different asymptote, subtract that asymptotic constant before applying the dispersion integral.

For refractive index, the corresponding positive-frequency form is commonly
written for $N(\omega)-1=n(\omega)-1+i\,k(\omega)$, when the response tends
to unity at high frequency:

$$
n(\omega)-1=\frac{2}{\pi}\,\mathcal{P}\int_0^\infty
\frac{\Omega k(\Omega)}{\Omega^2-\omega^2}\,d\Omega,
$$
$$
k(\omega)=-\frac{2\omega}{\pi}\,\mathcal{P}\int_0^\infty
\frac{n(\Omega)-1}{\Omega^2-\omega^2}\,d\Omega.
$$

These forms assume the stated causal convention, suitable high-frequency
decay, and a response that can be represented by the real/imaginary pair.
Changing the time convention changes the sign assigned to the imaginary
part.

## Practical interpretation

Absorption at one frequency contributes to the dispersive real response at
other frequencies. KK consistency therefore links measured $n$ and $k$
(or $\varepsilon_1$ and $\varepsilon_2$); they are not arbitrary
independent functions for a causal material.

Experimental spectra cover a finite band, while these relations integrate
over all positive frequencies. Applying a numerical KK transform to a finite
band requires assumptions or extrapolations outside the measured interval,
careful treatment of the principal-value singularity, and consistent unit
conversion. Baseline offsets, measurement noise, and unmeasured resonances can
strongly affect the inferred result.

## XMDM implementation status

The current `xmdm.kk` module is a placeholder and exposes no numerical KK
transform or validation function. The equations here are theoretical
background only. `Drude`, `Lorentz`, and the other dispersion models evaluate
their supplied expressions; they do not automatically enforce KK
consistency on arbitrary tabulated data.
