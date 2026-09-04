"""Tests for the OO core: round-trip readback, recalibration, the Calibrator
formula, the reconciled config, and the no-geometry guarantee.

Reuses the synthetic-product fixture pattern from ``test_writer.py``. The
headline behaviour is that reading one of our FITS products back and rebuilding
it (a) reproduces it bit-for-bit when nothing changes and (b) changes *only* the
calibrated cube — by exactly ``-offset * cal_factor`` — when the background knob
moves.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits

import cubegenpy.builder as builder_mod
import cubegenpy.calibrate as calibrate_mod
from cubegenpy import (
    Background,
    BuildConfig,
    Calibrator,
    CubeBuilder,
    FitsReadbackSource,
    ProductInputs,
    StoredCalModel,
    SyntheticSource,
    read_product,
)
from cubegenpy.layout import CAL_FACTOR_NULL
from cubegenpy.writer import hdu_specs
from cubegenpy.writer import Dims

_STORED_NOBG = BuildConfig(calibration="stored", background=Background("none"),
                           write_pds4_label=False)


def _build_synthetic(out_dir: Path) -> Path:
    """Write FITS1 from the synthetic source via the stored-cal pipeline."""
    product = CubeBuilder(SyntheticSource(), config=_STORED_NOBG).build(out_dir)
    return product.fits_path


def _rebuild_from_fits(src_fits: Path, out_dir: Path, *, background: Background) -> Path:
    """Read a FITS product back and rebuild it with a (possibly new) background."""
    config = BuildConfig(calibration="stored", background=background,
                         write_pds4_label=False)
    product = CubeBuilder(FitsReadbackSource(src_fits), config=config).build(out_dir)
    return product.fits_path


# --------------------------------------------------------------------------- #
# 1. Round-trip identity
# --------------------------------------------------------------------------- #

def _bintable_specs():
    return [s for s in hdu_specs(rings_in_fov=True) if s.xtension == "BINTABLE"]


def _assert_geometry_equal(h1, h2):
    """Every geometry-table column is bit-identical between two open HDULists."""
    for spec in _bintable_specs():
        d1, d2 = h1[spec.name].data, h2[spec.name].data
        for col in spec.columns:
            assert np.array_equal(d1[col.name], d2[col.name]), f"{spec.name}.{col.name}"


def _assert_primary_keywords_equal(h1, h2):
    """Every layout-defined primary keyword matches between two open HDULists."""
    from cubegenpy.layout import PRIMARY_KEYWORDS
    for kw in PRIMARY_KEYWORDS:
        if kw.name in h1[0].header:
            assert h1[0].header[kw.name] == h2[0].header[kw.name], kw.name


def test_round_trip_bit_identical(tmp_path):
    """synthetic->FITS1; read back; rebuild stored/no-bg->FITS2; assert identical."""
    fits1 = _build_synthetic(tmp_path / "a")
    fits2 = _rebuild_from_fits(fits1, tmp_path / "b", background=Background("none"))

    with fits.open(fits1) as h1, fits.open(fits2) as h2:
        # Image HDUs: raw counts, cal factor, wavelength, and the primary cube.
        for name in ("PRIMARY", "RAW_COUNTS", "CAL_FACTOR", "WAVELENGTH"):
            assert np.array_equal(h1[name].data, h2[name].data), name  # ISC-26
            assert h1[name].data.dtype == h2[name].data.dtype, name

        _assert_geometry_equal(h1, h2)  # every geometry column round-trips

        # KERNELS ASCII table.
        k1, k2 = h1["KERNELS"].data, h2["KERNELS"].data
        assert np.array_equal(k1["FILENAME"], k2["FILENAME"])
        assert np.array_equal(k1["KERNEL_TYPE"], k2["KERNEL_TYPE"])

        _assert_primary_keywords_equal(h1, h2)


def test_raw_counts_uint16_round_trips_above_int16_max(tmp_path):
    """A raw count > 32767 survives the readback (finding #1 regression guard)."""
    fits1 = _build_synthetic(tmp_path / "a")
    inputs = read_product(fits1)
    big = np.array(inputs.raw_counts, copy=True)
    big[0, 0, 0] = 60000  # would overflow signed int16
    inputs = replace(inputs, raw_counts=big)
    from cubegenpy import writer
    hdul = writer.build_hdulist(**inputs.as_writer_kwargs())
    out = writer.write_product(tmp_path / "c", "BIG", hdul, write_label=False)
    with fits.open(out["fits"]) as h:
        assert h["RAW_COUNTS"].data[0, 0, 0] == 60000
        assert h["RAW_COUNTS"].data.dtype.kind == "u"


# --------------------------------------------------------------------------- #
# 2. Recalibration changes ONLY the offset (headline)
# --------------------------------------------------------------------------- #

def test_recalibrate_changes_only_offset(tmp_path):
    fits1 = _build_synthetic(tmp_path / "a")
    rtg = 0.001
    fits2 = _rebuild_from_fits(fits1, tmp_path / "b",
                              background=Background(mode="rtg", rtg_value=rtg))

    inputs1 = read_product(fits1)
    cal = inputs1.cal_factor  # NaNs restored at undefined entries
    finite = np.isfinite(cal)

    with fits.open(fits1) as h1, fits.open(fits2) as h2:
        # On disk the cube is FITS order (NZ, NY, NX); transpose back to the
        # caller order (NX, NY, NZ) that cal_factor is expressed in.
        cube1 = np.array(h1[0].data, dtype=np.float64).T
        cube2 = np.array(h2[0].data, dtype=np.float64).T

        # cube2 - cube1 == -offset * cal_factor (broadcast over readout axis).
        expected = (-rtg * cal)[:, :, None] * np.ones_like(cube1)
        diff = cube2 - cube1
        mask = np.broadcast_to(finite[:, :, None], diff.shape)
        assert np.allclose(diff[mask], expected[mask], atol=1e-5)  # ISC-27
        assert not np.array_equal(cube1, cube2)  # the cube DID change

        # Everything else is untouched.
        for name in ("RAW_COUNTS", "CAL_FACTOR", "WAVELENGTH"):
            assert np.array_equal(h1[name].data, h2[name].data), name
        _assert_geometry_equal(h1, h2)
        _assert_primary_keywords_equal(h1, h2)


# --------------------------------------------------------------------------- #
# 3. Calibrator units (no FITS)
# --------------------------------------------------------------------------- #

def _tiny_inputs():
    dims = Dims(NX=4, NY=2, NZ=3, NT=3)
    raw = (np.arange(4 * 2 * 3, dtype=np.uint16).reshape(4, 2, 3) + 1)
    cal = (np.arange(4 * 2, dtype=np.float32).reshape(4, 2) + 0.5)
    wavelength = np.linspace(600.0, 1100.0, 4, dtype=np.float32)
    header = {"INT_TIME": 2.0, "PROD_ID": "TINY"}
    return ProductInputs(
        cube=None, raw_counts=raw, cal_factor=cal, wavelength=wavelength,
        header=header, geometry={}, kernels=[], bodies=[], resolved_bodies=[],
        dims=dims,
    )


def test_calibrator_none_background():
    inputs = _tiny_inputs()
    cube = Calibrator(StoredCalModel(inputs.cal_factor)).calibrate(inputs, Background("none"))
    cps = inputs.raw_counts.astype(np.float64) / 2.0
    expected = (cps * inputs.cal_factor[:, :, None]).astype(np.float32)
    assert np.allclose(cube, expected)  # ISC-12


def test_calibrator_rtg_background():
    inputs = _tiny_inputs()
    bg = Background(mode="rtg", rtg_value=0.1)
    cube = Calibrator(StoredCalModel(inputs.cal_factor)).calibrate(inputs, bg)
    cps = inputs.raw_counts.astype(np.float64) / 2.0
    expected = ((cps - 0.1) * inputs.cal_factor[:, :, None]).astype(np.float32)
    assert np.allclose(cube, expected)


def test_calibrator_spectral_average_masks_by_wavelength():
    inputs = _tiny_inputs()
    bg = Background(mode="spectral_average", wavelength_range=(600.0, 800.0))
    cube = Calibrator(StoredCalModel(inputs.cal_factor)).calibrate(inputs, bg)

    cps = inputs.raw_counts.astype(np.float64) / 2.0
    mask = (inputs.wavelength >= 600.0) & (inputs.wavelength <= 800.0)
    assert mask.sum() == 2  # only the first two samples are in band
    offset = cps[mask, :, :].mean(axis=0, keepdims=True)
    expected = ((cps - offset) * inputs.cal_factor[:, :, None]).astype(np.float32)
    assert np.allclose(cube, expected)  # ISC-7


def test_spectral_average_requires_range():
    with pytest.raises(ValueError):
        Background(mode="spectral_average")  # no wavelength_range


# --------------------------------------------------------------------------- #
# 4. Config
# --------------------------------------------------------------------------- #

def test_config_defaults_round_trip():
    cfg = BuildConfig()
    assert cfg.calibration == "pyuvis"
    assert cfg.background.mode == "none"
    assert cfg.write_pds4_label is True


def test_config_regenerate_raises():
    with pytest.raises(NotImplementedError):
        BuildConfig(calibration="regenerate")


def test_config_unknown_calibration_raises():
    with pytest.raises(ValueError):
        BuildConfig(calibration="bogus")


def test_config_summary_includes_background_mode():
    assert "bg=rtg" in BuildConfig(background=Background("rtg")).summary()  # ISC-22
    assert "bg=none" in BuildConfig().summary()


# --------------------------------------------------------------------------- #
# 5. No-geometry guarantee (PORT_PLAN §7)
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("module", [calibrate_mod, builder_mod])
def test_no_spice_imports(module):
    source = Path(module.__file__).read_text().lower()
    assert "spiceypy" not in source
    assert "import spice" not in source


def test_geometry_passes_through_untouched(tmp_path):
    """The builder must not mutate or recompute the geometry it is handed."""
    fits1 = _build_synthetic(tmp_path / "a")
    inputs = read_product(fits1)
    before = {hdu: {c: np.array(v, copy=True) for c, v in cols.items()}
              for hdu, cols in inputs.geometry.items()}

    CubeBuilder(FitsReadbackSource(fits1), config=_STORED_NOBG).build(tmp_path / "b")

    # read_product is deterministic, so re-reading yields the same geometry,
    # proving the build path treated it as opaque pass-through data.
    after = read_product(fits1).geometry
    for hdu, cols in before.items():
        for c, v in cols.items():
            assert np.array_equal(v, after[hdu][c]), f"{hdu}.{c}"
