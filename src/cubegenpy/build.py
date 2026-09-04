"""Back-compat functional entry point over the OO core.

The working, runnable paths now live on :class:`cubegenpy.builder.CubeBuilder`
plus a :class:`~cubegenpy.sources.Source`
(:class:`~cubegenpy.sources.SyntheticSource` for synthetic builds,
:class:`~cubegenpy.sources.FitsReadbackSource` for recalibration). This module
keeps the original functional ``build_cube`` signature for the *production*
path — fetch a real PDS product via pyuvis + ingest externally-computed
geometry — which is not wired yet (blocked on the Showalter geometry format).

``CubeProduct`` is re-exported from :mod:`cubegenpy.product`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence

from .config import BuildConfig
from .product import CubeProduct

__all__ = ["build_cube", "CubeProduct"]

# Legacy calibration aliases accepted by the old functional signature.
_LEGACY_CALIBRATION = {"default": "pyuvis"}


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
    """Build a Cassini UVIS PDS4 FITS cube for ``pds_product_id`` (production path).

    Parameters
    ----------
    pds_product_id
        Cassini UVIS PRODUCT_ID, e.g. ``"EUV2013_047_09_33_59"``. The raw
        DAT/LBL pair will be fetched via :mod:`pyuvis` (which delegates to
        :mod:`planetarypy.catalog.fetch_product`).
    geometry
        Externally-computed geometry, keyed by FITS HDU name (``"SC_GEOM"``,
        ``"BODY_GEOM"``, ``"GENERAL_GEOM"``, ``"RING_GEOM"``). Each value maps a
        column name to a ``numpy.ndarray`` shaped per Mark's 2026-02 FITS layout
        proposal.
    spice_kernels
        Filenames of SPICE kernels used to compute ``geometry``; written verbatim
        into the ``KERNELS`` HDU.
    target
        PDS target name, e.g. ``"TITAN"``.
    out_dir
        Output directory. The FITS file is written as ``<pds_product_id>.fits``.
    write_pds4_label
        If ``True`` (default), emit a sibling PDS4 XML label.
    calibration
        Calibration source. ``"default"`` maps to ``"pyuvis"``; see
        :class:`~cubegenpy.config.BuildConfig`.

    Returns
    -------
    CubeProduct
        Paths to the written FITS and (optional) PDS4 label.

    Raises
    ------
    NotImplementedError
        The production ``PyuvisSource`` (fetch real PDS product + ingest the
        Showalter geometry folder) is not built yet. Use
        :class:`cubegenpy.builder.CubeBuilder` with
        :class:`~cubegenpy.sources.SyntheticSource` or
        :class:`~cubegenpy.sources.FitsReadbackSource` for the working paths.
    """
    calibration = _LEGACY_CALIBRATION.get(calibration, calibration)
    # Validate the requested config now (raises on unknown/regenerate) so the
    # error is about the knobs, not the missing source, when that's the problem.
    BuildConfig(calibration=calibration, write_pds4_label=write_pds4_label)

    raise NotImplementedError(
        "build_cube's production path needs PyuvisSource (real PDS fetch + "
        "Showalter geometry ingest), which is blocked on the geometry format. "
        "Use CubeBuilder(SyntheticSource(...)) or "
        "CubeBuilder(FitsReadbackSource(path), config=BuildConfig(calibration="
        "'stored')) for the working build / recalibration paths."
    )
