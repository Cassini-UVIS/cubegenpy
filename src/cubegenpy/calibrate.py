"""Counts -> calibrated cube, with the background-subtraction knob and the
calibration extension seam.

This is the focus of the OO port. It collapses the IDL pipeline's
counts-vs-counts/sec ambiguity and its ``eq 2``/``eq 3`` dimensionality branches
into a single broadcasting formula operating entirely in counts/sec space::

    calibrated = (raw_counts / int_time - background_offset) * cal_factor

Two orthogonal pieces of data drive it:

* :class:`Background` — *how much* to subtract before applying the cal factor,
  modelled as a value/spec (not a bool) so it can carry the RTG dark rate or a
  spectral-average band.
* :class:`CalModel` — *where the cal factor comes from*. This is the documented
  extension seam: :class:`StoredCalModel` (recalibration: reuse the FITS's stored
  factor verbatim), :class:`PyuvisCalModel` (build path, real PDS data — stub),
  and :class:`SpicaCalModel` (future stellar-calibration augmentation).

No SPICE, no geometry: geometry only ever flows through as opaque arrays
elsewhere in the pipeline (PORT_PLAN §7).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import numpy as np

if TYPE_CHECKING:  # avoid an import cycle product -> writer (only needed for hints)
    from .product import ProductInputs


# --------------------------------------------------------------------------- #
# Background — the central knob, modelled as data
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Background:
    """How much background (in counts/sec) to subtract before calibration.

    Models the two IDL background modes as data instead of flags:

    * ``"none"`` — subtract nothing (default).
    * ``"rtg"`` — subtract a constant dark rate ``rtg_value`` (the
      radioisotope-thermoelectric-generator background, IDL ``pass.rtg``).
    * ``"spectral_average"`` — estimate the background from a featureless
      wavelength band (``wavelength_range``) by averaging counts/sec over the
      spectral axis, then subtract that per-(slit, readout) average from every
      spectral sample.

    ``spatial_bin``/``spectral_bin`` are carried for parity with the IDL spec but
    are not yet used by the stand-in spectral-average estimator.
    """

    mode: str = "none"
    rtg_value: float = 0.0004
    spatial_bin: int = 1
    spectral_bin: int = 1
    wavelength_range: tuple[float, float] | None = None

    def __post_init__(self) -> None:
        if self.mode not in ("none", "rtg", "spectral_average"):
            raise ValueError(f"unknown background mode: {self.mode!r}")
        if self.mode == "spectral_average" and self.wavelength_range is None:
            raise ValueError("spectral_average background needs a wavelength_range")

    def offset(self, counts_per_sec: np.ndarray, wavelength: np.ndarray):
        """Return the amount to subtract from ``counts_per_sec``.

        ``counts_per_sec`` is the ``(NX, NY, NZ)`` cube already divided by the
        integration time; ``wavelength`` is the ``(NX,)`` centre-wavelength axis.
        The return value is a scalar (``none``/``rtg``) or a ``(1, NY, NZ)`` array
        (``spectral_average``) — both broadcast cleanly against the cube.
        """
        if self.mode == "none":
            return 0.0
        if self.mode == "rtg":
            return float(self.rtg_value)
        # spectral_average
        lo, hi = self.wavelength_range
        wavelength = np.asarray(wavelength)
        mask = (wavelength >= lo) & (wavelength <= hi)
        if not mask.any():
            raise ValueError(
                f"wavelength_range {self.wavelength_range} selects no spectral "
                f"samples (axis spans {wavelength.min():g}..{wavelength.max():g})"
            )
        band = np.asarray(counts_per_sec)[mask, :, :]
        return band.mean(axis=0, keepdims=True)


# --------------------------------------------------------------------------- #
# CalModel — the extension seam for where cal_factor comes from
# --------------------------------------------------------------------------- #

@runtime_checkable
class CalModel(Protocol):
    """Produces the 2-D ``CAL_FACTOR`` (NX, NY) for a product.

    The seam that lets real pyuvis/Spica calibration models drop in later without
    touching the :class:`Calibrator` or :class:`~cubegenpy.builder.CubeBuilder`.
    """

    def cal_factor(self, inputs: "ProductInputs") -> np.ndarray:
        ...


class StoredCalModel:
    """Return a cal factor that was already computed and stored.

    The recalibration path: read ``CAL_FACTOR`` back from a downloaded FITS and
    reuse it verbatim (no recompute), so a rebuild with a new :class:`Background`
    changes only the primary cube and leaves the ``CAL_FACTOR`` HDU byte-identical.
    """

    def __init__(self, stored: np.ndarray) -> None:
        self._stored = np.asarray(stored, dtype=np.float32)

    def cal_factor(self, inputs: "ProductInputs") -> np.ndarray:
        return self._stored


class UnitCalModel:
    """A cal factor of all ones — the ``calibration="none"`` debug passthrough.

    With a unit factor and no background the calibrated cube is just counts/sec,
    so the primary HDU shows the raw signal for inspection. The real
    ``CAL_FACTOR`` HDU is still written from ``inputs.cal_factor``; only the cube
    bypasses it.
    """

    def cal_factor(self, inputs: "ProductInputs") -> np.ndarray:
        return np.ones_like(np.asarray(inputs.cal_factor, dtype=np.float32))


class PyuvisCalModel:
    """Derive the cal factor from pyuvis (build path) — **not wired yet**.

    Will read the archived PDS cal matrix via :mod:`pyuvis` (``UVPDS`` / cal
    matrix x ``CORE_MULTIPLIER`` -> kR). Thin glue; only exercised once real PDS
    data is wired (blocked on the Showalter geometry format). pyuvis is imported
    lazily so the rest of the core has no hard pyuvis/cal-data dependency.
    """

    def cal_factor(self, inputs: "ProductInputs") -> np.ndarray:
        raise NotImplementedError(
            "PyuvisCalModel needs the real pyuvis PDS cal-matrix wiring, which is "
            "blocked on the Showalter geometry source. Use StoredCalModel "
            "(calibration='stored') for the FITS-readback/recalibration path."
        )


class SpicaCalModel:
    """Stellar-calibration-augmented cal factor — **future seam, documented stub**.

    Composes lab sensitivity x spectral modifier x (1 / flatfield), mapping onto
    the IDL ``Get_UVIS_calibration`` chain and
    ``pyuvis.calib.greg.get_spica_obs`` / ``steffl.Row2Row``. This is the drop-in
    point for "more stellar-calibration observations not yet analyzed" (Spica and
    the 1,341 FUV+EUV STAR observations). The :class:`CalModel` Protocol guarantees
    it slots in without touching the core; it is intentionally not implemented now.
    """

    def cal_factor(self, inputs: "ProductInputs") -> np.ndarray:
        raise NotImplementedError(
            "SpicaCalModel (stellar-calibration augmentation) is a reserved seam — "
            "see Plans/so-the-basic-guide-twinkly-ritchie.md and PORT_PLAN.md §4."
        )


# --------------------------------------------------------------------------- #
# Calibrator
# --------------------------------------------------------------------------- #

class Calibrator:
    """Turn raw counts into a calibrated cube via a chosen :class:`CalModel`."""

    def __init__(self, cal_model: CalModel) -> None:
        self.cal_model = cal_model

    def calibrate(self, inputs: "ProductInputs", background: Background) -> np.ndarray:
        """Compute the calibrated ``(NX, NY, NZ)`` cube as ``float32``.

        Operates entirely in counts/sec space. The 2-D ``cal_factor`` (NX, NY) is
        broadcast against the 3-D cube over the readout axis. ``np.nan_to_num``
        stands in for the IDL row-wise ``cg_interpolate_nans2`` (the NaNs come from
        undefined ``CAL_FACTOR`` entries) until real FUV data needs interpolation.
        """
        int_time = float(inputs.header["INT_TIME"])
        if int_time <= 0:
            raise ValueError(f"INT_TIME must be positive, got {int_time!r}")

        counts_per_sec = np.asarray(inputs.raw_counts, dtype=np.float64) / int_time
        offset = background.offset(counts_per_sec, inputs.wavelength)
        cal_factor = np.asarray(self.cal_model.cal_factor(inputs), dtype=np.float64)

        net = counts_per_sec - offset
        calibrated = net * cal_factor[:, :, np.newaxis]  # (NX, NY, 1) -> (NX, NY, NZ)
        np.nan_to_num(calibrated, copy=False)  # in place: `calibrated` is a fresh array
        return calibrated.astype(np.float32)
