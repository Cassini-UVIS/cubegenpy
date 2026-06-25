"""Build configuration for cubegenpy — the Python successor to the IDL ``pass`` struct.

The IDL ``cube_generator`` threaded a large ``pass`` settings structure (built in
``cg_create_pass_struct.pro``) through the whole pipeline: calibration choice,
flatfield selector, background-subtraction flags, output format, etc. Most of
those fields are obsolete here — geometry is external, the GUI is gone, and the
legacy ``.sav``/ENVI/binary writers are replaced by the FITS writer. This frozen
dataclass keeps only the knobs that still have meaning for the FITS pipeline.

See ``PORT_PLAN.md`` §4 for the calibration-source decision this encodes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

CalibrationSource = Literal["pyuvis", "regenerate", "none"]


@dataclass(frozen=True)
class BuildConfig:
    """Options controlling how a UVIS observation is turned into a FITS product.

    Attributes
    ----------
    calibration
        Where the calibrated cube + ``CAL_FACTOR`` come from:

        * ``"pyuvis"`` (default) — read the archived, already-calibrated PDS
          product via :mod:`pyuvis` (counts × PDS cal matrix → kR). Thin glue,
          modern path, no cal-data-file management.
        * ``"regenerate"`` — port of the IDL ``Get_UVIS_calibration`` ("Ultimate"
          Greg Holsclaw time-varying cal); regenerates the cal factor
          independently. Requires the calibration data files. Deferred — not yet
          implemented.
        * ``"none"`` — fill the primary HDU with the raw counts (passthrough),
          for debugging.
    subtract_background
        Apply RTG / spectral-average background subtraction before calibration.
        Off by default, exactly as the IDL ``pass.rtg`` / spectral-avg flags were.
    write_pds4_label
        Emit the sibling draft PDS4 XML label.
    fits_version
        Value written to the primary-header ``VERSION`` keyword.
    """

    calibration: CalibrationSource = "pyuvis"
    subtract_background: bool = False
    write_pds4_label: bool = True
    fits_version: float = 1.0

    def __post_init__(self) -> None:
        if self.calibration not in ("pyuvis", "regenerate", "none"):
            raise ValueError(f"unknown calibration source: {self.calibration!r}")
        if self.calibration == "regenerate":
            raise NotImplementedError(
                "calibration='regenerate' (ported Get_UVIS_calibration) is not "
                "implemented yet — see PORT_PLAN.md §4. Use 'pyuvis' for now."
            )

    def summary(self) -> str:
        """One-line provenance string (successor to ``cg_settings_print``)."""
        bg = "bg-sub" if self.subtract_background else "no-bg"
        return f"cubegenpy[cal={self.calibration}, {bg}, v{self.fits_version}]"


DEFAULT_CONFIG = BuildConfig()
