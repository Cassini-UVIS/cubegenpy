"""Canonical payload passed through the cubegenpy build pipeline.

:class:`ProductInputs` mirrors the keyword arguments of
:func:`cubegenpy.writer.build_hdulist` exactly — it *is* the interchange format
of the OO core. A :class:`~cubegenpy.sources.Source` produces a
``ProductInputs``; the :class:`~cubegenpy.calibrate.Calibrator` fills its
``cube`` field; :meth:`cubegenpy.builder.CubeBuilder.build` splats it back into
``build_hdulist``. Synthetic-build and FITS-readback-recalibrate are then one
pipeline with different front ends.

:class:`CubeProduct` (the build result) lives here too so the data types share a
module and ``build.py`` can stay a thin functional wrapper.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np

from .writer import Dims


@dataclass(frozen=True)
class ProductInputs:
    """Everything :func:`cubegenpy.writer.build_hdulist` needs, as one object.

    Field names and meaning mirror ``build_hdulist`` one-to-one. ``cube`` is the
    only field a :class:`~cubegenpy.sources.Source` may leave as ``None`` — the
    :class:`~cubegenpy.calibrate.Calibrator` computes it from ``raw_counts`` and
    ``cal_factor`` and the builder fills it in via :func:`dataclasses.replace`.

    Array conventions
    -----------------
    These are the contract between this package and ``pyuvis``, and they are
    conventional rather than enforced by any import — which is exactly why they
    are written down here. Everything on this class is in **caller order**; the
    reversal to the proposal's FITS order happens once, in
    :func:`cubegenpy.writer._to_fits_order`, and is undone once, in
    :func:`cubegenpy.fitsio.read_product`.

    ==================  ===========================================================
    ``cube``            ``(NX, NY, NZ)`` float32. NaN marks undefined.
    ``raw_counts``      ``(NX, NY, NZ)`` **uint16**, PDS3 convention: 65535 is the
                        null, not a count. Written to FITS as signed int16 (or
                        int32 when a real value exceeds 32767) with the null
                        recoded to -1 and declared via ``BLANK``.
    ``cal_factor``      ``(NX, NY)`` float32.
    ``wavelength``      ``(NX,)`` float32, **Angstrom** — note ``pyuvis`` returns
                        nm, so the production path must convert.
    geometry cells      ``(nrows, *reversed(tdim))``: a ``5,NY,NZ,NT`` backplane
                        arrives as ``(nrows, NT, NZ, NY, 5)``.
    ==================  ===========================================================

    ``pyuvis`` reads PDS3 qubes with ``reshape(CORE_ITEMS, order="F")``, so its
    arrays are Fortran-ordered with shape ``(NX, NY, NZ)`` — which is what makes
    the writer's transpose a no-copy view and lets the FITS data section
    reproduce the PDS3 byte sequence.
    """

    cube: np.ndarray | None
    raw_counts: np.ndarray
    cal_factor: np.ndarray
    wavelength: np.ndarray
    header: Mapping[str, object]
    geometry: Mapping[str, Mapping[str, object]]
    kernels: Sequence[tuple[str, str]]
    bodies: Sequence[str]
    resolved_bodies: Sequence[str]
    dims: Dims
    rings_in_fov: bool = False
    edge_on: bool = False

    def as_writer_kwargs(self) -> dict:
        """Return the keyword dict to splat into :func:`writer.build_hdulist`."""
        return {
            "cube": self.cube,
            "raw_counts": self.raw_counts,
            "cal_factor": self.cal_factor,
            "wavelength": self.wavelength,
            "header": self.header,
            "geometry": self.geometry,
            "kernels": self.kernels,
            "bodies": self.bodies,
            "resolved_bodies": self.resolved_bodies,
            "dims": self.dims,
            "rings_in_fov": self.rings_in_fov,
            "edge_on": self.edge_on,
        }


@dataclass(frozen=True)
class CubeProduct:
    """Result of a successful build.

    Bundles **what was written** so callers can pass the paths straight into
    archive submission tooling without having to recompute them.
    """

    fits_path: Path
    label_path: Path | None
    product_id: str
