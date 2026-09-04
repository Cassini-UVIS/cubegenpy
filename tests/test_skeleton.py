"""Stage-1 skeleton + workbook-driven template.

Covers the two-stage pipeline: a geometry-complete/science-empty product written
by the geometry provider, then filled by calibration without disturbing anything
the provider wrote.
"""

from __future__ import annotations

import numpy as np
import pytest
from astropy.io import fits

from cubegenpy import (
    calibrated_header,
    check_skeleton,
    geometry_contract,
    is_skeleton,
    read_product,
    write_skeleton,
)
from cubegenpy import writer as W
from cubegenpy.layout import PIPESTAT_SKELETON, RAW_COUNTS_NULL
from cubegenpy.writer import Dims

DIMS = Dims(NX=16, NY=4, NZ=3, NT=3)
BODIES = ["SATURN", "TITAN"]
RESOLVED = ["TITAN"]
HEADER = {"PROD_ID": "EUV_TEST", "CHANNEL": "EUV", "TARGET": "TITAN",
          "INT_TIME": 240.0}

# v2 HDU plan (proposal p.2), which the workbook must reproduce.
V2_ORDER = ["PRIMARY", "RAW_COUNTS", "CAL_FACTOR", "BACKGROUND", "SC_GEOM",
            "BODY_GEOM", "GENERAL_GEOM", "RING_GEOM", "KERNELS", "WAVELENGTH"]
V2_TFIELDS = {"SC_GEOM": 25, "BODY_GEOM": 13, "GENERAL_GEOM": 3, "RING_GEOM": 14}


@pytest.fixture
def skeleton(tmp_path):
    geom = {
        "SC_GEOM": {"SUB_SC_LAT_CENTRIC": np.full((2, 3, 3), -12.5, np.float32)},
        "BODY_GEOM": {"LAT_CENTRIC": np.full((1, 3, 3, 4, 5), 42.0, np.float32)},
    }
    return write_skeleton(
        tmp_path, "EUV_TEST", dims=DIMS, header=HEADER, geometry=geom,
        kernels=[("naif0012.tls", "LSK")],
        bodies=BODIES, resolved_bodies=RESOLVED,
    )


# --------------------------------------------------------------------------- #
# The workbook is the source of truth
# --------------------------------------------------------------------------- #

def test_hdu_order_matches_v2():
    assert [s.name for s in W.hdu_specs()] == V2_ORDER


@pytest.mark.parametrize("ext,n", V2_TFIELDS.items())
def test_tfields_match_v2(ext, n):
    spec = next(s for s in W.hdu_specs() if s.name == ext)
    assert len(spec.columns) == n


def test_v2_column_renames_present():
    """The v1 -> v2 column changes actually reached the specs."""
    sc = {c.name for c in next(s for s in W.hdu_specs() if s.name == "SC_GEOM").columns}
    assert {"SUB_SC_LAT_CENTRIC", "SUB_SC_LAT_GRAPHIC", "SUB_SC_LOCAL_TIME"} <= sc
    assert "PHI" not in sc and "SATURN_LOCAL_TIME" not in sc

    body = {c.name for c in next(s for s in W.hdu_specs() if s.name == "BODY_GEOM").columns}
    assert "LOCAL_TIME" in body
    assert not ({"RESOLUTION_FINE", "RESOLUTION_COARSE"} & body)

    ring = {c.name for c in next(s for s in W.hdu_specs() if s.name == "RING_GEOM").columns}
    assert {"RING_AZIMUTH", "SOLAR_ELEVATION", "SC_ELEVATION"} <= ring


def test_wavemin_wavemax_wavestep_are_declared():
    names = {k.name for k in W.primary_keywords()}
    assert {"WAVEMIN", "WAVEMAX", "WAVESTEP", "PIPESTAT"} <= names


# --------------------------------------------------------------------------- #
# Stage 1
# --------------------------------------------------------------------------- #

def test_skeleton_has_full_v2_structure(skeleton):
    with fits.open(skeleton) as hdul:
        assert [h.header.get("EXTNAME") or "PRIMARY" for h in hdul] == V2_ORDER


def test_skeleton_is_marked(skeleton):
    assert is_skeleton(skeleton)
    assert fits.getheader(skeleton, 0)["PIPESTAT"] == PIPESTAT_SKELETON


def test_placeholders_are_self_announcing(skeleton):
    """Never zero: a zero flux is legal and would hide an unfilled product."""
    with fits.open(skeleton) as hdul:
        assert np.all(np.isnan(hdul[0].data))
        assert np.all(hdul["RAW_COUNTS"].data == RAW_COUNTS_NULL)
        assert np.all(np.isnan(hdul["BACKGROUND"].data))


def test_check_skeleton_separates_filled_from_unfilled(skeleton):
    r = check_skeleton(skeleton)
    assert r.is_skeleton
    assert r.science_filled == ()          # nothing science-bearing yet
    assert "SC_GEOM.SUB_SC_LAT_CENTRIC" in r.filled_columns
    assert "BODY_GEOM.LAT_CENTRIC" in r.filled_columns
    assert "SC_GEOM.SUB_SC_LON" in r.unfilled_columns
    assert r.bodies == ("SATURN", "TITAN")
    assert r.resolved_bodies == ("TITAN",)


def test_check_skeleton_reports_dims(skeleton):
    r = check_skeleton(skeleton)
    assert (r.dims.NX, r.dims.NY, r.dims.NZ) == (DIMS.NX, DIMS.NY, DIMS.NZ)


def test_geometry_contract_mentions_every_table_column():
    text = geometry_contract(DIMS)
    for ext, _ in V2_TFIELDS.items():
        assert ext in text
    assert "SUB_SC_LAT_GRAPHIC" in text and "RING_AZIMUTH" in text


# --------------------------------------------------------------------------- #
# Stage 2: filling must not disturb stage 1
# --------------------------------------------------------------------------- #

def test_stage2_preserves_everything_stage1_wrote(skeleton, tmp_path):
    before_hdr = fits.getheader(skeleton, 0).tostring()
    before = {e: fits.getdata(skeleton, e).copy()
              for e in ("SC_GEOM", "BODY_GEOM", "GENERAL_GEOM", "KERNELS")}

    inp = read_product(skeleton)
    cube = np.random.default_rng(0).random((DIMS.NX, DIMS.NY, DIMS.NZ)).astype(np.float32)
    out = tmp_path / "stage2.fits"
    kwargs = inp.as_writer_kwargs() | {
        "cube": cube, "header": calibrated_header(inp.header),
    }
    W.build_hdulist(**kwargs).writeto(out, overwrite=True)

    # Every stage-1 keyword survives except the status, which must be promoted.
    h1, h2 = fits.getheader(skeleton, 0), fits.getheader(out, 0)
    assert h2["PIPESTAT"] == "CALIBRATED"
    assert not is_skeleton(out)
    for k in h1:
        if k in ("PIPESTAT", "COMMENT", ""):
            continue
        assert h2[k] == h1[k], k
    assert before_hdr
    for ext, arr in before.items():
        got = fits.getdata(out, ext)
        for col in arr.dtype.names:
            assert np.array_equal(arr[col], got[col]), f"{ext}.{col}"
    assert not np.all(np.isnan(fits.getdata(out, 0)))
