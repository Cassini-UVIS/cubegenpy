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
