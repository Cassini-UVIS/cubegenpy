"""Build configuration for cubegenpy — the Python successor to the IDL ``pass`` struct.

The IDL ``cube_generator`` threaded a large ``pass`` settings structure (built in
``cg_create_pass_struct.pro``) through the whole pipeline: calibration choice,
flatfield selector, background-subtraction flags, output format, etc. Most of
those fields are obsolete here — geometry is external, the GUI is gone, and the
legacy ``.sav``/ENVI/binary writers are replaced by the FITS writer. This frozen
dataclass keeps only the knobs that still have meaning for the FITS pipeline.

See ``PORT_PLAN.md`` §4 and ``Plans/so-the-basic-guide-twinkly-ritchie.md`` for
the calibration-source and background decisions this encodes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .calibrate import Background

CalibrationSource = Literal["pyuvis", "stored", "regenerate", "none"]


@dataclass(frozen=True)
class BuildConfig:
    """Options controlling how a UVIS observation is turned into a FITS product.

    Attributes
    ----------
    calibration
        Where the calibrated cube + ``CAL_FACTOR`` come from:

        * ``"pyuvis"`` (default) — derive the cal factor from the archived PDS
          product via :mod:`pyuvis` (counts x PDS cal matrix -> kR). Thin glue,
          modern path; not wired yet (blocked on real-data ingest).
        * ``"stored"`` — recalibration: reuse the ``CAL_FACTOR`` read back from an
          existing FITS verbatim and only re-apply the background offset. The
          working path for :class:`~cubegenpy.sources.FitsReadbackSource`.
        * ``"regenerate"`` — reserved seam for the ported IDL
          ``Get_UVIS_calibration`` ("Ultimate" Greg Holsclaw time-varying cal) /
          :class:`~cubegenpy.calibrate.SpicaCalModel`. Raises until implemented.
        * ``"none"`` — debug passthrough: fill the primary HDU with counts/sec
          (unit cal factor); the real ``CAL_FACTOR`` HDU is still written.
    background
        How much background to subtract before calibration, as a
        :class:`~cubegenpy.calibrate.Background` value (not a bool, so it can carry
        the RTG dark rate or a spectral-average band). Defaults to ``mode="none"``.
    write_pds4_label
        Emit the sibling draft PDS4 XML label.
    fits_version
        Value written to the primary-header ``VERSION`` keyword.
    """

    calibration: CalibrationSource = "pyuvis"
    background: Background = field(default_factory=Background)
    write_pds4_label: bool = True
    fits_version: float = 1.0

    def __post_init__(self) -> None:
        if self.calibration not in ("pyuvis", "stored", "regenerate", "none"):
            raise ValueError(f"unknown calibration source: {self.calibration!r}")
        if self.calibration == "regenerate":
            raise NotImplementedError(
                "calibration='regenerate' (ported Get_UVIS_calibration / "
                "SpicaCalModel seam) is not implemented yet — see PORT_PLAN.md §4. "
                "Use 'pyuvis' (build) or 'stored' (recalibration)."
            )

    def summary(self) -> str:
        """One-line provenance string (successor to ``cg_settings_print``)."""
        return (
            f"cubegenpy[cal={self.calibration}, bg={self.background.mode}, "
            f"v{self.fits_version}]"
        )


DEFAULT_CONFIG = BuildConfig()
