"""Structural tests for the draft UVIS FITS writer.

Builds the network-free synthetic product and asserts that the emitted FITS
file matches Mark Showalter's layout proposal: HDU set, dtypes, shapes,
windowed NY, CAL_FACTOR null, CENTER_* naming, Saturn always present, the
conditional RING_GEOM, and the UTC/DATE formatting rules.
"""

from __future__ import annotations

import numpy as np
import pytest
from astropy.io import fits

from cubegenpy.demo import _DEMO_DIMS as D
from cubegenpy.demo import make_synthetic_product
from cubegenpy.layout import CAL_FACTOR_NULL


def _is(dtype, kind: str, itemsize: int) -> bool:
    """Endianness-agnostic dtype check (FITS stores big-endian on disk)."""
    return dtype.kind == kind and dtype.itemsize == itemsize


@pytest.fixture(scope="module")
def product(tmp_path_factory):
    out = tmp_path_factory.mktemp("uvis")
    paths = make_synthetic_product(out, rings_in_fov=True)
    with fits.open(paths["fits"]) as hdul:
        hdul.info(output=False)
        yield hdul, paths


def test_fits_reopens_cleanly(product):
    hdul, _ = product
    assert len(hdul) >= 8  # ISC-20


def test_primary_is_float32_cube(product):
    hdul, _ = product
    prim = hdul[0]
    assert _is(prim.data.dtype, "f", 4)            # ISC-1
    assert prim.data.shape == (D.NX, D.NY, D.NZ)   # (NX, NY, NZ)


def test_raw_counts_is_int16(product):
    hdul, _ = product
    raw = hdul["RAW_COUNTS"]
    assert _is(raw.data.dtype, "i", 2)             # ISC-2
    assert raw.data.shape == (D.NX, D.NY, D.NZ)


def test_cal_factor_2d_with_null(product):
    hdul, _ = product
    cal = hdul["CAL_FACTOR"]
    assert _is(cal.data.dtype, "f", 4)             # ISC-3
    assert cal.data.shape == (D.NX, D.NY)
    assert not np.isnan(cal.data).any()
    assert (cal.data == CAL_FACTOR_NULL).any()    # ISC-4 (NaN -> -1000)


def test_wavelength_1d_float32(product):
    hdul, _ = product
    wav = hdul["WAVELENGTH"]
    assert _is(wav.data.dtype, "f", 4)             # ISC-5
    assert wav.data.shape == (D.NX,)


def test_geometry_hdus_present(product):
    hdul, _ = product
    names = {h.header.get("EXTNAME") for h in hdul}
    assert {"SC_GEOM", "BODY_GEOM", "GENERAL_GEOM"} <= names  # ISC-6, 7
    assert "RING_GEOM" in names                                # ISC-9 (rings on)


def test_sc_geom_per_body_rows(product):
    hdul, _ = product
    sc = hdul["SC_GEOM"]
    assert sc.data["NAME"].shape[0] == 2          # TITAN + SATURN (ISC-6)
    assert "SATURN" in [n.strip() for n in sc.data["NAME"]]   # ISC-16


def test_center_naming_not_target(product):
    hdul, _ = product
    cols = hdul["SC_GEOM"].columns.names
    assert any(c.startswith("CENTER_") for c in cols)   # ISC-15
    assert not any(c.startswith("TARGET_") for c in cols)


def test_general_geom_time_et_float64(product):
    hdul, _ = product
    time_et = hdul["GENERAL_GEOM"].data["TIME_ET"]
    assert _is(time_et.dtype, "f", 8)              # ISC-8


def test_backplane_tdim_order(product):
    hdul, _ = product
    # FITS TDIM is fastest-first: 5,NY,NZ,NT
    sc = hdul["BODY_GEOM"]
    idx = sc.columns.names.index("LAT_CENTRIC") + 1
    assert sc.header[f"TDIM{idx}"] == f"(5,{D.NY},{D.NZ},{D.NT})"


def test_kernels_ascii_table(product):
    hdul, _ = product
    k = hdul["KERNELS"]
    assert isinstance(k, fits.TableHDU)           # ASCII (ISC-10)
    assert k.columns.names == ["FILENAME", "KERNEL_TYPE"]


def test_primary_header_keywords(product):
    hdul, _ = product
    hdr = hdul[0].header
    for kw in ("PROD_ID", "CHANNEL", "INT_TIME", "IMG_YMIN", "IMG_YMAX"):
        assert kw in hdr                          # ISC-11


def test_window_height(product):
    hdul, _ = product
    hdr = hdul[0].header
    ny = hdr["IMG_YMAX"] - hdr["IMG_YMIN"] + 1
    assert ny == D.NY                             # ISC-14
    assert hdul[0].data.shape[1] == D.NY


def test_utc_formatting(product):
    hdul, _ = product
    hdr = hdul[0].header
    for kw in ("OBS_UTC", "END_UTC"):
        val = hdr[kw]
        assert "+" not in val and not val.endswith("Z")   # ISC-12 no tz
        frac = val.split(".")[-1]
        assert len(frac) <= 3                              # ISC-13 ms only
    assert "." not in hdr["DATE"]                          # DATE no frac secs


def test_label_emitted(product):
    _, paths = product
    assert paths["label"].exists()                # ISC-18
    assert paths["label"].suffix == ".xml"


def test_rings_conditional_off():
    """RING_GEOM absent when rings are not in the FOV (ISC-9)."""
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        paths = make_synthetic_product(d, product_id="EUV_NORINGS",
                                       rings_in_fov=False, write_label=False)
        with fits.open(paths["fits"]) as hdul:
            names = {h.header.get("EXTNAME") for h in hdul}
        assert "RING_GEOM" not in names
