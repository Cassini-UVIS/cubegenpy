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
        # Placeholder 65535 is written as the proposal's integer null (-1);
        # BLANK makes astropy surface it as NaN on read.
        raw = hdul["RAW_COUNTS"]
        assert raw.header["BLANK"] == -1
        assert np.all(np.isnan(raw.data))
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


# --------------------------------------------------------------------------- #
# Extension-header keywords come from the workbook too
# --------------------------------------------------------------------------- #

def test_extension_keywords_are_workbook_declared(skeleton):
    """BLANK/RAWWIDEN/BUNIT are declared in the hdu_keywords sheet, not hardcoded."""
    from cubegenpy import load_template

    t = load_template()
    declared = {(k.extname, k.name) for k in
                (*t.hdu_keywords("RAW_COUNTS"), *t.hdu_keywords("WAVELENGTH"),
                 *t.hdu_keywords("BACKGROUND"))}
    assert {("RAW_COUNTS", "BLANK"), ("RAW_COUNTS", "RAWWIDEN"),
            ("WAVELENGTH", "BUNIT"), ("BACKGROUND", "BUNIT")} <= declared

    with fits.open(skeleton) as hdul:
        assert hdul["RAW_COUNTS"].header["BLANK"] == -1
        assert hdul["RAW_COUNTS"].header["RAWWIDEN"] is False
        # BUNIT, not UNIT: the FITS-reserved spelling (see the plan, C.9 #1).
        assert hdul["WAVELENGTH"].header["BUNIT"] == "Angstrom"
        assert "UNIT" not in hdul["WAVELENGTH"].header
        assert hdul["BACKGROUND"].header["BUNIT"] == "count/s"


# --------------------------------------------------------------------------- #
# NT policy
# --------------------------------------------------------------------------- #

def test_default_policy_honours_the_v2_floor():
    from cubegenpy import SubsamplingPolicy

    p = SubsamplingPolicy()
    assert p.recommend(smear_pixels=0.0) == 3      # no smear -> begin/middle/end
    assert p.recommend(smear_pixels=1.5) == 3      # still the floor
    assert p.recommend(smear_pixels=6.2) == 8      # ceil(6.2/1)+1 fenceposts
    assert p.recommend(smear_pixels=1e6) == 33     # clamped at the ceiling


def test_policy_is_tunable():
    from cubegenpy import SubsamplingPolicy

    fine = SubsamplingPolicy(pixels_per_subsample=0.5, maximum=65)
    assert fine.recommend(smear_pixels=6.2) == 14
    coarse = SubsamplingPolicy(pixels_per_subsample=4.0)
    assert coarse.recommend(smear_pixels=6.2) == 3


def test_policy_refuses_to_go_below_the_proposal_floor():
    from cubegenpy import NTOutOfRange, SubsamplingPolicy

    with pytest.raises(NTOutOfRange, match="floor"):
        SubsamplingPolicy(minimum=2)
    with pytest.raises(NTOutOfRange, match="floor"):
        SubsamplingPolicy().validate(2)


def test_smear_helper():
    from cubegenpy import smear_pixels

    # 0.01 deg/s for 240 s at 0.25 deg/pixel -> 9.6 pixels
    assert smear_pixels(0.01, 240.0, 0.25) == pytest.approx(9.6)


def test_skeleton_records_nt_and_its_rule(tmp_path):
    from cubegenpy import SubsamplingPolicy

    policy = SubsamplingPolicy(pixels_per_subsample=0.5, maximum=65)
    nt = policy.recommend(smear_pixels=6.2)
    dims = Dims(NX=8, NY=4, NZ=2, NT=nt)
    path = write_skeleton(tmp_path, "NT_TEST", dims=dims, header=HEADER,
                          subsampling=policy, bodies=["SATURN"], resolved_bodies=[])
    hdr = fits.getheader(path, 0)
    assert "0.5px/sub" in hdr["NT_RULE"]
    # NT itself is not a keyword -- it is read back from the backplane TDIM,
    # which is the only place it is stated.
    assert "NSUBSAMP" not in hdr
    assert check_skeleton(path).dims.NT == nt == 14


def test_skeleton_rejects_nt_outside_the_policy(tmp_path):
    from cubegenpy import NTOutOfRange

    with pytest.raises(NTOutOfRange):
        write_skeleton(tmp_path, "BAD", dims=Dims(NX=8, NY=4, NZ=2, NT=2),
                       header=HEADER, bodies=["SATURN"], resolved_bodies=[])


def test_null_is_minus_one_in_both_integer_widths():
    """The PDS3 null (65535) must become -1 whether or not the product widens.

    Regression guard: np.where(is_null, -1, uint16_array) raises OverflowError on
    numpy >= 2.5 and silently wraps on older numpy -- where the wrap happens to
    cancel for int16 but leaves 65535 in the int32 branch. Local tests passed
    while CI failed, so this asserts the value rather than the absence of a crash.
    """
    import warnings

    from cubegenpy.layout import RAW_COUNTS_NULL
    from cubegenpy.writer import _raw_counts_hdu

    for peak, expected_bitpix in [(1200, 16), (60000, 32)]:
        arr = np.full((2, 2, 2), 1200, dtype=np.uint16)
        arr[0, 0, 0] = RAW_COUNTS_NULL
        arr[1, 1, 1] = peak
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            hdu = _raw_counts_hdu(arr)
        assert hdu.header["BITPIX"] == expected_bitpix
        assert hdu.header["BLANK"] == -1
        # the null cell, and only it, carries -1
        assert (hdu.data == -1).sum() == 1
        assert hdu.data.max() == peak
