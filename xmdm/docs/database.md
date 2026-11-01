# XMDM material database

The bundled `xmdm-db` is a material-first JSON catalog. It combines tabulated
optical properties and analytic dispersion records in one directory tree:

```text
xmdm-db/
  index.json
  Ag/
    <record-uuid>.json
  Si/
    <record-uuid>.json
```

Each top-level material key is a stable identifier (usually a chemical
formula or element symbol). The catalog entry provides a display name, aliases,
and record references. Each reference points to one record JSON file, whose
`model` field specifies how its `data` is represented. The database has no
separate directory per model.

The schema and record examples below describe the bundled database. See the
[database schema reference](../src/xmdm-db/README.md) for fuller model payload
examples and provenance fields.

## Select and load records

Pass a material/record selector to the relevant model loader. The bundled
database is used by default; `db` can point at another material-first JSON
database directory.

```python
from xmdm import Material, RefractiveIndexFormula

silver = Material.from_db("Ag/Johnson", unit="nm", kind="n", verbose=False)
formula = RefractiveIndexFormula.from_db("SiO2/Malitson")

print(Material.avail("Ag"))  # available tabulated records for silver
print(RefractiveIndexFormula.avail())
```

The record selector is `material/name`, not a path to the JSON file. Use
`Material.avail()` or a model's `avail()` method to list matching materials
and records. Each `from_db()` validates the record structure before creating
the model.

## Catalog and record layout

`index.json` has a schema version and a `materials` object. A simplified
catalog entry looks like:

```json
{
  "schema_version": "1",
  "materials": {
    "Ag": {
      "name": "Silver (Ag)",
      "aliases": ["Ag"],
      "records": [
        {
          "id": "00000000-0000-4000-8000-000000000001",
          "physics": "optics",
          "model": "tabulated",
          "name": "Johnson",
          "source": "Original publication reference",
          "path": "Ag/00000000-0000-4000-8000-000000000001.json"
        }
      ]
    }
  }
}
```

Each record file is a JSON object with `schema_version`, `physics`, `model`,
`name`, `id`, `data`, and `metadata`. The current schema version is `"1"`.
The record UUID, material directory, record name, model, and catalog reference
must agree. Relative record paths are checked to remain inside the database.
Linear optical records use `physics: "optics"`; tabulated nonlinear
coefficients (`type: "n2"`) use `physics: "nlo"` (nonlinear optics).
The same value is stored in the record and its catalog reference.

For tabulated records, `data` contains a coordinate `unit`, property `type`,
and equal-length arrays `f`, `re`, and `im`. Despite the conventional field
name `f`, the coordinates can be wavelengths, frequencies, wavenumbers, or
photon energies. Units are case-sensitive: `m`, `nm`, `um`, `Hz`, `GHz`,
`THz`, `cm-1`, and `eV`.

Tabulated property types are:

| `type` | Meaning | Stored values |
| --- | --- | --- |
| `n` | Complex refractive index | `re` is n; `im` is k (or zero for n-only input). |
| `nk` | Complex refractive index with n and k columns | `re` is n; `im` is k. |
| `e` / `eps` | Complex relative permittivity | `re` is \(\varepsilon_1\); `im` is \(\varepsilon_2\). |
| `k` | Extinction coefficient only | `re` is k; `im` is zero. |
| `n2` | Nonlinear refractive-index coefficient | `re` is \(n_2\); `im` is zero. |

`k` and `n2` remain their own properties; the library does not convert them
to refractive index or permittivity. For a table containing only one sample,
the value is defined at that coordinate only; querying another coordinate
returns a non-finite result rather than treating the lone sample as a constant
or an extrapolatable segment.

## Bundled database contents and provenance

The bundled catalog contains 1,472 records across 277 materials. It includes
1,383 entries from the RefractiveIndex.INFO `main` library: 633 `nk` tables,
121 `n` tables, 33 `k` tables, 207 `n2` tables, and 389 formula records.
The main-library import excludes `glass` and `organic`. The already bundled
PDMS/Zhang dataset was separately refreshed from the upstream organic library
as `PDMS/Zhang-10-1`; no other organic datasets were added.

Fresh upstream records take priority over equivalent legacy records, including
equivalents stored as permittivity rather than n/k, in different coordinate
units, or as sampled analytic formulas. Comparisons account for the numerical
precision of the legacy tables. The 13 initially reused entries now have their
upstream-derived UUIDs, and 28 additional legacy duplicates were removed.
There are 207 nonlinear and 1,265 linear optical records.

RII records retain their original reference with the attribution
"downloaded from refractiveindex.info", plus available source notes,
conditions, and warnings. All imported records omit
`refractiveindex_entry_type`, `database`, `database_*`, and `source_reference`;
their catalog references also omit the import-only `database_*` fields.
Material `about.yml` information is kept in the material catalog where supplied.
Legacy RII claims without a matching upstream dataset are corrected to
"downloaded from Lumerical", preserving original publication references.
Explicit local measurements retain their measurement citations and identify
POSTECH instead; they are not attributed to Lumerical.

Use the upstream selector names and models after deduplication. For example,
`CdSe/Bond_o` becomes `CdSe/Bond-o`, `GaN/Adachi` becomes `GaN/Kawashima`,
and `a-Si/Pierce` becomes `Si/Pierce`. `Si3N4/Luke` is now an `rii_formula`
record rather than a sampled `tabulated` record. Removed legacy UUIDs are no
longer catalog entries. Do not infer missing authors, conditions, or output units.

Amorphous silicon measurements are cataloged under `Si` alongside crystalline
silicon. Load the POSTECH measurement with `Si/a-Si-H`; `a-Si` remains an alias
for the silicon material, not a separate material ID.

The imported upstream snapshot is
[`c5c2f188e848453def5970e347399d653df2ffc2`](https://github.com/polyanskiy/refractiveindex.info-database/tree/c5c2f188e848453def5970e347399d653df2ffc2/database/data/main).
The upstream database is dedicated to the public domain under CC0 1.0.
When using the data, cite the particular record's original reference and
M. N. Polyanskiy, "Refractiveindex.info database of optical constants,"
*Scientific Data* **11**, 94 (2024), alongside the download attribution.

One record in that snapshot, `AgGaSe2/Boyd-o`, has an incomplete upstream
formula-2 coefficient list. Its coefficients are retained exactly; evaluation
reports the malformed list rather than guessing a missing value.

## Static snapshot and validation

The RefractiveIndex.INFO import was a one-time operation. The bundled JSON
files are a static snapshot, not a continuously synchronized upstream
database. There is no ongoing importer or automatic refresh.

Use `load_record()` to check an individual record's identity and structure,
and `validate_record_data()` to check its model data. The separately installed
`xmdm-server` package provides `xmdm verify` to validate the catalog. For a
custom database, maintain both the JSON record and its matching index
reference, including the `nlo` classification for `n2`.