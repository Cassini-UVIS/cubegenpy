"""Read one of *our own* UVIS FITS products back into :class:`ProductInputs`.

This inverts :func:`cubegenpy.writer.build_hdulist`. It is **layout-driven**:
it walks :func:`cubegenpy.writer.hdu_specs` so the reader and writer share a
single source of truth and a read->write round-trip reproduces the file
bit-for-bit. Correctness points (all derived from ``writer.py`` / ``layout.py``):

* Invert the ``CAL_FACTOR`` NULL sentinel (``== -1000.0`` -> ``np.nan``) so a
  re-write reproduces it.
* ``NAME`` columns are identity, not geometry data — extract them into
  ``bodies`` / ``resolved_bodies`` and drop them from each geometry dict (the
  writer re-adds them).
* Infer ``NT`` from a time-series ``TDIM`` (``GENERAL_GEOM.TIME_ET``), never
  hardcode it.
* Geometry cells come back in numpy slowest-first order ``(nrows, NT, NZ, NY, 5)``
  — exactly what ``build_hdulist`` expects, so they pass straight through.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from astropy.io import fits

from . import layout
from .layout import CAL_FACTOR_NULL
from .product import ProductInputs
from . import writer
from .writer import Dims


def read_product(path: str | Path) -> ProductInputs:
    """Read a cubegenpy FITS product into the writer's interchange format."""
    with fits.open(path) as hdul:
        names = {h.header.get("EXTNAME") for h in hdul}
        rings_in_fov = "RING_GEOM" in names
        edge_on = rings_in_fov and (
            "EDGE_ON_RADIUS" in hdul["RING_GEOM"].columns.names
        )

        primary = hdul[0]
        # Undo writer._to_fits_order: files are FITS-order, callers are (NX,NY,NZ).
        cube = np.ascontiguousarray(np.array(primary.data, dtype=np.float32).T)
        header = _read_header(primary.header)

        raw_counts = np.ascontiguousarray(np.array(hdul["RAW_COUNTS"].data).T)

        cal_factor = np.ascontiguousarray(
            np.array(hdul["CAL_FACTOR"].data, dtype=np.float32).T)
        cal_factor[cal_factor == CAL_FACTOR_NULL] = np.nan  # invert NULL sentinel

        wavelength = np.array(hdul["WAVELENGTH"].data, dtype=np.float32)

        nx, ny, nz = cube.shape
        nt = _infer_nt(hdul["GENERAL_GEOM"].data["TIME_ET"], nz)
        dims = Dims(NX=nx, NY=ny, NZ=nz, NT=nt)

        bodies = _names(hdul["SC_GEOM"].data["NAME"])
        resolved_bodies = _names(hdul["BODY_GEOM"].data["NAME"])

        khdu = hdul["KERNELS"].data
        kernels = [
            (str(f).strip(), str(t).strip())
            for f, t in zip(khdu["FILENAME"], khdu["KERNEL_TYPE"])
        ]

        geometry = _read_geometry(hdul, rings_in_fov=rings_in_fov, edge_on=edge_on)

    return ProductInputs(
        cube=cube,
        raw_counts=raw_counts,
        cal_factor=cal_factor,
        wavelength=wavelength,
        header=header,
        geometry=geometry,
        kernels=kernels,
        bodies=bodies,
        resolved_bodies=resolved_bodies,
        dims=dims,
        rings_in_fov=rings_in_fov,
        edge_on=edge_on,
    )


def _read_header(hdr) -> dict:
    """Pull the primary-header keywords the writer knows about, in proposal order."""
    return {kw.name: hdr[kw.name] for kw in writer.primary_keywords() if kw.name in hdr}


def _infer_nt(time_et: np.ndarray, nz: int) -> int:
    """NT from a time-series cell shaped ``(nrows, NT, NZ)`` (numpy slowest-first)."""
    if time_et.ndim != 3 or time_et.shape[-1] != nz:
        raise ValueError(
            f"GENERAL_GEOM.TIME_ET has shape {time_et.shape}; expected (nrows, NT, "
            f"{nz}) so NT can be inferred"
        )
    return int(time_et.shape[-2])


def _names(name_column: np.ndarray) -> list[str]:
    return [str(n).strip() for n in name_column]


def _read_geometry(hdul, *, rings_in_fov: bool, edge_on: bool) -> dict:
    """Rebuild the ``geometry`` mapping by walking the layout specs.

    Every BINTABLE column except ``NAME`` is copied back verbatim; cells already
    carry the numpy slowest-first shape ``build_hdulist`` expects.
    """
    geometry: dict[str, dict] = {}
    for spec in writer.hdu_specs(rings_in_fov=rings_in_fov, edge_on=edge_on):
        if spec.xtension != "BINTABLE":
            continue
        data = hdul[spec.name].data
        geometry[spec.name] = {
            col.name: np.array(data[col.name])
            for col in spec.columns
            if col.name != "NAME"
        }
    return geometry
