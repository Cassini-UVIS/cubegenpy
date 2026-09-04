"""Front ends that produce a :class:`ProductInputs` for the builder.

A :class:`Source` is the only thing that differs between the two pipelines the
OO core supports:

* :class:`SyntheticSource` — fabricate small, network-free arrays (the old
  ``demo.make_synthetic_product`` body) for exercising the writer end-to-end. It
  leaves ``cube=None``; the :class:`~cubegenpy.calibrate.Calibrator` computes the
  cube from the (synthetic) raw counts and cal factor, which is more honest than
  the old fabricated-random cube.
* :class:`FitsReadbackSource` — read one of our own FITS products back in (for
  recalibration), delegating to :func:`cubegenpy.fitsio.read_product`.

The real-data ``PyuvisSource`` (fetch a PDS product + ingest the Showalter
geometry folder) is a deliberate future seam — blocked on the geometry format,
not built here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np

from . import layout
from .fitsio import read_product
from .product import ProductInputs
from .writer import Dims

# Tiny dimensions — enough to exercise every axis cheaply.
_DEMO_DIMS = Dims(NX=16, NY=8, NZ=4, NT=3)


@runtime_checkable
class Source(Protocol):
    """Produces the canonical :class:`ProductInputs` payload."""

    def load(self) -> ProductInputs:
        ...


def _backplane(dims: Dims, nrows: int, fill: float = 0.0) -> np.ndarray:
    """Array shaped (nrows, NT, NZ, NY, 5) -> FITS TDIM 5,NY,NZ,NT."""
    cell = dims.cell_shape_numpy(("5", "NY", "NZ", "NT"))
    return np.full((nrows, *cell), fill, dtype=np.float32)


def _timeseries(dims: Dims, nrows: int, fill: float = 0.0) -> np.ndarray:
    """Array shaped (nrows, NT, NZ) -> FITS TDIM NZ,NT."""
    cell = dims.cell_shape_numpy(("NZ", "NT"))
    return np.full((nrows, *cell), fill, dtype=np.float32)


class SyntheticSource:
    """Fabricate a tiny, deterministic UVIS product (no network, no SPICE).

    Builds raw counts (``uint16``), a 2-D cal factor with one NULL entry, a
    wavelength axis, primary-header keywords, and zero-filled geometry tables.
    ``cube`` is left ``None`` for the calibrator to fill.
    """

    def __init__(
        self,
        product_id: str = "EUV2013_047_09_33_59",
        *,
        rings_in_fov: bool = True,
        dims: Dims = _DEMO_DIMS,
    ) -> None:
        self.product_id = product_id
        self.rings_in_fov = rings_in_fov
        self.dims = dims

    def load(self) -> ProductInputs:
        dims = self.dims
        product_id = self.product_id
        rng = np.random.default_rng(0)

        # PDS3 raw counts are unsigned 16-bit (0-65535), which is the caller-side
        # convention ProductInputs documents. The writer encodes them as signed
        # on disk; fitsio inverts that, so a readback still round-trips.
        raw = (rng.random((dims.NX, dims.NY, dims.NZ)) * 1000).astype(np.uint16)

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

        # Spec-driven so the synthetic product tracks whatever the
        # data-definition workbook says, rather than a second hardcoded copy of
        # the column inventory that can drift from it.
        from . import writer as _writer

        _rows = {"per_body": len(bodies), "per_resolved_body": len(resolved)}
        geometry: dict[str, dict[str, np.ndarray]] = {}
        for spec in _writer.hdu_specs(rings_in_fov=True):
            if spec.xtension != "BINTABLE":
                continue
            nrows = _rows.get(spec.row_mode, 1)
            cols: dict[str, np.ndarray] = {}
            for col in spec.columns:
                if col.name == "NAME" or not col.tdim:
                    continue
                if col.kind == "float64":
                    cols[col.name] = _timeseries(dims, nrows).astype(np.float64)
                elif col.kind == "float32":
                    cols[col.name] = (_backplane(dims, nrows)
                                      if len(col.tdim) == 4
                                      else _timeseries(dims, nrows))
            geometry[spec.name] = cols

        kernels = [
            ("naif0012.tls", "LSK"),
            ("cpck14Oct2011.tpc", "PCK"),
            ("130321R_SCPSE_13038_13063.bsp", "SPK"),
        ]

        return ProductInputs(
            cube=None,
            raw_counts=raw,
            cal_factor=cal,
            wavelength=wavelength,
            header=header,
            geometry=geometry,
            kernels=kernels,
            bodies=bodies,
            resolved_bodies=resolved,
            dims=dims,
            rings_in_fov=self.rings_in_fov,
        )


class FitsReadbackSource:
    """Load a previously-written cubegenpy FITS product for recalibration."""

    def __init__(self, fits_path: str | Path) -> None:
        self.fits_path = Path(fits_path)

    def load(self) -> ProductInputs:
        return read_product(self.fits_path)
