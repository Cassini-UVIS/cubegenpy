# Port plan: IDL cube_generator → cubegenpy

This document tracks every IDL `.pro` file in
`~/Dropbox/Documents/01_projects/uvis_pdart/code/tools/cube_generator/`
and where its functionality lands in the Python redesign — or whether
it's deliberately dropped.

The Python redesign is **not** a 1:1 port. It is a smaller-scoped tool
that:

- Reads PDS3 raw data via [`pyuvis`](https://github.com/Cassini-UVIS/pyuvis).
- Accepts geometry as input (computed upstream).
- Writes a single FITS-PDS4 output (Mark's 2026-02 layout) + sibling XML label.
- Has no GUI.

## Source-of-data delegation

| Concern | IDL home | Python home |
|---|---|---|
| Read PDS3 DAT + LBL | `cg_feuv_reader.pro`, `open_pds_file.pro` | `pyuvis.io.PDSReader`, `pyuvis.io.UVPDS` |
| Wavelength table | `uvis_wl.sav` | `pyuvis.io.UVPDS.wavelengths` |
| HSP sensitivity | `cg_get_fuv_red_patch.pro` | `pyuvis.hsp_sensitivity` |
| Flat-fielding (AJS) | `cg_read_ajs_flf.pro` + `cg_bin_win_flatfield.pro` | `pyuvis.calib.steffl` |
| Flat-fielding (Greg/Spica) | `cg_read_spica_ff_data.pro` | `pyuvis.calib.greg` |
| SCLK conversion | `cg_convert_sclk.pro` | `spiceypy.sct2e` (called upstream) |
| Geometry / Geometer engine | `cg_geometer_engine.pro` (external) | **External — provided as input** |
| SPICE kernel mgmt | `cassini_spice_kernel_list_v2.pro` (external) | **External — kernel list passed in** |
| File fetch via PDS | `cg_get_filename.pro`, `get_file_location.pro` | `planetarypy.catalog.fetch_product` (via pyuvis) |

## IDL → Python file-level mapping

| IDL file | LOC | Status | Python target |
|---|---:|---|---|
| `cube_generator.pro` | 1107 | **DROPPED** | IDL widget/GUI; not ported |
| `cube_single.pro` | 1046 | **PORT** | `cubegenpy.build.build_cube` (the algorithm core) |
| `cube_multi.pro` | 1009 | **DEFERRED** | Multi-window batching → phase 2; A/B suffix scheme per meeting notes |
| `cube_control.pro` | 308 | **DROPPED** | GUI control flow |
| `cg_convert_sclk.pro` | 338 | **REPLACED** | `spiceypy.sct2e` upstream |
| `cg_feuv_reader.pro` | 277 | **REPLACED** | `pyuvis.io.PDSReader` |
| `cg_write_save_new.pro` | 255 | **DROPPED** | IDL .sav output replaced by FITS |
| `cg_write_save_new_multi.pro` | 255 | **DROPPED** | Same |
| `cg_create_pass_struct.pro` | 203 | **PORT** | `cubegenpy.config.BuildConfig` (dataclass) |
| `cg_valstr.pro` | 165 | **PORT** | `cubegenpy.utils.validate_string` (small helper) |
| `cg_init_structures_dp.pro` | 137 | **PORT** | Replaced by FITS HDU builders in `cubegenpy.fits_writer` |
| `cg_nogui.pro` | 110 | **REPLACED** | `cubegenpy.build.build_cube` is the no-GUI entry point |
| `cg_settings_print.pro` | 94 | **PORT** | `cubegenpy.config.BuildConfig.__repr__` |
| `cg_int1.pro` | 76 | **PORT** | Inlined into `cubegenpy.utils` if still needed |
| `open_pds_file.pro` | 66 | **REPLACED** | `pyuvis.io.PDSReader` |
| `cg_write_binary.pro` | <100 | **DROPPED** | Raw binary output replaced by FITS |
| `cg_get_fuv_red_patch.pro` | <100 | **REPLACED** | `pyuvis.hsp_sensitivity` |
| `cg_read_ajs_flf.pro` | <100 | **REPLACED** | `pyuvis.calib.steffl` |
| `cg_bin_win_flatfield.pro` | <100 | **REPLACED** | `pyuvis.calib.steffl` |
| `cg_read_spica_ff_data.pro` | <100 | **REPLACED** | `pyuvis.calib.greg` |
| `cg_interpolate_nans.pro` | <100 | **PORT** | `cubegenpy.utils.interpolate_nans` (small) |
| `cg_interpolate_nans2.pro` | <100 | **PORT** | Same — pick the better of the two |
| `cg_shrink.pro` | <100 | **PORT** | `cubegenpy.utils.shrink` |
| `cg_enlarg.pro` | <100 | **PORT** | `cubegenpy.utils.enlarge` |
| `cg_attget.pro` | <100 | **PORT** | `cubegenpy.utils.attr_get` |
| `cg_xerox.pro` | <100 | **PORT** | `cubegenpy.utils.xerox` |
| `cg_getstar.pro` | <100 | **DEFERRED** | Star observation special case → phase 2 |
| `cg_get_uvis_modifier.pro` | <100 | **PORT** | Inline as a small helper if needed |
| `cube_generator_tutorial.README` | doc | reference | Preserved as `refs/cube_generator_tutorial.README` (TODO: copy in) |
| `UVISImageCube*.doc` | doc | reference | Original IDL cube format spec — superseded by the new FITS layout |
| `T-0.txt`, `path_finder_*.txt` | 2 files | **DROPPED** | Local-machine-specific paths; gone |
| `GeometerStars.txt`, `cg_defaults.txt` | 2 files | reference | Preserved as `refs/` if values are still needed |
| `uvis_wl.sav`, `Spica_FF_data.sav` | 2 files | **REPLACED** | Wavelengths from pyuvis; flatfield data lives with calibration code |

## Python module layout (planned)

```
src/cubegenpy/
  __init__.py          — re-exports build_cube
  build.py             — public API: build_cube() entry point
  config.py            — BuildConfig dataclass (replaces pass struct)
  fits_writer.py       — assemble the 9 HDUs per Mark's spec
  pds4_label.py        — emit PDS4 XML label alongside the FITS
  geometry.py          — validate / normalise the input geometry dict
  utils.py             — small helpers ported from cg_*
```

## Phase 1 (this scaffolding)

- [x] Project skeleton (pyproject.toml, src layout, README, LICENSE, CHANGELOG)
- [x] Public API stub (`build_cube` raising NotImplementedError)
- [x] PORT_PLAN.md (this file)
- [ ] Initial git commit + standalone repo

## Phase 2 (next session)

- [ ] `BuildConfig` dataclass (port of `cg_create_pass_struct`)
- [ ] FITS HDU builders for the 9 HDUs (Mark's layout)
- [ ] PDS4 label generator (XML matching the FITS structure)
- [ ] Geometry input validation (shape/key checks against Mark's table specs)
- [ ] Single-product `build_cube` end-to-end on a default Titan EUV file
- [ ] CI workflow + smoke test
- [ ] Quarto docs site stub

## Phase 3 (future)

- [ ] Multi-window observations: A/B suffixed sibling files (~0.005% of products per meeting notes)
- [ ] Background-subtraction HDU
- [ ] Geometry input format spec (when Mark's actual files arrive — likely a separate FITS)
- [ ] Star observation special case (`cg_getstar`)
- [ ] Validate generated PDS4 labels against the official schema
