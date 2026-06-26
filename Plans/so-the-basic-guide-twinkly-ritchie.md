# cubegenpy OO core: CubeBuilder + Calibrator + FITS readback

## Context

cubegenpy is the Python successor to the IDL `cube_generator`. The writer layer
(`writer.py`, declarative `layout.py`, `labels.py`, `demo.py`) is done and stays
untouched. What's missing is the orchestration core: `build.py` is still a
`NotImplementedError` stub, and it disagrees with `config.py` (it passes
`calibration="default"`, which `BuildConfig` rejects).

This plan modernizes the IDL pipeline into a small OO core, driven by these
decisions (confirmed with the PI):

- **API = a class-based `CubeBuilder`** you configure, then call `.build()`.
- **Geometry is always external input, never computed** (the IDL SPICE
  `GEOMETER_ENGINE` per-pixel loop is dropped entirely).
- **No Showalter geometry data exists yet** → exercise FITS-building with
  **synthetic/random data** (reuse `demo.make_synthetic_product`). The real
  production pyuvis+Showalter source is a future seam, not built now.
- **Recalibration (user-time), as a start, changes ONLY the background-subtraction
  offset.** Read RAW_COUNTS + stored CAL_FACTOR + geometry + header back from a
  downloaded FITS, apply a new background offset, rewrite. No port of the IDL
  `Get_UVIS_calibration` is needed now.
- **Background subtraction is the central knob** (not deferred), modeled as a
  value/spec, not a bool.
- **Calibration must be extensible** to incorporate more stellar calibration
  observations (Spica, etc.) not yet fully analyzed → a `CalModel` extension seam.
- Dropped for good: multi-format output (FITS only) and temporal-smearing
  branches (store whatever `NT` the external geometry provides).

Intended outcome: a working `CubeBuilder` that produces a FITS product from
synthetic inputs, can read one of our FITS products back, and recalibrate it by
changing only the background offset — with the calibration component structured
so real pyuvis/Spica calibration models drop in later without touching the core.

## Status & resume checklist (handoff 2026-06-26)

**Done & committed on `main`** (`code/cubegenpy`):
- `8222253` — writer layer (`writer.py`, `layout.py`, `labels.py`, `demo.py`),
  `config.py`, `tests/test_writer.py`, `PORT_PLAN.md`.
- `c9b33ab` — docs review page + dark-mode inline-code fix.

**Uncommitted working tree** (present on disk, not yet committed):
- `docs/design.qmd` (this plan as a Quarto page w/ Mermaid diagrams) + `docs/_quarto.yml` nav wiring.
- `Plans/so-the-basic-guide-twinkly-ritchie.md` (this file).

**Nothing implemented yet** — `build.py:build_cube` is still `NotImplementedError`.
This plan is approved; next session starts at the build order below.

**Findings discovered after the plan was written — fold into implementation:**
1. **RAW_COUNTS dtype bug.** `writer.py:205` casts to signed `int16`
   (`np.asarray(raw_counts, dtype=np.int16)`), but raw UVIS counts are **uint16**
   (0–65535) → overflow above 32767. Fix: pass the uint16 array (astropy writes
   `BITPIX=16`+`BZERO=32768` automatically) or use int32. Also fix `layout.py:156`
   prose. This is required for the "RAW_COUNTS round-trips bit-identically" test.
2. **Raw vs cal dtype (verified from PDS labels).** Raw science QUBEs are
   `MSB_UNSIGNED_INTEGER` (uint16, COUNTS/BIN); the only `IEEE_REAL` (float32)
   data on PDS is the companion `*_CAL_<n>` calibration matrix (1024×64, kR) —
   exactly the `CAL_FACTOR` source / `PyuvisCalModel` input. (Not yet verified for
   TIME_SERIES HDAC/HSP or the 29 SPECTRUM products.)
3. **Windowing (from `cassini.uvis.supplemental_index`, 162,770 FUV/EUV imaging).**
   Spatial: ~73% full-slit (0–63), ~27% windowed → `IMG_YMIN/YMAX/YBIN` must handle
   arbitrary windows + line binning up to 64. Spectral: window almost always full
   (0–1023, ~98%), but `BAND_BINNING_FACTOR` is highly variable (1→1024) → derive
   the spectral axis from `(min_band, max_band, band_binning)`, never assume 1024.
   `-1` sentinel in windowing cols = HDAC+HSP (non-imaging, `DATA_OBJECT_TYPE=TIME_SERIES`).
4. **Stellar-calibration pool for the deferred `SpicaCalModel`:** 3,378 STAR-targeted
   observations (`cassini.uvis.index`, TARGET_NAME="STAR"); 1,341 are FUV+EUV
   (818 FUV / 523 EUV) — the spectral-imaging subset usable as calibration sources.

**Resume = the Build order section below**, with finding #1 applied in the writer
touch-up and #2–#4 informing the Calibrator/layout work.

## Design principle

`writer.build_hdulist(...)` kwargs (`cube, raw_counts, cal_factor, wavelength,
header, geometry, kernels, bodies, resolved_bodies, dims, rings_in_fov, edge_on`)
**are the interchange format**. Model a frozen `ProductInputs` dataclass equal to
that set. A `Source` produces a `ProductInputs`; the `Calibrator` fills its `cube`
field; `CubeBuilder.build()` splats it into `build_hdulist`. Synthetic-build and
FITS-readback-recalibrate become one pipeline with different front ends.

## Module / class layout (new files under `src/cubegenpy/`)

| File | Classes / fns | Responsibility | Reuses |
|---|---|---|---|
| `product.py` | `ProductInputs` (frozen), `CubeProduct` (moved from `build.py`) | Canonical payload mirroring `build_hdulist` kwargs; build result | `writer.Dims` |
| `calibrate.py` | `Background`, `CalModel` (Protocol), `StoredCalModel`, `PyuvisCalModel`, `Calibrator` | counts→calibrated cube + CAL_FACTOR; background knob; **extension seam** | `pyuvis.io`, `pyuvis.calib` |
| `fitsio.py` | `read_product(path) -> ProductInputs` | NEW: read our own FITS back into writer inputs, layout-driven | `layout`, `astropy.io.fits` |
| `sources.py` | `Source` (Protocol), `SyntheticSource`, `FitsReadbackSource` | Produce a `ProductInputs` | `demo`, `fitsio` |
| `builder.py` | `CubeBuilder` | Configure → `.build(out_dir) -> CubeProduct` | `writer`, `config` |
| `config.py` | `BuildConfig` (reconciled) | knobs incl. `background: Background` | — |
| `build.py` | `build_cube(...)` thin wrapper | back-compat functional entry over `CubeBuilder` | `builder`, `sources` |

## Calibrator (the focus) — `calibrate.py`

**Central formula** (this IS the recalibration case):
```
calibrated = (raw_counts / int_time − background_offset) × cal_factor
```
`Calibrator.calibrate(inputs, background) -> np.ndarray(float32)` operates entirely
in counts/sec space (`int_time` from `header["INT_TIME"]`), broadcasting the 2-D
`cal_factor` against the 3-D cube. `np.nan_to_num` stands in for the IDL row-wise
`cg_interpolate_nans2` (swap to a `np.interp`-per-row helper when real FUV data
lands).

**`Background`** (frozen dataclass) models the two IDL modes as data:
`mode: "none" | "rtg" | "spectral_average"`, `rtg_value=0.0004`, `spatial_bin`,
`spectral_bin`, `wavelength_range`. `.offset(counts_per_sec, wavelength)` returns
the scalar/array to subtract. This replaces the IDL's counts-vs-counts/sec
ambiguity and its `eq 2/eq 3` dimensionality branches (numpy broadcasting).

**`CalModel` (Protocol) — the extension seam** for how `cal_factor` is produced:
- `StoredCalModel(stored)` — recalibration: returns the FITS's CAL_FACTOR verbatim
  (no recompute). Used by the "stored" calibration mode.
- `PyuvisCalModel` — build path: derive cal_factor from pyuvis (`UVPDS`/cal matrix
  × `CORE_MULTIPLIER`). Thin glue; only exercised once real PDS data is wired.
- `SpicaCalModel` (**future, documented stub only**) — stellar-calibration-augmented
  cal factor composing lab sensitivity × spectral modifier × (1/flatfield), mapping
  onto IDL `Get_UVIS_calibration` and `pyuvis.calib.greg.get_spica_obs` /
  `steffl.Row2Row`. This is the seam for "more calibration observations not yet
  analyzed." Not implemented now; the Protocol guarantees it drops in.

Build path → `Calibrator(PyuvisCalModel())`; recalibration → `Calibrator(StoredCalModel(inputs.cal_factor))`,
so a rebuild with a new `Background` changes **only** the primary cube and the
CAL_FACTOR HDU is byte-identical.

## CubeBuilder — `builder.py`

`CubeBuilder(source, *, config=DEFAULT_CONFIG, calibrator=None)`. `.build(out_dir)`:
```
inputs     = source.load()
calibrator = self.calibrator or Calibrator(<model from config.calibration; StoredCalModel(inputs.cal_factor) when "stored">)
cube       = calibrator.calibrate(inputs, config.background)
inputs     = replace(inputs, cube=cube)
hdul       = writer.build_hdulist(**inputs.as_writer_kwargs())
paths      = writer.write_product(out_dir, inputs.header["PROD_ID"], hdul, write_label=config.write_pds4_label)
return CubeProduct(paths["fits"], paths.get("label"), product_id)
```
When `calibration="stored"`, the calibrator is built inside `build()` from
`inputs.cal_factor` (only available after `source.load()`).

**Sources** (`sources.py`): `Source` Protocol with `.load() -> ProductInputs`.
- `SyntheticSource` — refactor `demo.make_synthetic_product` so its array-building
  body returns `ProductInputs`; `make_synthetic_product` then becomes
  `CubeBuilder(SyntheticSource(...)).build()`. The demo's fabricated random *cube*
  is dropped (cube now comes from the Calibrator — more honest). `test_writer.py`
  only checks dtype/shape, so it still passes.
- `FitsReadbackSource(fits_path)` — delegates to `fitsio.read_product`.

## FITS readback — `fitsio.py` (NEW)

`read_product(path) -> ProductInputs` inverts the writer, **layout-driven**: iterate
`layout.hdu_specs(...)` so reader and writer share one source of truth. Correctness
points (all derived from `writer.py`/`layout.py`):
- Invert the CAL_FACTOR NULL sentinel (`== -1000.0` → `np.nan`) so a re-write
  reproduces it (round-trip stable).
- `NAME` columns are not geometry data — extract into `bodies`/`resolved_bodies`,
  drop from each geometry dict (writer re-adds them).
- Infer `NT` from a time-series TDIM (e.g. `GENERAL_GEOM.TIME_ET`), not hardcoded 3.
- Geometry cells come back in numpy slowest-first order `(nrows, NT, NZ, NY, 5)` —
  exactly what `build_hdulist` expects, so they pass straight through.

## Reconciled `config.py`

```python
CalibrationSource = Literal["pyuvis", "stored", "regenerate", "none"]

@dataclass(frozen=True)
class BuildConfig:
    calibration: CalibrationSource = "pyuvis"
    background: Background = Background()        # default mode="none"
    write_pds4_label: bool = True
    fits_version: float = 1.0
    # __post_init__: "regenerate" raises NotImplementedError (SpicaCalModel seam)
    # summary(): includes background.mode
```
- Add `"stored"` (recalibration-from-FITS). Keep `"regenerate"` reserved+raising so
  the seam stays visible. Replace `subtract_background: bool` with
  `background: Background` (a bool can't carry the RTG value / wavelength range).
- `build.py:build_cube` becomes a thin wrapper: map legacy `"default"`→`"pyuvis"`,
  build a `BuildConfig`, and delegate to `CubeBuilder`. The real-data `PyuvisSource`
  isn't built yet, so `build_cube` stays raising `NotImplementedError` for the
  production signature; the working paths are exposed via `CubeBuilder` +
  `SyntheticSource`/`FitsReadbackSource`. Update `__init__.py` exports accordingly.

## Build order

1. `product.py` (`ProductInputs`, move `CubeProduct`)
2. `calibrate.py` (`Background`, `CalModel`, `StoredCalModel`, `Calibrator`; `PyuvisCalModel` stub)
3. `fitsio.py` (`read_product`)
4. `sources.py` (`SyntheticSource`, `FitsReadbackSource`)
5. `builder.py` (`CubeBuilder`)
6. Reconcile `config.py`; refactor `demo.make_synthetic_product` to delegate; rewire `build.py`/`__init__.py`
7. `tests/test_recalibrate.py`

## Verification (new `tests/test_recalibrate.py`, reusing `test_writer.py` patterns)

1. **Round-trip identity**: synthetic→FITS1; `read_product`→`ProductInputs`; rebuild
   with `calibration="stored"`, `background mode="none"`→FITS2. Assert RAW_COUNTS,
   CAL_FACTOR, WAVELENGTH, all geometry arrays, KERNELS, and every primary keyword
   are **bit-identical** FITS1↔FITS2.
2. **Recalibrate changes ONLY the offset** (headline): read FITS1 back, rebuild with
   `Background(mode="rtg", rtg_value=0.001)`. Assert `cube2 − cube1 == −offset ×
   cal_factor[...,None]` within float32 tol, and RAW_COUNTS/CAL_FACTOR/WAVELENGTH/
   geometry/kernels/header all unchanged.
3. **Calibrator units** (no FITS): hand `raw`/`int_time`/`cal_factor` → assert the
   formula per background mode; `spectral_average` masks by `wavelength_range`.
4. **Config**: defaults round-trip; `calibration="regenerate"` raises; `summary()`
   includes background mode.
5. **No-geometry guarantee** (PORT_PLAN §7): assert `calibrate.py`/`builder.py`
   import no SPICE and compute no geometry — it only flows through as opaque arrays.

Run: `cd code/cubegenpy && pip install -e ".[dev]" && make test` (or `pytest`).

## Explicitly deferred (seams left open, not built now)

- `PyuvisSource` (fetch real PDS product + ingest Showalter geometry folder) — blocked on Showalter's format, which doesn't exist yet.
- `SpicaCalModel` / real integration of `pyuvis.calib.steffl`+`greg` and the IDL
  `Get_UVIS_calibration` chain — the calibration-observation extension work. The
  `CalModel` Protocol is the drop-in point. **This is the natural next phase after
  the skeleton lands.**
- Row-wise NaN interpolation (`cg_interpolate_nans2`) — `np.nan_to_num` stands in
  until real FUV data needs it.
