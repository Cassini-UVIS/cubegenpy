"""Stage 1 of the two-stage pipeline: a geometry-complete, science-empty product.

The idea is to invert the usual order. Instead of the geometry provider handing
over a Python dict that this package then has to interpret, **the provider writes
the archive product itself** -- header, all geometry HDUs, kernels, wavelengths --
leaving only the science arrays empty. Calibration fills those in afterwards
(stage 2), preserving everything stage 1 wrote.

The payoff is that the interchange format stops being a negotiated dict and
becomes the FITS file: self-describing, inspectable with any FITS tool, and
already the thing being delivered. :func:`geometry_contract` prints exactly what
each geometry column must look like, so the provider can check their arrays
before writing rather than after.

Typical use::

    from cubegenpy import write_skeleton, geometry_contract, check_skeleton
    from cubegenpy.writer import Dims

    dims = Dims(NX=1024, NY=32, NZ=180, NT=3)
    print(geometry_contract(dims))          # what shapes to supply

    path = write_skeleton(
        "out/", "EUV2002_198_03_26",
        dims=dims,
        header={"PROD_ID": "EUV2002_198_03_26", "CHANNEL": "EUV", ...},
        geometry={"SC_GEOM": {...}, "BODY_GEOM": {...}, ...},
        kernels=[("naif0012.tls", "LSK")],
        bodies=["SATURN", "TITAN"], resolved_bodies=["TITAN"],
    )
    print(check_skeleton(path))             # what got filled, what did not

Placeholders are deliberately self-announcing: NaN for the float arrays and the
PDS3 null (65535) for raw counts, never zero -- a zero flux is a legal value and
would let an unfilled product pass unnoticed. The primary header carries
``PIPESTAT = 'GEOMETRY_ONLY'`` so a half-filled product can never be mistaken for
a finished one.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np
from astropy.io import fits

from . import layout, writer
from .layout import (
    CAL_FACTOR_NULL,
    PIPESTAT_COMPLETE,
    PIPESTAT_SKELETON,
    RAW_COUNTS_NULL,
)
from .writer import Dims

__all__ = [
    "write_skeleton",
    "calibrated_header",
    "geometry_contract",
    "check_skeleton",
    "is_skeleton",
    "SkeletonReport",
]


# --------------------------------------------------------------------------- #
# The contract: what the geometry provider must supply
# --------------------------------------------------------------------------- #

def geometry_contract(
    dims: Dims, *, rings_in_fov: bool = False, edge_on: bool = False,
) -> str:
    """Human-readable spec of every geometry array expected for ``dims``.

    Shapes are given in **numpy order** -- the order the arrays must actually
    have in memory. That is the reverse of the ``TDIM`` order the proposal
    writes, because FITS lists the fastest-varying axis first and numpy lists it
    last. Getting this backwards is the easiest mistake to make here, so both
    are shown.

    ``nrows`` is per-HDU: one row per body for ``SC_GEOM``, one per *resolved*
    body for ``BODY_GEOM``, and exactly one for the singleton tables.
    """
    lines = [
        f"Geometry contract for NX={dims.NX} NY={dims.NY} NZ={dims.NZ} NT={dims.NT}",
        "",
        "Array shapes are numpy order (slowest axis first) = reversed TDIM.",
        "Leading axis is the row count, described per HDU below.",
        "",
    ]
    for spec in writer.hdu_specs(rings_in_fov=rings_in_fov, edge_on=edge_on):
        if spec.xtension != "BINTABLE":
            continue
        nrows = {
            "per_body": "len(bodies)",
            "per_resolved_body": "len(resolved_bodies)",
        }.get(spec.row_mode, "1")
        lines.append(f"{spec.name}  (rows = {nrows})")
        for col in spec.columns:
            if col.name == "NAME":
                continue  # supplied by the writer from bodies/resolved_bodies
            if col.tdim:
                fits_dim = ",".join(str(n) for n in dims.resolve(col.tdim))
                np_shape = (nrows, *dims.cell_shape_numpy(col.tdim))
                shape = f"({', '.join(str(s) for s in np_shape)})"
                lines.append(
                    f"    {col.name:<26} {col.kind:<8} {shape:<26} TDIM=({fits_dim})"
                )
            else:
                lines.append(
                    f"    {col.name:<26} {col.kind:<8} ({nrows},){'':<19} scalar"
                )
        lines.append("")
    lines.append("Any column omitted is written as zeros and reported as")
    lines.append("unfilled by check_skeleton().")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Stage 1: write the skeleton
# --------------------------------------------------------------------------- #

def write_skeleton(
    out_dir: str | Path,
    product_id: str,
    *,
    dims: Dims,
    header: Mapping[str, object],
    geometry: Mapping[str, Mapping[str, object]] | None = None,
    kernels: Sequence[tuple[str, str]] = (),
    bodies: Sequence[str] = (),
    resolved_bodies: Sequence[str] = (),
    wavelength: np.ndarray | None = None,
    rings_in_fov: bool = False,
    edge_on: bool = False,
    overwrite: bool = True,
) -> Path:
    """Write a geometry-complete, science-empty product and return its path.

    Every argument except the science arrays mirrors
    :func:`cubegenpy.writer.build_hdulist`, so a skeleton is a normal product in
    every respect but its data content.

    Parameters
    ----------
    dims
        Must be final. FITS allocates array space on write, so the science
        arrays stage 2 fills have to be the right size from the start.
    header
        Primary-header values. ``PIPESTAT`` is set automatically and any caller
        value for it is ignored.
    wavelength
        Optional; NaN-filled if omitted, for the case where the wavelength
        solution is not yet known.
    """
    geometry = dict(geometry or {})
    hdr = {k: v for k, v in header.items() if k != "PIPESTAT"}
    hdr["PIPESTAT"] = PIPESTAT_SKELETON

    shape = (dims.NX, dims.NY, dims.NZ)
    hdul = writer.build_hdulist(
        # Self-announcing placeholders: never zero, which is a legal flux.
        cube=np.full(shape, np.nan, dtype=np.float32),
        raw_counts=np.full(shape, RAW_COUNTS_NULL, dtype=np.uint16),
        cal_factor=np.full((dims.NX, dims.NY), np.nan, dtype=np.float32),
        background=np.full((dims.NX, dims.NY), np.nan, dtype=np.float32),
        wavelength=(np.full(dims.NX, np.nan, dtype=np.float32)
                    if wavelength is None
                    else np.asarray(wavelength, dtype=np.float32)),
        header=hdr,
        geometry=geometry,
        kernels=list(kernels),
        bodies=list(bodies),
        resolved_bodies=list(resolved_bodies),
        dims=dims,
        rings_in_fov=rings_in_fov,
        edge_on=edge_on,
    )
    hdul[0].header["COMMENT"] = "GEOMETRY_ONLY: science arrays are placeholders."

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{product_id}.fits"
    hdul.writeto(path, overwrite=overwrite)
    return path


# --------------------------------------------------------------------------- #
# Inspection
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class SkeletonReport:
    """What a product contains, and what it is still missing."""

    path: Path
    pipestat: str | None
    dims: Dims
    bodies: tuple[str, ...]
    resolved_bodies: tuple[str, ...]
    filled_columns: tuple[str, ...]
    unfilled_columns: tuple[str, ...]
    science_filled: tuple[str, ...]

    @property
    def is_skeleton(self) -> bool:
        return self.pipestat == PIPESTAT_SKELETON

    def __str__(self) -> str:
        n_f, n_u = len(self.filled_columns), len(self.unfilled_columns)
        out = [
            f"{self.path.name}",
            f"  PIPESTAT        : {self.pipestat or '(absent)'}",
            f"  dims            : NX={self.dims.NX} NY={self.dims.NY} "
            f"NZ={self.dims.NZ} NT={self.dims.NT}",
            f"  bodies          : {', '.join(self.bodies) or '(none)'}",
            f"  resolved bodies : {', '.join(self.resolved_bodies) or '(none)'}",
            f"  science arrays  : {', '.join(self.science_filled) or 'none filled'}",
            f"  geometry        : {n_f} filled, {n_u} unfilled",
        ]
        if self.unfilled_columns:
            out.append("  unfilled columns:")
            out += [f"      {c}" for c in self.unfilled_columns]
        return "\n".join(out)


def check_skeleton(path: str | Path) -> SkeletonReport:
    """Inspect a product and report which parts carry real values.

    A geometry column counts as *unfilled* when it is entirely zero, which is
    what :func:`writer.build_hdulist` writes for a column the caller omitted.
    That is a heuristic -- a genuinely all-zero backplane would be reported as
    unfilled -- but for the intended use (did my arrays land where I meant them
    to?) it is the useful answer.
    """
    path = Path(path)
    filled: list[str] = []
    unfilled: list[str] = []
    science: list[str] = []

    with fits.open(path) as hdul:
        primary = hdul[0]
        pipestat = primary.header.get("PIPESTAT")
        # Proposal p.3: NAXIS1=wavelengths, NAXIS2=slit, NAXIS3=time steps.
        nx, ny, nz = (primary.header.get(f"NAXIS{i}", 0) for i in (1, 2, 3))

        nt = 0
        if "GENERAL_GEOM" in {h.header.get("EXTNAME") for h in hdul}:
            gg = hdul["GENERAL_GEOM"]
            for i, name in enumerate(gg.columns.names, start=1):
                if name == "TIME_ET":
                    dim = gg.header.get(f"TDIM{i}", "")
                    parts = dim.strip("()").split(",")
                    if len(parts) == 2:
                        nt = int(parts[1])

        # Science arrays: filled means "not entirely placeholder".
        if primary.data is not None and not np.all(np.isnan(primary.data)):
            science.append("PRIMARY")
        for ext, null in (("RAW_COUNTS", RAW_COUNTS_NULL),
                          ("CAL_FACTOR", CAL_FACTOR_NULL),
                          ("BACKGROUND", None), ("WAVELENGTH", None)):
            if ext not in {h.header.get("EXTNAME") for h in hdul}:
                continue
            data = hdul[ext].data
            if data is None:
                continue
            if null is not None:
                # placeholder is either the sentinel or NaN, depending on HDU
                unset = (data == null) | (np.isnan(data) if data.dtype.kind == "f"
                                          else np.zeros_like(data, bool))
                if not np.all(unset):
                    science.append(ext)
            elif not np.all(np.isnan(data)):
                science.append(ext)

        bodies: tuple[str, ...] = ()
        resolved: tuple[str, ...] = ()
        for hdu in hdul:
            ext = hdu.header.get("EXTNAME")
            if not ext or not isinstance(hdu, fits.BinTableHDU):
                continue
            names = hdu.columns.names
            if "NAME" in names:
                vals = tuple(str(v).strip() for v in hdu.data["NAME"])
                if ext == "SC_GEOM":
                    bodies = vals
                elif ext == "BODY_GEOM":
                    resolved = vals
            for col in names:
                if col == "NAME":
                    continue
                arr = np.asarray(hdu.data[col])
                target = filled if np.any(arr != 0) else unfilled
                target.append(f"{ext}.{col}")

    return SkeletonReport(
        path=path, pipestat=pipestat,
        dims=Dims(NX=nx, NY=ny, NZ=nz, NT=nt or 3),
        bodies=bodies, resolved_bodies=resolved,
        filled_columns=tuple(filled), unfilled_columns=tuple(unfilled),
        science_filled=tuple(science),
    )


def calibrated_header(header: Mapping[str, object]) -> dict:
    """Stage-1 header promoted for a stage-2 (calibrated) product.

    Stage 2 must not inherit ``PIPESTAT = GEOMETRY_ONLY``; a filled product that
    still claims to be a skeleton is as misleading as a skeleton that does not.
    Everything else the geometry provider wrote is carried through untouched::

        inputs = read_product(skeleton)
        kwargs = inputs.as_writer_kwargs() | {
            "cube": cube, "header": calibrated_header(inputs.header),
        }
    """
    out = dict(header)
    out["PIPESTAT"] = PIPESTAT_COMPLETE
    return out


def is_skeleton(path: str | Path) -> bool:
    """True if the product is geometry-only and must not be treated as science."""
    with fits.open(path) as hdul:
        return hdul[0].header.get("PIPESTAT") == PIPESTAT_SKELETON
