# XMDM Database

## Layout

The database is material-first. Each material directory contains one JSON file
per measured dataset or model fit; `model` is a record field, not a directory
level. This keeps all representations of a material together.

```text
db/
  index.json
  Ag/
    <record-uuid>.json
    <record-uuid>.json
  Au/
    <record-uuid>.json
```

`index.json` is the catalog of materials and their records. Material directory
names are stable identifiers (chemical symbols where available), not display
names. The index stores display names, aliases, and each record's relative path,
model, and source. Record UUIDs are deterministic for the legacy source record,
so rerunning the migration does not change record paths.

Each record file is a JSON object. `schema_version` matches
`xmdm.__schema_version__` and is the string `"1"`. The record `name` is the
dataset or model source name, so it can be selected as `<material>/<name>`
(for example, `Ag/Johnson` or `Au/Palik`). For tabulated records it is the
legacy filename without its extension; for fitted models it is the short source
label.

```JSON
{
"schema_version": "1",
"physics": "<physics context>",
"model": "<model=tabulated/drude/lorentz/sellmeier/cauchy/rii_formula>",
"name": "<dataset or source name>",
"id": "<uuid>",
"data": {},
"metadata": {}
}
```

The `data` and `metadata` fields depend on the model. Legacy metadata is
preserved when available; unknown authors and timestamps are omitted rather
than inferred. Legacy records may include their original path for traceability.

`physics` identifies the physical domain of an individual record. Linear
optical records use `"physics": "optics"`; tabulated `n2` records use
`"physics": "nlo"` (nonlinear optics). The same field is stored on their
record references in `index.json` so catalogs can distinguish future domains
without opening every record. It is not a material-level classification:
one material may eventually have both optical and thermal property records.
This additive metadata does not change schema version `"1"` or the existing
optical lookup and interpolation APIs. XMDM can load `n2` tables; the server
supports catalog filtering by `physics`, evaluation with `parameter="n2"`,
and resampling that retains the nonlinear classification.

## Models

For tabulated materials:

```JSON
{
"schema_version": "1",
"physics": "optics",
"model": "tabulated",
"name": "CRC",
"id": "<uuid>",
"data": {
  "unit": "<spectral-coordinate unit>",
  "type": "<n, nk, e, eps, k, or n2>",
  "f": [f0, f1, f2],
  "re": [re0, re1, re2],
  "im": [im0, im1, im2],
  "additional_columns": {}
},
"metadata": {
  "source": "<reference>",
  "description": "<comments>",
  "legacy_path": "tabulated/Ag/CRC.yml"
}
}
```

`f` is the source dataset's spectral coordinate (often wavelength), not
necessarily frequency. Its original `unit` and `type` are preserved. The real
and imaginary columns are stored separately as `re` and `im`.
Datasets with more columns preserve them in `additional_columns`, keyed by
column name. A two-column `n`, `k`, or `n2` dataset has a zero imaginary component.
`k` stores the extinction coefficient in `re`; `n2` stores the real nonlinear
index coefficient in `re`. These property types are not converted into `n` or
permittivity. If a sidecar supplied extra columns, its path is recorded in
`metadata.additional_legacy_paths`.


For a Drude model,

```JSON
{
"schema_version": "1",
"physics": "optics",
"model": "drude",
"name": "Ordal",
"id": <uuid>,
"data": {
  "eps_inf": <epsilon infinity>,
  "omega_p": <plasma frequency>,
  "gamma": <gamma>,
},
"metadata": {
  "source": "<reference>",
  "description": "<comments>",
  "legacy_path": "drude.yml"
}
}
```

$$
  \varepsilon(\omega) = \varepsilon_\infty - \frac{\omega_p^2}{\omega^2 + i \gamma \omega}
$$
where 
  $\varepsilon_\infty = \varepsilon(\omega \to \infty)$ is the high-frequency permittivity,
  $\omega_p$ is the plasma frequency,
  $\gamma$ is the Drude damping rate.



For a (Drude-)Lorentz model,

```JSON
{
"schema_version": "1",
"physics": "optics",
"model": "lorentz",
"name": "Rakic",
"id": <uuid>,
"data": {
  "eps_inf": <epsilon infinity>,
  "omega_p": <plasma frequency>,
  "f": [f0, f1, f2, ...],
  "gamma": [g0, g1, g2, ...],
  "omega_0": [w0, w1, w2, ...]
},
"metadata": {
  "source": "<reference>",
  "legacy_path": "lorentz.yml"
}
}
```

$$
  \varepsilon(\omega) = \varepsilon_\infty + \sum_j \frac{f_j\omega_p^2}{\omega_{0,j}^2 - \omega^2 - i \gamma_j \omega}
  $$
  where 
    $\varepsilon_\infty$ is the high-frequency permittivity,
    $\omega_p$ is the shared plasma frequency,
    $f_j$, $\omega_{0,j}$, and $\gamma_j$ are the oscillator strength, resonance frequency, and damping rate of the j-th Lorentz oscillator. The implemented Lorentz model is this oscillator sum and does not add a separate Drude term.


For a Sellmeier model,

```JSON
{
"schema_version": "1",
"physics": "optics",
"model": "sellmeier",
"name": "<dataset or source name>",
"id": <uuid>,
"data": {
  "unit": "<wavelength unit; default um>",
  "B": [B0, B1, B2, ...],
  "C": [C0, C1, C2, ...]
},
"metadata": {
  "source": "<reference>"
}
}
```

$$
  n^2(\lambda) = 1 + \sum_i \frac{B_i \lambda^2}{\lambda^2 - C_i}
$$
where 
  $B_i$ and $C_i$ are the Sellmeier coefficients,
  $\lambda$ is the wavelength.



For a Cauchy model,

```JSON
{
"schema_version": "1",
"physics": "optics",
"model": "cauchy",
"name": "<dataset or source name>",
"id": <uuid>,
"data": {
  "A": <A>,
  "B": <B>,
  "C": <C>,
  "unit": "<wavelength unit; default um>"
},
"metadata": {
  "source": "<reference>"
}
}
```

$$
  n(\lambda) = A + \frac{B}{\lambda^2} + \frac{C}{\lambda^4}
$$
where 
  $A$, $B$, and $C$ are the Cauchy coefficients,
  $\lambda$ is the wavelength.

For a RefractiveIndex.INFO analytic formula,

```JSON
{
"schema_version": "1",
"physics": "optics",
"model": "rii_formula",
"name": "<dataset or source name>",
"id": "<uuid>",
"data": {
  "formula": 1,
  "coefficients": [c0, c1, c2],
  "unit": "um",
  "wavelength_range": [0.2, 2.0]
},
"metadata": {
  "source": "<original reference>; downloaded from refractiveindex.info"
}
}
```

The `formula` field selects one of RefractiveIndex.INFO's formulae 1–9;
`coefficients` retain their upstream order. Formula wavelengths and tabulated
coordinates from this source are in micrometres. Optional wavelength ranges
are kept as supplied. Incomplete upstream coefficients are preserved and
reported as evaluation errors rather than inferred.

For a Lorentz record migrated from the legacy database, the source field
`omega` is represented as `omega_0` in the JSON schema. The Lorentz-model
parameters in the existing data are expressed in eV.

`metadata` may include fabrication conditions, measurement setup,
environmental conditions, source references, descriptions, and source
warnings. All RefractiveIndex.INFO imports omit `refractiveindex_entry_type`,
`database`, `database_*`, and `source_reference`; import-only `database_*`
fields are also removed from their catalog references. Legacy records with
unmatched RII attribution instead use "downloaded from Lumerical", retaining
their publication references. Explicit local measurements preserve their
measurement citations and identify POSTECH. Fields absent from the source
are not fabricated.

## Bundled database contents

The bundled `xmdm-db` contains 1,472 records across 277 materials, including
the pinned RefractiveIndex.INFO `main` dataset. Its 1,383 entries comprise 994
tabulated records (`nk`: 633, `n`: 121, `k`: 33, `n2`: 207) and 389 analytic
formula records. Of the 1,472 catalog records, 207 use `physics="nlo"` and
1,265 use `physics="optics"`. The one-time main-library import excluded `glass` and
`organic` libraries and preserved original references with the attribution
"downloaded from refractiveindex.info". The already bundled PDMS/Zhang record
was separately refreshed from the organic library as `PDMS/Zhang-10-1`;
no other organic records were added.

Fresh upstream entries replace equivalent legacy records, including unit
conversions, n/k-to-permittivity conversions, and sampled formula equivalents
within the legacy table's recorded numerical precision. The 13 originally
reused entries now use upstream-derived UUIDs; 28 additional legacy duplicates
were removed. Use upstream names and models, such as `CdSe/Bond-o` instead of
`CdSe/Bond_o`, `GaN/Kawashima` instead of `GaN/Adachi`, and `Si/Pierce` instead
of `a-Si/Pierce`. `Si3N4/Luke` now uses `rii_formula`, not `tabulated`.
Removed legacy UUIDs are no longer available.

This is a static snapshot, not an ongoing synchronization with upstream.
No recurring importer or automatic database refresh is provided. The upstream
database is dedicated to the public domain under CC0 1.0; cite each original
record reference and M. N. Polyanskiy, *Scientific Data* **11**, 94 (2024)
when using the imported dataset. The pinned source is commit
[`c5c2f188e848453def5970e347399d653df2ffc2`](https://github.com/polyanskiy/refractiveindex.info-database/tree/c5c2f188e848453def5970e347399d653df2ffc2/database/data/main).
In this snapshot, `AgGaSe2/Boyd-o` has an incomplete formula-2 coefficient
list upstream; its values are preserved and evaluation reports the source
error rather than inferring the missing coefficient.