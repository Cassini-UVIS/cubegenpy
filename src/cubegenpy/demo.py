"""Build a tiny synthetic UVIS product so the OO core is runnable now.

No network, no SPICE, no real data: :class:`cubegenpy.sources.SyntheticSource`
fabricates small arrays with the right dtypes and shapes, the
:class:`cubegenpy.calibrate.Calibrator` turns the synthetic raw counts + stored
cal factor into the calibrated cube, and :class:`cubegenpy.builder.CubeBuilder`
writes the FITS product. Useful as documentation of the expected ``geometry``
layout and as the fixture the test suite builds on.

Run directly::

    python -m cubegenpy.demo /tmp/uvis_out
"""

from __future__ import annotations

import sys
from pathlib import Path

from .builder import CubeBuilder
from .config import BuildConfig
from .sources import _DEMO_DIMS, SyntheticSource

__all__ = ["make_synthetic_product", "_DEMO_DIMS"]


def make_synthetic_product(
    out_dir: str | Path,
    product_id: str = "EUV2013_047_09_33_59",
    *,
    rings_in_fov: bool = True,
    write_label: bool = True,
) -> dict[str, Path]:
    """Create one synthetic product and write it to ``out_dir``.

    Returns the written paths (``{"fits": ..., "label": ...}``) for back-compat
    with the writer-era callers and tests. The cube is computed by the
    calibrator from the synthetic raw counts using ``calibration="stored"`` (the
    synthetic source already carries a ``CAL_FACTOR``), so no pyuvis/PDS data is
    needed.
    """
    builder = CubeBuilder(
        SyntheticSource(product_id, rings_in_fov=rings_in_fov),
        config=BuildConfig(calibration="stored", write_pds4_label=write_label),
    )
    product = builder.build(out_dir)

    paths: dict[str, Path] = {"fits": product.fits_path}
    if product.label_path is not None:
        paths["label"] = product.label_path
    return paths


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "."
    written = make_synthetic_product(target)
    for kind, path in written.items():
        print(f"{kind}: {path}")
