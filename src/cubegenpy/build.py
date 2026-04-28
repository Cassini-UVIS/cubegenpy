"""Public API for assembling a Cassini UVIS observation into a PDS4 FITS product.

This module's surface is intentionally small. Geometry is **not** computed
here — it is provided as input by the upstream geometry pipeline (Mark's
backplanes). cubegenpy's responsibility is to combine raw + calibrated UVIS
data with that geometry into a single FITS file laid out per Mark's
2026-02 proposal, and to emit a sibling PDS4 XML label.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


@dataclass(frozen=True)
class CubeProduct:
    """Result of a successful :func:`build_cube` call.

    Bundles **what was written** so callers can pass the paths straight
    into archive submission tooling without having to recompute them.
    """

    fits_path: Path
    label_path: Path | None
    product_id: str


def build_cube(
    pds_product_id: str,
    geometry: Mapping[str, Mapping[str, object]],
    spice_kernels: Sequence[str],
    target: str,
    out_dir: str | Path,
    *,
    write_pds4_label: bool = True,
    calibration: str = "default",
) -> CubeProduct:
    """Build a Cassini UVIS PDS4 FITS cube for ``pds_product_id``.

    Parameters
    ----------
    pds_product_id
        Cassini UVIS PRODUCT_ID, e.g. ``"EUV2013_047_09_33_59"``. The raw
        DAT/LBL pair will be fetched via :mod:`pyuvis` (which delegates
        to :mod:`planetarypy.catalog.fetch_product`).
    geometry
        Externally-computed geometry, keyed by FITS HDU name. Expected
        keys: ``"SC_GEOM"``, ``"BODY_GEOM"``, ``"GENERAL_GEOM"``,
        ``"RING_GEOM"``. Each value is a mapping of column name to
        ``numpy.ndarray`` shaped per Mark's 2026-02 FITS layout
        proposal (see ``refs/FITS-layout-proposal-MRS-2025-02-03.pdf``).
    spice_kernels
        Filenames of SPICE kernels that were used to compute ``geometry``.
        Will be written verbatim into the ``KERNELS`` ASCII-table HDU.
    target
        PDS target name, e.g. ``"TITAN"``, ``"SATURN"``, ``"ENCELADUS"``.
    out_dir
        Output directory. The FITS file is written as
        ``<pds_product_id>.fits`` and the label as
        ``<pds_product_id>.xml``.
    write_pds4_label
        If ``True`` (default), emit a sibling PDS4 XML label.
    calibration
        Which calibration pipeline to apply when building the calibrated
        cube. ``"default"`` uses the current pyuvis recommended path
        (Steffl row2row + Greg flatfield). Pass ``"none"`` to skip and
        fill the primary HDU with the raw counts copy.

    Returns
    -------
    CubeProduct
        Paths to the written FITS and (optional) PDS4 label.

    Raises
    ------
    NotImplementedError
        Until the algorithm port lands. See ``PORT_PLAN.md``.
    """
    raise NotImplementedError(
        "cubegenpy is currently scaffolding only — see PORT_PLAN.md "
        "for the implementation roadmap."
    )
