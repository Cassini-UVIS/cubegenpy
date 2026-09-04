"""Choosing ``NT``: how finely one integration is sub-sampled in time.

``NT`` is the sub-integration axis of the geometry backplanes -- the number of
points at which the geometry is evaluated *within* a single readout, so that
smear can be reconstructed when the instrument moves appreciably during an
integration. v2 decides the floor (three: begin, middle, end) and leaves the
rest open: *"For long, significantly smeared products, finer sampling in T will
be provided ... the precise details are still TBD."*

That TBD is a policy, not a constant, so it lives here as one object the
geometry provider can set, inspect and defend, rather than as a number buried in
a call site::

    from cubegenpy import SubsamplingPolicy

    policy = SubsamplingPolicy()                 # the default rule
    nt = policy.recommend(smear_pixels=6.2)      # -> 7

    strict = SubsamplingPolicy(pixels_per_subsample=0.5, maximum=65)
    nt = strict.recommend(smear_pixels=6.2)      # -> 14

The default rule is deliberately simple and stated in one line of arithmetic so
it can be argued with: place sample points no more than
``pixels_per_subsample`` apart along the smear track, never fewer than
``minimum``, never more than ``maximum``. Fenceposts, so a smear of *S* pixels
sampled every *P* pixels needs ``ceil(S / P) + 1`` points.

The policy is recorded in the product, not just applied: :meth:`describe`
returns the one-line provenance that the writer stores in ``NT_RULE``, so a
reader can see why a given file has the NT it has.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

__all__ = ["SubsamplingPolicy", "NTOutOfRange", "smear_pixels"]

# v2 p.12: "NT >= 3, meaning that all backplanes are generated for the
# beginning, middle, and end of each integration."
NT_FLOOR = 3


class NTOutOfRange(ValueError):
    """A supplied NT violates the proposal's floor or the policy's ceiling."""


@dataclass(frozen=True)
class SubsamplingPolicy:
    """The rule for turning smear into a sub-sample count.

    Parameters
    ----------
    pixels_per_subsample
        Target spacing of sample points along the smear track, in detector
        pixels. Smaller means finer time sampling and a larger product: every
        backplane column scales linearly with ``NT``.
    minimum
        Floor. Must be at least 3; v2 fixes that, so lowering it is refused
        rather than silently honoured.
    maximum
        Ceiling, to stop a pathological product from exploding. Backplane
        volume is ``5 * NY * NZ * NT`` floats per column, so this is a real
        constraint rather than a formality.
    """

    pixels_per_subsample: float = 1.0
    minimum: int = NT_FLOOR
    maximum: int = 33

    def __post_init__(self) -> None:
        if self.minimum < NT_FLOOR:
            raise NTOutOfRange(
                f"minimum={self.minimum} is below the proposal's floor of "
                f"{NT_FLOOR} (v2 p.12: begin, middle and end of each integration)"
            )
        if self.maximum < self.minimum:
            raise NTOutOfRange(
                f"maximum={self.maximum} is below minimum={self.minimum}"
            )
        if self.pixels_per_subsample <= 0:
            raise NTOutOfRange("pixels_per_subsample must be positive")

    def recommend(self, smear_pixels: float) -> int:
        """NT for an integration that smears ``smear_pixels`` across the slit."""
        if smear_pixels < 0 or not math.isfinite(smear_pixels):
            raise NTOutOfRange(f"smear_pixels must be finite and >= 0, got {smear_pixels}")
        needed = math.ceil(smear_pixels / self.pixels_per_subsample) + 1
        return max(self.minimum, min(self.maximum, needed))

    def validate(self, nt: int) -> int:
        """Return ``nt`` unchanged, or raise if it is outside the policy."""
        if nt < NT_FLOOR:
            raise NTOutOfRange(
                f"NT={nt} is below the proposal's floor of {NT_FLOOR}"
            )
        if nt > self.maximum:
            raise NTOutOfRange(f"NT={nt} exceeds the policy maximum of {self.maximum}")
        return nt

    def describe(self) -> str:
        """One-line provenance, short enough to fit a FITS card with its comment."""
        return (f"{self.pixels_per_subsample:g}px/sub, "
                f"NT {self.minimum}-{self.maximum}")


def smear_pixels(slew_rate_deg_s: float, integration_s: float,
                 pixel_scale_deg: float) -> float:
    """Smear during one integration, in detector pixels.

    A convenience for the common case where the provider has a slew rate rather
    than a smear length. Kept separate from the policy so a provider computing
    smear some other way -- from SPICE pointing at the integration endpoints,
    say -- can pass the result straight to :meth:`SubsamplingPolicy.recommend`.
    """
    if pixel_scale_deg <= 0:
        raise NTOutOfRange("pixel_scale_deg must be positive")
    return abs(slew_rate_deg_s) * abs(integration_s) / pixel_scale_deg
