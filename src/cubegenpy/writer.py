"""Assemble a Cassini UVIS observation into a proposal-shaped PDS4 FITS file.

This is the **draft** writer for the new layout (see :mod:`cubegenpy.layout`).
It is deliberately a pure assembler:

* **Data in, FITS out.** The caller supplies the calibrated cube, raw counts,
  calibration factor, wavelengths, a ``geometry`` mapping (keyed by HDU name),
  and the kernel list. The writer never computes geometry or fetches data —
  that is the upstream pipeline's job (proposal + plan).
* Every HDU, dtype, shape and keyword is taken from :mod:`cubegenpy.layout`,
  so the proposal is the single source of truth.

Multidimensional geometry cells use FITS ``TDIM`` in the proposal's axis order
(fastest axis first, e.g. ``5,NY,NZ,NT``). numpy stores axes slowest-first, so
the caller's arrays are expected with the **reversed** trailing shape
(``..., NT, NZ, NY, 5``); astropy then writes the correct ``TDIMn``. See
:func:`cubegenpy.demo.make_synthetic_product` for a worked example.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np
from astropy.io import fits

from . import layout
from .layout import CAL_FACTOR_NULL, Column, HDUSpec, Keyword

_KIND_TO_NP = {"float32": np.float32, "float64": np.float64, "bool": np.bool_}
_KIND_TO_CODE = {"float32": "E", "float64": "D", "bool": "L"}


@dataclass(frozen=True)
class Dims:
    """Resolved integer dimensions for one product."""

    NX: int  # wavelengths
    NY: int  # window height (slit samples kept)
    NZ: int  # readout/integration steps
    NT: int = 3  # sub-samples per readout

    def resolve(self, tdim: tuple[str, ...]) -> tuple[int, ...]:
        """Map FITS-order dim tokens to integer sizes (FITS order)."""
        table = {"NX": self.NX, "NY": self.NY, "NZ": self.NZ, "NT": self.NT}
        return tuple(int(t) if t.isdigit() else table[t] for t in tdim)

    def cell_shape_numpy(self, tdim: tuple[str, ...]) -> tuple[int, ...]:
        """Per-row numpy cell shape = reversed FITS dims (slowest-first)."""
        return tuple(reversed(self.resolve(tdim)))


# --------------------------------------------------------------------------- #
# Column / table construction
# --------------------------------------------------------------------------- #

def _column(col: Column, nrows: int, dims: Dims,
            provided: Mapping[str, object] | None) -> fits.Column:
    """Build one ``fits.Column`` from a layout spec, using provided data or zeros."""
    provided = provided or {}

    if col.kind == "char":
        values = provided.get(col.name) or [""] * nrows
        arr = _char_array(values, col.char_len)
        return fits.Column(name=col.name, format=f"A{col.char_len}", array=arr)

    np_dtype = _KIND_TO_NP[col.kind]
    code = _KIND_TO_CODE[col.kind]
    cell = dims.cell_shape_numpy(col.tdim)  # () for scalars

    supplied = provided.get(col.name)
    if supplied is None:
        arr = np.zeros((nrows, *cell), dtype=np_dtype)
    else:
        arr = np.asarray(supplied, dtype=np_dtype)
        expected = (nrows, *cell)
        if arr.shape != expected:
            raise ValueError(
                f"{col.name}: got array shape {arr.shape}, expected {expected} "
                f"(nrows={nrows}, FITS TDIM={dims.resolve(col.tdim)})"
            )

    if cell:  # multidimensional cell -> explicit TDIM in proposal (FITS) order
        fmt = f"{math.prod(cell)}{code}"
        dim = "(" + ",".join(str(n) for n in dims.resolve(col.tdim)) + ")"
        return fits.Column(name=col.name, format=fmt, array=arr,
                           dim=dim, unit=col.unit or None)
    return fits.Column(name=col.name, format=code, array=arr, unit=col.unit or None)


def _table_hdu(spec: HDUSpec, nrows: int, dims: Dims,
               provided: Mapping[str, object] | None) -> fits.BinTableHDU:
    cols = [_column(c, nrows, dims, provided) for c in spec.columns]
    hdu = fits.BinTableHDU.from_columns(cols, name=spec.name)
    hdu.header["EXTNAME"] = spec.name  # correct the proposal's copy-paste typo
    _annotate_columns(hdu, spec)
    return hdu


def _char_array(values: Sequence[object], char_len: int) -> np.ndarray:
    """Fixed-width unicode array, truncated to ``char_len`` (for ``A``-format columns)."""
    return np.array([str(v)[:char_len] for v in values], dtype=f"U{char_len}")


def _ascii_hdu(spec: HDUSpec, rows: Mapping[str, Sequence[str]]) -> fits.TableHDU:
    nrows = max((len(v) for v in rows.values()), default=0)
    cols = []
    for c in spec.columns:
        arr = _char_array(rows.get(c.name, [""] * nrows), c.char_len)
        cols.append(fits.Column(name=c.name, format=f"A{c.char_len}", array=arr))
    hdu = fits.TableHDU.from_columns(cols, name=spec.name)
    hdu.header["EXTNAME"] = spec.name
    _annotate_columns(hdu, spec)
    return hdu


def _annotate_columns(hdu: fits.BinTableHDU, spec: HDUSpec) -> None:
    for i, c in enumerate(spec.columns, start=1):
        if c.comment:
            hdu.header.comments[f"TTYPE{i}"] = c.comment[:60]


# --------------------------------------------------------------------------- #
# Header
# --------------------------------------------------------------------------- #

def _fmt_utc(value: str) -> str:
    """UTC string with no time zone and at most millisecond precision."""
    dt = datetime.fromisoformat(str(value).strip()).replace(tzinfo=None)
    return dt.isoformat(timespec="milliseconds")


def _fmt_date(value: str) -> str:
    """File DATE with no fractional seconds."""
    return str(value).strip().split(".")[0]


def _build_primary(cube: np.ndarray, header_values: Mapping[str, object]) -> fits.PrimaryHDU:
    hdu = fits.PrimaryHDU(data=np.asarray(cube, dtype=np.float32))
    hdr = hdu.header
    for kw in layout.PRIMARY_KEYWORDS:
        if kw.name not in header_values:
            continue
        hdr[kw.name] = (_coerce_keyword(kw, header_values[kw.name]), kw.comment)
        if kw.unit:
            hdr.comments[kw.name] = f"[{kw.unit}] {kw.comment}"
    hdr["COMMENT"] = "Calibrated data array (NX, NY, NZ); see PDS4 label."
    return hdu


def _coerce_keyword(kw: Keyword, value: object) -> object:
    if kw.kind == "utc":
        return _fmt_utc(value)
    if kw.kind == "date":
        return _fmt_date(value)
    if kw.kind == "int":
        return int(value)
    if kw.kind == "float":
        return float(value)
    return str(value)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def build_hdulist(
    *,
    cube: np.ndarray,
    raw_counts: np.ndarray,
    cal_factor: np.ndarray,
    wavelength: np.ndarray,
    header: Mapping[str, object],
    geometry: Mapping[str, Mapping[str, object]],
    kernels: Sequence[tuple[str, str]],
    bodies: Sequence[str],
    resolved_bodies: Sequence[str],
    dims: Dims,
    rings_in_fov: bool = False,
    edge_on: bool = False,
) -> fits.HDUList:
    """Assemble the full proposal-shaped :class:`~astropy.io.fits.HDUList`.

    Parameters mirror the proposal's data products. ``geometry`` is keyed by
    HDU name (``"SC_GEOM"``, ``"BODY_GEOM"``, ``"GENERAL_GEOM"``,
    ``"RING_GEOM"``); each value maps column name -> ndarray already shaped
    ``(nrows, *reversed_tdim)``. Missing columns are zero-filled so a partial
    geometry pipeline still yields a valid, inspectable file.
    """
    if "SATURN" not in [b.upper() for b in bodies]:
        # Proposal p.6: always include Saturn in SC_GEOM even if outside the FOV.
        bodies = [*bodies, "SATURN"]

    specs = layout.hdu_specs(rings_in_fov=rings_in_fov, edge_on=edge_on)
    hdus: list[fits.hdu.base._BaseHDU] = []

    for spec in specs:
        if spec.name == "PRIMARY":
            hdus.append(_build_primary(cube, header))
        elif spec.name == "RAW_COUNTS":
            hdus.append(fits.ImageHDU(np.asarray(raw_counts, dtype=np.int16), name="RAW_COUNTS"))
        elif spec.name == "CAL_FACTOR":
            cf = np.array(cal_factor, dtype=np.float32)  # own a float32 copy
            cf[np.isnan(cf)] = CAL_FACTOR_NULL           # fill NULL in place
            ihdu = fits.ImageHDU(cf, name="CAL_FACTOR")
            ihdu.header["NULLVAL"] = (CAL_FACTOR_NULL, "Value flagging an undefined entry")
            hdus.append(ihdu)
        elif spec.name == "WAVELENGTH":
            whdu = fits.ImageHDU(np.asarray(wavelength, dtype=np.float32), name="WAVELENGTH")
            whdu.header["BUNIT"] = "Angstrom"
            hdus.append(whdu)
        elif spec.name == "KERNELS":
            rows = {
                "FILENAME": [k[0] for k in kernels],
                "KERNEL_TYPE": [k[1] for k in kernels],
            }
            hdus.append(_ascii_hdu(spec, rows))
        else:  # geometry BINTABLEs
            nrows = _nrows_for(spec, bodies, resolved_bodies)
            provided = dict(geometry.get(spec.name, {}))
            provided.setdefault("NAME", _names_for(spec, bodies, resolved_bodies))
            hdus.append(_table_hdu(spec, nrows, dims, provided))

    return fits.HDUList(hdus)


def _nrows_for(spec: HDUSpec, bodies, resolved_bodies) -> int:
    if spec.row_mode == "per_body":
        return len(bodies)
    if spec.row_mode == "per_resolved_body":
        return len(resolved_bodies)
    return 1  # singleton


def _names_for(spec: HDUSpec, bodies, resolved_bodies):
    if spec.row_mode == "per_body":
        return list(bodies)
    if spec.row_mode == "per_resolved_body":
        return list(resolved_bodies)
    return [""]


def write_product(
    out_dir: str | Path,
    product_id: str,
    hdulist: fits.HDUList,
    *,
    write_label: bool = True,
    overwrite: bool = True,
) -> dict[str, Path]:
    """Write ``<product_id>.fits`` (and an optional draft ``.xml`` label)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fits_path = out_dir / f"{product_id}.fits"
    hdulist.writeto(fits_path, overwrite=overwrite)

    paths = {"fits": fits_path}
    if write_label:
        from .labels import write_draft_label  # local import: label is optional

        paths["label"] = write_draft_label(out_dir, product_id, hdulist)
    return paths
