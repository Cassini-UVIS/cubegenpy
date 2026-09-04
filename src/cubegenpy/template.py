"""Load the data-definition workbook into the layout dataclasses.

This is the seam that makes the spreadsheet, not Python, the source of truth for
the FITS format. It reads ``UVIS_data_definition_v0.5.xlsx`` and produces exactly
the :class:`~cubegenpy.layout.HDUSpec` / :class:`~cubegenpy.layout.Column` /
:class:`~cubegenpy.layout.Keyword` objects that :mod:`cubegenpy.writer` already
consumes, so nothing downstream has to change::

    workbook -> template.load() -> HDUSpec/Column/Keyword -> writer.build_hdulist

The hardcoded tuples in :mod:`cubegenpy.layout` remain as the v1 baseline. The
workbook carries **v2**, so loading it is also what upgrades the writer to the
v2 column inventory (SC_GEOM 25, BODY_GEOM 13, GENERAL_GEOM 3, RING_GEOM 14).

The workbook is read **once** per path and cached. The old ``fits_writer2`` read
its workbook twice, in two modules that then drifted; one loader avoids that.

Sheet requirements are deliberately strict: an unknown value in a categorical
column raises rather than being silently coerced, because a typo in ``null_mode``
would otherwise produce a structurally valid archive with wrong null semantics.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pandas as pd

from .layout import Column, HDUSpec, Keyword

__all__ = ["load", "TemplateError", "Template", "HDUKeyword"]

# Package-data copy; falls back to the repo's data_definition/ during development.
_PACKAGED = Path(__file__).parent / "templates" / "UVIS_data_definition_v0.5.xlsx"
_REPO = (Path(__file__).resolve().parents[4]
         / "data_definition" / "UVIS_data_definition_v0.5.xlsx")


class TemplateError(ValueError):
    """The workbook is missing something, or says something invalid."""


# Workbook dtype vocabulary -> (layout kind, char_len)
_DTYPES: dict[str, tuple[str, int]] = {
    "float32": ("float32", 0),
    "float64": ("float64", 0),
    "logical": ("bool", 0),
    "char4": ("char", 4),
    "char12": ("char", 12),
    "char32": ("char", 32),
}

_PRESENCE = {"always": "always", "always_degenerate": "rings_in_fov"}


@dataclass(frozen=True)
class HDUKeyword:
    """A keyword stamped on an *extension* header.

    ``source`` is ``literal:<value>`` (the workbook supplies the value) or
    ``computed:<name>`` (the writer supplies it at build time, keyed by name).
    """

    extname: str
    name: str
    kind: str
    source: str
    comment: str

    @property
    def literal(self) -> str | None:
        return (self.source.split(":", 1)[1]
                if self.source.startswith("literal:") else None)

    @property
    def computed_key(self) -> str | None:
        return (self.source.split(":", 1)[1]
                if self.source.startswith("computed:") else None)


class Template:
    """The loaded workbook: HDU specs, primary keywords, extension keywords."""

    def __init__(self, path: Path, hdus: list[HDUSpec], keywords: tuple[Keyword, ...],
                 hdu_keywords: tuple[HDUKeyword, ...] = ()):
        self.path = path
        self._hdus = hdus
        self.keywords = keywords
        self._hdu_keywords = hdu_keywords

    def hdu_keywords(self, extname: str) -> tuple[HDUKeyword, ...]:
        """Extension-header keywords declared for ``extname``."""
        return tuple(k for k in self._hdu_keywords if k.extname == extname)

    def hdu_specs(self, *, rings_in_fov: bool = False,
                  edge_on: bool = False) -> list[HDUSpec]:
        """Ordered HDU specs, mirroring :func:`cubegenpy.layout.hdu_specs`.

        ``RING_GEOM`` is ``always_degenerate`` in v2 -- always present, with its
        arrays collapsing to a scalar NaN when no rings are in the field of view.
        The ``rings_in_fov`` argument is accepted for signature compatibility with
        the hardcoded layout; under v2 it does not remove the HDU.
        """
        del rings_in_fov, edge_on  # v2: presence is fixed, degeneracy is in the data
        return list(self._hdus)

    def __repr__(self) -> str:
        return (f"<Template {self.path.name}: {len(self._hdus)} HDUs, "
                f"{len(self.keywords)} keywords>")


def _sheet(xl: pd.ExcelFile, name: str) -> pd.DataFrame:
    if name not in xl.sheet_names:
        raise TemplateError(f"workbook has no {name!r} sheet")
    return xl.parse(name).fillna("")


def _validate_enums(xl: pd.ExcelFile, sheets: dict[str, pd.DataFrame]) -> None:
    """Every categorical cell must appear in the ``enums`` sheet."""
    if "enums" not in xl.sheet_names:
        return
    enums = _sheet(xl, "enums")
    allowed = {f: set(g.allowed_value) for f, g in enums.groupby("field")}
    checks = [
        ("xtension", sheets["hdus"], "xtension"),
        ("row_mode", sheets["hdus"], "row_mode"),
        ("presence", sheets["hdus"], "presence"),
        ("data_type", sheets["columns"], "data_type"),
        ("null_mode", sheets["columns"], "null_mode"),
        ("value_type", sheets["header_keywords"], "value_type"),
    ]
    for field, df, col in checks:
        if field not in allowed or col not in df:
            continue
        used = {str(v).strip() for v in df[col] if str(v).strip()}
        if bad := used - allowed[field]:
            raise TemplateError(
                f"{col!r} has values outside the enums sheet: {sorted(bad)}"
            )


def _columns_for(df: pd.DataFrame, extname: str) -> tuple[Column, ...]:
    out: list[Column] = []
    for _, r in df[df.extname == extname].iterrows():
        dtype = str(r.data_type).strip()
        if dtype not in _DTYPES:
            raise TemplateError(
                f"{extname}.{r.ttype}: unknown data_type {dtype!r}"
            )
        kind, char_len = _DTYPES[dtype]
        raw_tdim = str(r.tdim).strip()
        # The workbook distinguishes the backplane slit axis (NYG) from the data
        # slit axis (NY). Dims has a single NY until the team settles the binning
        # question, so map it through for now -- see Part C.7 of the plan.
        tdim = tuple(t.strip().replace("NYG", "NY")
                     for t in raw_tdim.split(",") if t.strip())
        out.append(Column(
            name=str(r.ttype).strip(),
            kind=kind,
            tdim=tdim,
            unit=str(r.tunit).strip() or None,
            char_len=char_len,
            comment=str(r.description).strip()[:45],
        ))
    return tuple(out)


@lru_cache(maxsize=None)
def load(path: str | Path | None = None) -> Template:
    """Load the workbook and return the parsed :class:`Template`."""
    if path is None:
        path = _PACKAGED if _PACKAGED.exists() else _REPO
    path = Path(path)
    if not path.exists():
        raise TemplateError(f"data-definition workbook not found: {path}")

    xl = pd.ExcelFile(path)
    sheets = {n: _sheet(xl, n) for n in ("hdus", "columns", "header_keywords")}
    _validate_enums(xl, sheets)

    hdus_df = sheets["hdus"].sort_values("hdu_index")
    if list(hdus_df.hdu_index) != list(range(len(hdus_df))):
        raise TemplateError(
            f"hdu_index must be contiguous from 0; got {list(hdus_df.hdu_index)}"
        )

    specs: list[HDUSpec] = []
    for _, r in hdus_df.iterrows():
        extname = str(r.extname).strip()
        presence = str(r.presence).strip()
        if presence not in _PRESENCE:
            raise TemplateError(f"{extname}: unknown presence {presence!r}")
        specs.append(HDUSpec(
            name=extname,
            xtension=("PRIMARY" if str(r.xtension).strip() == "PRIMARY_IMAGE"
                      else str(r.xtension).strip()),
            row_mode=str(r.row_mode).strip(),
            include=_PRESENCE[presence],
            columns=_columns_for(sheets["columns"], extname),
            description=str(r.description).strip(),
        ))

    kw_df = sheets["header_keywords"].sort_values("order")
    # The workbook's vocabulary is user-facing; `writer._coerce_keyword` spells
    # the file-creation timestamp 'date'.
    kind_map = {"datetime": "date"}
    keywords = tuple(
        Keyword(
            name=str(r.keyword).strip(),
            kind=kind_map.get(str(r.value_type).strip(), str(r.value_type).strip()),
            unit=str(r.unit).strip() or None,
            # FITS cards are 80 chars; keep comments short enough that
            # astropy does not truncate them with a warning.
            comment=str(r.comment).strip()[:45],
        )
        for _, r in kw_df.iterrows()
    )
    hk: list[HDUKeyword] = []
    if "hdu_keywords" in xl.sheet_names:
        for _, r in _sheet(xl, "hdu_keywords").iterrows():
            hk.append(HDUKeyword(
                extname=str(r.extname).strip(),
                name=str(r.keyword).strip(),
                kind=str(r.value_type).strip(),
                source=str(r.source).strip(),
                comment=str(r.comment).strip()[:45],
            ))
        known = {s.name for s in specs}
        if bad := {k.extname for k in hk} - known:
            raise TemplateError(f"hdu_keywords names unknown HDUs: {sorted(bad)}")

    return Template(path, specs, keywords, tuple(hk))
