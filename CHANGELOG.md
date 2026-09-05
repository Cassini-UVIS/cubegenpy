# Release notes

<!-- do not remove -->

## 0.2.1 — Correct null value in widened RAW_COUNTS

### Fixes
* The PDS3 null (65535) was not always becoming the proposal's `-1` on write.
  `np.where(is_null, -1, uint16_array)` is unsafe: numpy >= 2.5 raises
  `OverflowError`, and numpy < 2.5 silently wraps `-1` to 65535. The wrap
  double-wraps back to `-1` when narrowing to int16 — correct by accident — but
  survives as **65535 when widening to int32**, so every product that overflowed
  int16 carried a null the `BLANK` keyword misdescribes, with no error anywhere.

  The array is now widened to int32 before the null is inserted, then narrowed.
  A regression test asserts the null *value* in both integer widths, rather than
  the absence of a crash, since the absence of a crash is what hid this: the
  suite passed on numpy 2.4.6 locally while failing on 2.5.2 in CI.

  Affects only products with counts above 32,767 — the ~90 in Showalter's list.

## 0.2.0 — Workbook-driven writer, v2 layout, metadata skeleton

The package now writes a complete, proposal-shaped product. The layout is no
longer written in Python: it is read from the data-definition workbook, which
carries Showalter's **v2** proposal (12 Aug 2026).

### The workbook is the source of truth

* New `cubegenpy.template` loads `UVIS_data_definition_v0.5.xlsx` into the same
  `HDUSpec` / `Column` / `Keyword` dataclasses the writer already consumed:

      workbook -> template.load() -> HDUSpec/Column/Keyword -> build_hdulist

  Nothing downstream changed. `layout.py` remains as the v1 baseline — a
  dependency-free fallback and a fixture for testing the loader against.
* Sheets: `hdus`, `columns`, `header_keywords`, `hdu_keywords`, `dimensions`,
  `enums`, `open_questions`, `raw_width_overrides`. Categorical cells are
  validated against `enums` at load, so a typo in `null_mode` fails loudly
  rather than producing an archive with wrong null semantics.
* `hdu_keywords` covers extension headers (`BLANK`, `RAWWIDEN`, `BUNIT`), which
  were previously stamped from code — the one part of the file the spreadsheet
  did not control.
* The workbook ships as package data. Loading it is not optional-but-silent: if
  it cannot be read, `hdu_specs()` warns via `TemplateFallback` and says plainly
  that output will not match v2.

### v2 layout

* 10 HDUs in proposal order, with the new `BACKGROUND` at index 3 and
  `WAVELENGTH` moved to last. `RING_GEOM` is always present (v2 p.14, *"It
  always contains one row"*), which keeps HDU indices constant across the
  archive.
* Column inventories updated to v2: `SC_GEOM` 25 fields (centric/graphic
  latitude splits; `PHI` moved to `RING_GEOM` as `RING_AZIMUTH`;
  `SATURN_LOCAL_TIME` replaced by `SUB_SC_LOCAL_TIME` in hours), `BODY_GEOM` 13
  (`RESOLUTION_*` out, `LOCAL_TIME` in), `GENERAL_GEOM` 3, `RING_GEOM` 14.
* New primary-header keywords `WAVEMIN` / `WAVEMAX` / `WAVESTEP`.

### Fixes

* **Image axis order was transposed.** The writer passed cube, raw counts and
  cal factor straight to astropy, which reverses numpy shape on write, so files
  came out with `NAXIS1 = NZ`. The proposal (p.3) requires `NAXIS1` =
  wavelengths, matching PDS3 `AXIS_NAME = (BAND, LINE, SAMPLE)`. Reversal now
  happens once at the FITS boundary and is undone by the reader, so callers keep
  the natural `(NX, NY, NZ)` that pyuvis returns. Because pyuvis reshapes with
  `order="F"`, the transpose is a no-copy view and the FITS data section
  reproduces the PDS3 byte sequence.
* **`RAW_COUNTS` is signed, not `uint16`.** FITS expresses unsigned 16-bit as
  `BITPIX=16` + `BZERO=32768`, which writes offset binary — physical 0 becomes
  `0x8000`. No byte matches PDS3, and PDS4 would have to restate the offset as
  `value_offset`, describing the transformation twice; a reader honouring both
  applies it twice. Since PDS4 requires the label alone to be sufficient, the
  file carries one description: signed, no offset, no scaling. Nulls are `-1`,
  declared with `BLANK`.
* **Overflow is detected at write time.** Counts above 32,767 widen that product
  to int32, warn with the peak value, and record `RAWWIDEN = T`. The affected
  set is an output of the build, recoverable from headers, rather than requiring
  a pre-flight survey of the archive.
* `fitsio` and `sources` were still reading hardcoded v1 specs while the writer
  had moved on, so reader and writer had silently diverged.
* Packaging: `pandas` and `openpyxl` were undeclared, and the workbook was not
  shipped — together, an installed package would have quietly emitted v1-shaped
  products.

### Two-stage build

* New `cubegenpy.skeleton`: `write_skeleton()` emits a geometry-complete,
  science-empty product so the geometry provider can write the archive file
  directly and calibration fill it afterwards. The interchange format stops
  being a negotiated dict and becomes the FITS file.
* `geometry_contract()` prints the expected array shape per column in numpy
  order *and* FITS `TDIM`, since those are reversed and easy to confuse.
  `check_skeleton()` reports which columns took data and which are still zeros.
* Placeholders are NaN and the PDS3 null, never zero: a zero flux is legal and
  would let an unfilled product pass unnoticed. `PIPESTAT = GEOMETRY_ONLY`
  marks a half-filled product; `calibrated_header()` promotes it.

### NT as a policy

* New `cubegenpy.subsampling`. v2 fixes `NT >= 3` and leaves the rest TBD, so
  the rule is a settable object rather than a constant:
  `SubsamplingPolicy.recommend(smear_pixels)` places sample points no more than
  `pixels_per_subsample` apart, clamped to `[minimum, maximum]`. The floor
  cannot be set below 3. `smear_pixels()` converts a slew rate for the common
  case.
* Only the *rule* is recorded, in `NT_RULE`. `NT` itself is already the last
  axis of every backplane `TDIM`; a keyword repeating it could disagree.

### OO core

* `Source` / `Calibrator` / `CubeBuilder` with `ProductInputs` as the
  interchange payload; `SyntheticSource` for network-free builds,
  `FitsReadbackSource` for recalibration; `read_product()` as the layout-driven
  inverse of `build_hdulist`. `build_cube` is now a back-compat shim over
  `CubeBuilder`; the production path (real PDS fetch + external geometry)
  remains unwired.

### Documentation

* `docs/tutorials/write_metadata_skeleton.ipynb` — executed end to end, no
  network or real data required.
* `product.py` records the array conventions shared with pyuvis (axis order,
  uint16/65535 nulls, Angstrom vs nm), which were assumed on both sides and
  enforced by neither.
* `labels.py` records the PDS4 label structure taken from a real MAVEN IUVS
  label, including two traps: FITS `TDIM` maps to nested `Group_Field_Binary` in
  **reversed** axis order, and the `data_type` enumeration lives in the
  Schematron, so `xmllint --schema` alone accepts a garbage type.

### Requires

* `pyuvis >= 0.9.2`, `pandas`, `openpyxl`.

## 0.1.0 — Initial scaffolding

* Project layout (hatchling, src, pyproject.toml, bump-my-version config).
* Public API stub: `cubegenpy.build_cube(...)` raising `NotImplementedError`.
* `docs/index.qmd` mapping every IDL `.pro` file to its Python target (or
  noting that the functionality is replaced by `pyuvis` / external geometry
  / dropped GUI). Will become the homepage of the docs site.
* `refs/` preserves the FITS layout proposal (Mark Showalter, 2026-02) and
  the team meeting notes that motivate the design.

No functional code in this release — see `PORT_PLAN.md` for the roadmap it
laid out, and 0.2.0 above for what landed.
