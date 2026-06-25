# PORT_PLAN.md — IDL `cube_generator` → `cubegenpy`

**Goal:** recreate the *non-GUI* IDL UVIS cube-generation pipeline in Python, with
the final product = the **new PDS4 FITS file** (assembled by `cubegenpy.writer`,
per Mark Showalter's 2026-02 layout proposal), replacing the legacy IDL
`.cube`/`.sav` output.

**Two locked constraints (team decisions):**
1. **Geometry is supplied externally and is never recomputed by cubegenpy.** The
   entire IDL geometer path is skipped, not ported.
2. **Obsolete IDL code is dropped, not ported.** The IDL base (~6,250 LOC, 32
   `.pro` files) is mostly GUI, geometry, or superseded-by-pyuvis; only a thin
   science/orchestration core is genuinely needed.

This complements `docs/index.qmd` (the file-by-file disposition table); this file
is the **implementation recipe** — the verified pipeline and the build order.

---

## 1. The verified non-GUI pipeline (from `cg_nogui` → product)

Traced through `cg_nogui.pro` → `cube_single.pro` (mirrored by `cube_multi.pro`).
Stage type: **IO** / **CAL** (science) / **GEO** (geometry — skip) / **OUT** /
**ORCH** (orchestration).

| # | IDL stage | file:line | Type | Disposition in cubegenpy |
|---|-----------|-----------|------|--------------------------|
| 0 | `cg_nogui` entry, build `pass` struct | cg_nogui.pro:67 | ORCH | → `build_cube()` + `BuildConfig` |
| 1 | `cassini_spice_kernel_list_v2` + `cspice_furnsh` | cg_nogui.pro:102-107 | GEO | **SKIP** — kernel list passed in, written verbatim to `KERNELS` HDU |
| 2 | `cg_feuv_reader` / `open_pds_file` → raw cube `rof` | cube_single.pro:61 | IO | **DELEGATE** → `pyuvis.io.PDSReader` / `UVPDS` |
| 3 | raw counts captured (`rawdataa = rof`) | cube_single.pro:67 | CAL | → `RAW_COUNTS` HDU (int16) |
| 4 | counts → counts/sec (`rof/dd.integration`) | cube_single.pro:72 | CAL | pyuvis (or trivial divide) |
| 5 | per-readout ET/UTC times (`cspice_*`) | cube_single.pro:214-283 | GEO | **SKIP** — time comes from external geometry (`GENERAL_GEOM.TIME_ET`) |
| 6 | `GEOMETER_ENGINE` + backplane rebinning | cube_single.pro:343-458 | GEO | **SKIP ENTIRELY** — geometry is external input |
| 7 | optional RTG / spectral-avg background subtraction | cube_single.pro:462-499 | CAL | default OFF; defer (optional `BACKGROUND` HDU later) |
| 8 | wavelength vector (`f/e_Flight_Wavelength`) | cube_single.pro:557/617 | CAL | **DELEGATE** → pyuvis `BAND_BIN_CENTER`; constants kept below as fallback |
| 9 | `Get_UVIS_calibration` → cal factor (+error) | cube_single.pro:562/625 | CAL | **DECISION POINT** (see §4) |
| 10 | apply cal (`rof_1 = rof * calibration`) | cube_single.pro:597/645 | CAL | pyuvis `UVPDS.calibrated`, or ported multiply |
| 11 | `cg_interpolate_nans2` (FUV) | cube_single.pro:598 | CAL | port as `np.interp` per row (small) |
| 12 | assemble cube (cal + raw + geometry planes) | cube_single.pro:818-900 | ORCH | → `writer.build_hdulist(...)` (geometry planes come from the external dict) |
| 13 | provenance `note` strings | cube_single.pro:920-967 | OUT | → header keywords / PDS4 label |
| 14 | `cg_write_save_new /FITS` (+ ENVI/binary/sav) | cube_single.pro:1012 | OUT | **REPLACE** → `cubegenpy.writer.write_product` |

**Net:** cubegenpy owns stages 0, 3, 11, 12, 14. Stages 2/4/8/10 delegate to
pyuvis. Stages 1/5/6 are geometry → skipped. Stage 9 is the open decision.

---

## 2. What the FITS writer needs, and where each input comes from

| FITS input (`build_hdulist` arg) | Source |
|---|---|
| `cube` (calibrated, float32) | pyuvis `UVPDS.calibrated` **or** ported `Get_UVIS_calibration` (§4) |
| `raw_counts` (int16) | pyuvis raw read (`rof` before the integration divide) |
| `cal_factor` (2-D, float32) | PDS cal matrix via pyuvis **or** `cal_bin = 1/sens_bin` from ported cal |
| `wavelength` (float32, NX) | pyuvis `BAND_BIN_CENTER` (Å→nm) **or** grating eq (§5) |
| `header` (CONFIG keywords) | pyuvis PDS label fields (`PRODUCT_ID`, `START_TIME`, channel, IMG bounds, INT_TIME, …) |
| `geometry` (SC/BODY/GENERAL/RING) | **external** — supplied by caller, never computed here |
| `kernels` | **external** — kernel list passed in |
| `bodies`, `resolved_bodies`, `dims`, `rings_in_fov` | from the geometry payload + label |

---

## 3. Obsolete / drop list (confirmed)

These get **no** Python equivalent — obsolete, GUI, geometry, or superseded.

| IDL | LOC | Why dropped |
|---|---:|---|
| `cube_generator.pro` | 1107 | IDL widget GUI |
| `cube_control.pro` | 308 | GUI control flow |
| `cube_multi.pro` | 1009 | = `cube_single` + a file loop; covered by porting the core + iterating |
| `cg_write_save_new*.pro`, `cg_write_binary.pro`, `cg_write_envi.pro`, `cg_write_save_orig.pro` | ~800 | legacy `.sav`/ENVI/binary writers → replaced by FITS writer |
| `geometer_engine.pro` + geometry loops/rebinning | — | **geometry external** |
| à-la-carte cal branch (`ff_selector≠0`): `cg_Get_{FUV,EUV}_{97,99,03,04}_Lab_Calibration`, `cg_read_ajs_flf`, `cg_bin_win_flatfield`, `cg_get_fuv_red_patch` | — | non-default legacy path; superseded by the Greg "Ultimate" path / pyuvis `calib.steffl`+`calib.greg`. **Port only if legacy reprocessing is required.** |
| `cg_convert_sclk.pro` | 338 | frozen 2005 SCLK table (wrong after 2005) → use SPICE or label `START_TIME` |
| `cg_int1.pro` | 76 | generic linear interp → `numpy.interp` |
| `open_pds_file.pro`, `cg_feuv_reader.pro`, `cg_attget.pro`, PDS label parsers | — | → `pyuvis.io` (real `pvl` parser) |
| `uvis_wl.sav` | — | wavelengths from pyuvis |
| GUI assets (`*.gif`, `cg_settings_print`, `path_finder_*.txt`, `T-0.txt`) | — | machine-specific / GUI |

**Small genuine ports** (not in pyuvis): `cg_interpolate_nans2` (row-wise NaN
interp), and — only on the cal-regeneration fork — the FUV red-patch and the
windowed flatfield resampling (`cg_xerox`/`cg_shrink`/`cg_enlarg` → `block_reduce`/`np.kron`).

---

## 4. THE open decision — calibration source

The calibrated cube + `CAL_FACTOR` HDU can come from either:

**Option A — Delegate to pyuvis (recommended default).**
Read the archived, already-calibrated PDS product via `pyuvis.io.UVPDS`
(`.calibrated` = counts × PDS cal matrix → kR; wavelengths from `BAND_BIN_CENTER`;
flatfields via `calib.steffl`/`calib.greg`). cubegenpy becomes thin glue:
*pyuvis (data+cal) + external geometry → FITS*. Minimal new code, modern path,
no cal-data-file management.
*Cost:* `CAL_FACTOR` is whatever the PDS cal matrix encodes; exact bit-parity with
the IDL `Get_UVIS_calibration` is not guaranteed.

**Option B — Port `Get_UVIS_calibration` for full parity.**
Reimplement the Greg "Ultimate" time-varying cal (lab sensitivity + slit-width
ratio + pixel bandpass + Spica spectral modifier + flatfield + FF time-modifier,
then `cal_bin = 1/sens_bin`). Regenerates the cal factor independently of the PDS
matrix.
*Cost:* needs the calibration data files (`*_Lab_Cal.dat`, `FLATFIELD_*`, ~60
`*_ff_modifier_<sclk>.dat`, trending `.sav`) and ~several hundred lines; the
agents found pyuvis already has the Spica/Steffl machinery, so this is partial.

A seam (`BuildConfig.calibration: "pyuvis" | "regenerate"`) lets both coexist;
**default `"pyuvis"`** until parity is required.

---

## 5. Wavelength grating constants (verbatim, fallback if not using pyuvis)

```
RAD = 180.0 / pi
# FUV (f_flight_wavelength.pro)
D   = 1.0e7 / 1066
ALP = (9.22 + 0.032)/RAD + 3.46465e-5
BET = arctan((arange(1024) - 511.5) * 0.025 * 0.99815 / 300.0) + 0.032/RAD + 3.46465e-5
LAM_FUV = D * (sin(ALP) + sin(BET))          # Angstrom, length 1024
# EUV (e_flight_wavelength.pro)
D   = 1.0e7 / 1371.0
ALP = 8.03/RAD + 0.00032 - 0.0000565
BET = arctan((arange(1024) - 511.5) * 0.025 * 0.9987 / 300.0) - 1.19/RAD + 0.00032 - 0.0000565
LAM_EUV = D * (sin(ALP) + sin(BET))          # Angstrom, length 1024
```
Bin by `w_specbin` (mean per bin). Prefer pyuvis `BAND_BIN_CENTER` for archive
products; keep these for raw/NetCDF inputs.

---

## 6. Planned module layout (additions to the existing scaffold)

```
src/cubegenpy/
  build.py        # build_cube() orchestration (replace NotImplementedError)
  config.py       # BuildConfig dataclass (port of the IDL `pass` struct)  [this turn]
  layout.py       # proposal-as-data spec                  [done — writer work]
  writer.py       # build_hdulist + write_product          [done]
  labels.py       # draft PDS4 label                        [done]
  calibrate.py    # Option B only: ported Get_UVIS_calibration (deferred)
  utils.py        # interpolate_nans, block resample (only if Option B)
```

`build_cube` orchestration (Option A shape):
1. `fetch_product(pds_product_id)` via pyuvis/planetarypy → raw + label.
2. Pull `cube` (calibrated), `raw_counts`, `cal_factor`, `wavelength`, `header`
   fields from pyuvis.
3. Validate the external `geometry` dict against `layout` column specs.
4. `hdul = writer.build_hdulist(...)`; `writer.write_product(out_dir, pid, hdul)`.
5. Return `CubeProduct(fits_path, label_path, product_id)`.

---

## 7. Verification strategy

1. **Unit:** `BuildConfig` round-trips defaults; geometry-dict validator rejects a
   wrong-shaped column.
2. **Golden cube:** for one EUV and one FUV archive product, compare the
   cubegenpy calibrated cube against the IDL `.cube` (or pyuvis `.calibrated`)
   within tolerance — calibration parity check.
3. **End-to-end:** `build_cube(pid, stub_geometry, kernels, target, out)` writes a
   FITS that passes the existing `tests/test_writer.py` structural assertions.
4. **No-geometry guarantee:** assert no SPICE/geometer call path exists in
   cubegenpy (geometry is input only).

---

## 8. Phase order

1. **This turn:** PORT_PLAN.md (this file) + `config.py` scaffold + decision gate.
2. After the calibration decision: implement `build_cube` (Option A glue first).
3. Geometry-dict validator (`geometry.py`) against `layout` specs.
4. Golden-file calibration parity test (EUV + FUV).
5. Multi-window A/B split; optional `BACKGROUND` HDU (deferred, per 2026-02 notes).
