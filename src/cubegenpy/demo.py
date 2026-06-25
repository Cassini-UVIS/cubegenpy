"""Build a tiny synthetic UVIS product so the draft writer is runnable now.

No network, no SPICE, no real data: it fabricates small arrays with the right
dtypes and shapes and runs them through :func:`cubegenpy.writer.build_hdulist`.
Useful as documentation of the expected ``geometry`` mapping layout and as the
fixture the test suite builds on.

Run directly::

    python -m cubegenpy.demo /tmp/uvis_out
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from . import layout
from .writer import Dims, build_hdulist, write_product

# Tiny dimensions — enough to exercise every axis cheaply.
_DEMO_DIMS = Dims(NX=16, NY=8, NZ=4, NT=3)


def _backplane(dims: Dims, nrows: int, fill: float = 0.0) -> np.ndarray:
    """Array shaped (nrows, NT, NZ, NY, 5) -> FITS TDIM 5,NY,NZ,NT."""
    cell = dims.cell_shape_numpy(("5", "NY", "NZ", "NT"))
    return np.full((nrows, *cell), fill, dtype=np.float32)


def _timeseries(dims: Dims, nrows: int, fill: float = 0.0) -> np.ndarray:
    """Array shaped (nrows, NT, NZ) -> FITS TDIM NZ,NT."""
    cell = dims.cell_shape_numpy(("NZ", "NT"))
    return np.full((nrows, *cell), fill, dtype=np.float32)


def make_synthetic_product(
    out_dir: str | Path,
    product_id: str = "EUV2013_047_09_33_59",
    *,
    rings_in_fov: bool = True,
    write_label: bool = True,
) -> dict[str, Path]:
    """Create one synthetic product and write it to ``out_dir``."""
    dims = _DEMO_DIMS
    rng = np.random.default_rng(0)

    cube = rng.random((dims.NX, dims.NY, dims.NZ), dtype=np.float32)
    raw = (rng.random((dims.NX, dims.NY, dims.NZ)) * 1000).astype(np.int16)

    cal = rng.random((dims.NX, dims.NY)).astype(np.float32)
    cal[0, 0] = np.nan  # exercise the CAL_FACTOR null sentinel (-> -1000)

    wavelength = np.linspace(560.0, 1180.0, dims.NX, dtype=np.float32)

    bodies = ["TITAN", "SATURN"]
    resolved = ["TITAN"]

    # IMG_Y bounds chosen so window height == NY (proposal: windowed-only).
    img_ymin, img_ymax = 15, 15 + dims.NY - 1
    header = {
        "FILENAME": f"{product_id}.fits",
        "PROD_ID": product_id,
        "DATE": "2026-06-18T16:40:43.123456",      # -> seconds only
        "MISSION": "Cassini",
        "INSTRUME": "UVIS",
        "VERSION": 1.0,
        "OBS_ID": "UVIS_181TI_MIDIRTMAP001_CIRS",
        "MPHASE": "Solstice",
        "TARGET": "TITAN",
        "ORBNUM": 181,
        "OBS_ET": 414279307.7041518,
        "END_ET": 414287227.7041518,
        "OBS_UTC": "2013-02-16T09:34:00.519123+00:00",  # -> no tz, ms only
        "END_UTC": "2013-02-16T11:46:00.519123Z",       # -> no tz, ms only
        "OBS_SCLK": "1/1739472000.000",
        "END_SCLK": "1/1739479920.000",
        "CHANNEL": "EUV",
        "IMG_XMIN": 0,
        "IMG_XMAX": dims.NX - 1,
        "IMG_YMIN": img_ymin,
        "IMG_YMAX": img_ymax,
        "IMG_XBIN": 1,
        "IMG_YBIN": 1,
        "INT_TIME": 240.0,
        "SLITANGL": 123.456,
        "UNIT": "kR/Angstrom",
    }

    geometry = {
        "SC_GEOM": {
            col.name: _timeseries(dims, len(bodies))
            for col in layout.SC_GEOM_COLUMNS
            if col.kind == "float32" and col.tdim
        },
        "BODY_GEOM": {
            col.name: _backplane(dims, len(resolved))
            for col in layout.BODY_GEOM_COLUMNS
            if col.kind == "float32"
        },
        "GENERAL_GEOM": {
            "RA": _backplane(dims, 1),
            "DEC": _backplane(dims, 1),
            "TIME_ET": _timeseries(dims, 1).astype(np.float64),
        },
        "RING_GEOM": {
            col.name: _backplane(dims, 1)
            for col in layout.RING_GEOM_COLUMNS
            if col.kind == "float32"
        },
    }

    kernels = [
        ("naif0012.tls", "LSK"),
        ("cpck14Oct2011.tpc", "PCK"),
        ("130321R_SCPSE_13038_13063.bsp", "SPK"),
    ]

    hdulist = build_hdulist(
        cube=cube,
        raw_counts=raw,
        cal_factor=cal,
        wavelength=wavelength,
        header=header,
        geometry=geometry,
        kernels=kernels,
        bodies=bodies,
        resolved_bodies=resolved,
        dims=dims,
        rings_in_fov=rings_in_fov,
    )
    return write_product(out_dir, product_id, hdulist, write_label=write_label)


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "."
    written = make_synthetic_product(target)
    for kind, path in written.items():
        print(f"{kind}: {path}")
