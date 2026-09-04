"""The configurable build orchestrator tying the OO core together.

:class:`CubeBuilder` is the public API: configure it with a
:class:`~cubegenpy.sources.Source` (and optionally a :class:`BuildConfig` and an
explicit :class:`~cubegenpy.calibrate.Calibrator`), then call :meth:`build`.

``build()`` is the single pipeline both front ends share::

    inputs = source.load()
    cube   = calibrator.calibrate(inputs, config.background)
    inputs = replace(inputs, cube=cube)
    writer.write_product(out_dir, ...)

The calibrator's :class:`~cubegenpy.calibrate.CalModel` is chosen from
``config.calibration`` unless one is passed in explicitly. For
``calibration="stored"`` (recalibration) the model is built *inside* ``build()``
from ``inputs.cal_factor``, which only exists after ``source.load()``.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from . import writer
from .calibrate import Calibrator, PyuvisCalModel, StoredCalModel, UnitCalModel
from .config import DEFAULT_CONFIG, BuildConfig
from .product import CubeProduct, ProductInputs
from .sources import Source


class CubeBuilder:
    """Configure -> ``.build(out_dir)`` -> :class:`CubeProduct`."""

    def __init__(
        self,
        source: Source,
        *,
        config: BuildConfig = DEFAULT_CONFIG,
        calibrator: Calibrator | None = None,
    ) -> None:
        self.source = source
        self.config = config
        self.calibrator = calibrator

    def build(self, out_dir: str | Path) -> CubeProduct:
        """Load inputs, calibrate, and write the FITS product (+ optional label)."""
        inputs = self.source.load()
        calibrator = self.calibrator or self._calibrator_for(inputs)

        cube = calibrator.calibrate(inputs, self.config.background)
        inputs = replace(inputs, cube=cube)

        hdulist = writer.build_hdulist(**inputs.as_writer_kwargs())
        product_id = str(inputs.header["PROD_ID"])
        paths = writer.write_product(
            out_dir, product_id, hdulist, write_label=self.config.write_pds4_label
        )
        return CubeProduct(paths["fits"], paths.get("label"), product_id)

    def _calibrator_for(self, inputs: ProductInputs) -> Calibrator:
        """Pick the :class:`Calibrator` implied by ``config.calibration``."""
        source = self.config.calibration
        if source == "stored":
            model = StoredCalModel(inputs.cal_factor)  # recalibration: reuse verbatim
        elif source == "pyuvis":
            model = PyuvisCalModel()
        elif source == "none":
            model = UnitCalModel()  # debug passthrough: primary holds counts/sec
        else:
            # "regenerate" is rejected in BuildConfig.__post_init__; defensive guard.
            raise NotImplementedError(f"no calibrator for calibration={source!r}")
        return Calibrator(model)
