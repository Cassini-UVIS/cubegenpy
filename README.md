# cubegenpy

> Build PDS4-compliant FITS cubes for Cassini UVIS observations.

`cubegenpy` is the Python successor to the IDL `cube_generator` tool. Its
job is to combine raw UVIS PDS3 data, calibration matrices, and externally
computed SPICE-derived geometry into a single FITS file laid out per the
PDART team's 2026-02 proposal — plus a sibling PDS4 XML label, so the
result is an archive-ready PDS4 product.

Unlike the IDL predecessor, **cubegenpy does not compute geometry**. The
spatial backplanes (BODY_GEOM, SC_GEOM, GENERAL_GEOM, RING_GEOM) are
generated upstream by the team's geometry pipeline and passed in as
input.

## Status

**Scaffolding only.** See [`docs/index.qmd`](./docs/index.qmd) for the
IDL→Python translation map, the architectural delegation to `pyuvis`,
and the phase plan.

## Install (once implemented)

```bash
pip install cubegenpy
```

For development:

```bash
git clone https://github.com/Cassini-UVIS/cubegenpy
cd cubegenpy
pip install -e ".[dev,docs]"
```

Supported Python versions: **3.12, 3.13, 3.14**.

## Usage (planned API)

```python
from cubegenpy import build_cube

product = build_cube(
    pds_product_id="EUV2013_047_09_33_59",
    geometry=mark_geometry_dict,         # supplied by upstream pipeline
    spice_kernels=[                      # written into the KERNELS HDU
        "130321R_SCPSE_13038_13063.bsp",
        "naif0012.tls",
        # ...
    ],
    target="TITAN",
    out_dir="./out",
    write_pds4_label=True,
)
print(product.fits_path)   # ./out/EUV2013_047_09_33_59.fits
print(product.label_path)  # ./out/EUV2013_047_09_33_59.xml
```

## FITS layout

Mirrors Mark Showalter's 2026-02 proposal — see
[`refs/FITS-layout-proposal-MRS-2025-02-03.pdf`](./refs/FITS-layout-proposal-MRS-2025-02-03.pdf).

| HDU | Type | Content |
|---|---|---|
| `PRIMARY` | IMAGE float32 | Calibrated cube `(NX, NY, NZ)` |
| `RAW_COUNTS` | IMAGE int16 | Raw counts cube, same shape |
| `CAL_FACTOR` | IMAGE float32 | 2-D `(NX, NY)` calibration matrix |
| `WAVELENGTH` | IMAGE float32 | Center wavelengths, length `NX` |
| `SC_GEOM` | BINTABLE | Spacecraft + sub-spacecraft geometry per body |
| `BODY_GEOM` | BINTABLE | Spatial backplanes per resolved body |
| `GENERAL_GEOM` | BINTABLE | RA, DEC, TIME_ET (body-independent) |
| `RING_GEOM` | BINTABLE | Ring backplanes |
| `KERNELS` | TABLE (ASCII) | SPICE kernels used to compute geometry |

## Documentation

- [`docs/index.qmd`](./docs/index.qmd) — full IDL → Python translation
  map, architectural delegation, and phase plan. Renders as a Quarto
  page; will become the homepage of the docs site once the Quarto
  site is wired up (same pattern as `pyuvis`).

## Citation

If you use `cubegenpy` in your research, see
[`CITATION.cff`](./CITATION.cff).

## License

Apache 2.0 — see [`LICENSE`](./LICENSE).
