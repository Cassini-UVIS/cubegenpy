"""The **v1 baseline** layout spec, kept as a fallback and a test fixture.

.. note::
   This module is no longer the source of truth. The FITS layout is defined by
   the data-definition workbook, loaded through :mod:`cubegenpy.template`, which
   carries Showalter's **v2** proposal (12 Aug 2026). Use
   :func:`cubegenpy.writer.hdu_specs` / :func:`~cubegenpy.writer.primary_keywords`
   to get the live specs; they fall back to this module only when the workbook
   cannot be read, and warn when they do.

   What remains here encodes the *v1* proposal (3 Feb 2026). It survives because
   it is dependency-free — no pandas, no openpyxl — and because it is a
   known-good baseline to test the workbook loader against.

Dimension tokens used in ``tdim`` (given in **FITS order**, fastest-varying
axis first, exactly as the proposal writes them):

* ``NX`` — number of wavelengths (spectral samples)
* ``NY`` — number of spatial samples along the slit = **window height**
* ``NZ`` — number of integration/readout steps
* ``NT`` — sub-samples per readout (begin/middle/end), typically 3
* ``"5"`` — pixel sampling: centre + 4 corners (backplanes)

Two proposal typos are corrected here deliberately: the EXTNAMEs come from the
section headings, not the copy-pasted ``EXTNAME='BODY_GEOM'`` in every header
dump; and ``IMG_YMAX`` is the slit *max*.

``RAW_COUNTS`` dtype — reversed
-------------------------------
This module used to argue for **uint16**, on the grounds that raw counts are
unsigned 0-65535 and signed int16 would overflow. That reasoning was about FITS
alone and is wrong once PDS4 is considered.

FITS writes unsigned 16-bit as ``BITPIX=16`` + ``BZERO=32768``, which is *offset
binary*: physical 0 becomes ``0x8000`` and 65535 becomes ``0x7FFF``, so no byte
matches the PDS3 encoding. PDS4 would then have to restate the offset as
``Element_Array/value_offset``, describing the same transformation twice — once
in the FITS header, once in the label — and a reader honouring both applies it
twice. Since PDS4 requires the label alone to be sufficient, the file must carry
exactly one description of its values.

So the writer emits **signed** integers with no offset and no scaling, widening
an individual product to int32 only when a real count exceeds 32767. See
:func:`cubegenpy.writer._raw_counts_hdu`. Values at or below 32767 keep their
exact PDS3 bytes as a side benefit.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Sentinel marking an undefined CAL_FACTOR entry (proposal p.4).
CAL_FACTOR_NULL = -1000.0

# PDS3 stores raw-count nulls as 65535 (the label's "-1" is wrong; proposal p.5
# says so too). Reused as the skeleton placeholder so an unfilled RAW_COUNTS
# reads as "no data" rather than as a plausible zero count.
RAW_COUNTS_NULL = 65535

# The proposal's integer null (p.5), declared in the header via BLANK.
RAW_COUNTS_BLANK = -1

# Largest value a signed 16-bit integer can hold.
INT16_MAX = 32767

# Values of the PIPESTAT keyword, which records how far a product has been
# through the pipeline. A geometry-only product is structurally complete and
# indistinguishable from a finished one without this.
PIPESTAT_SKELETON = "GEOMETRY_ONLY"
PIPESTAT_COMPLETE = "CALIBRATED"


@dataclass(frozen=True)
class Column:
    """One column of a geometry/table HDU.

    ``tdim`` is the per-cell shape in FITS axis order (fastest first), as the
    proposal writes it, e.g. ``("5", "NY", "NZ", "NT")`` for a backplane or
    ``("NZ", "NT")`` for a time series. Empty tuple = scalar (one value/row).
    """

    name: str
    kind: str  # "float32" | "float64" | "bool" | "char"
    tdim: tuple[str, ...] = ()
    unit: str | None = None
    char_len: int = 0  # only for kind == "char"
    comment: str = ""


@dataclass(frozen=True)
class HDUSpec:
    name: str
    xtension: str  # "PRIMARY" | "IMAGE" | "BINTABLE" | "ASCII_TABLE"
    row_mode: str  # "singleton" | "per_body" | "per_resolved_body"
    include: str = "always"  # "always" | "rings_in_fov" | "edge_on"
    columns: tuple[Column, ...] = field(default_factory=tuple)
    description: str = ""


# --- geometry column inventories (verbatim names from the proposal) ----------

_TS = ("NZ", "NT")  # time-series cells (no spatial axis)
_BP = ("5", "NY", "NZ", "NT")  # per-pixel backplane cells

SC_GEOM_COLUMNS: tuple[Column, ...] = (
    Column("NAME", "char", char_len=12, comment="Body inside FOV this row applies to"),
    Column("SUB_SC_LAT", "float32", _TS, "deg"),
    Column("SUB_SC_LON", "float32", _TS, "deg"),
    Column("SUB_SOLAR_LAT", "float32", _TS, "deg"),
    Column("SUB_SOLAR_LON", "float32", _TS, "deg"),
    Column("SC_ALTITUDE", "float32", _TS, "km"),
    Column("VEL_X_SC_RATE", "float32", _TS, "km/s"),
    Column("VEL_Y_SC_RATE", "float32", _TS, "km/s"),
    Column("VEL_Z_SC_RATE", "float32", _TS, "km/s"),
    Column("VX_SC", "float32", _TS, "km"),
    Column("VY_SC", "float32", _TS, "km"),
    Column("VZ_SC", "float32", _TS, "km"),
    Column("CENTER_RA", "float32", _TS, "deg", comment="Direction to body centre"),
    Column("CENTER_DEC", "float32", _TS, "deg", comment="Direction to body centre"),
    Column("CENTER_PHASE_ANGLE", "float32", _TS, "deg"),
    Column("PHI", "float32", _TS, "deg", comment="Definition pending (Todd)"),
    Column("RAM_LONGITUDE", "float32", _TS, "deg"),
    Column("RAM_LATITUDE", "float32", _TS, "deg"),
    Column("SATURN_LOCAL_TIME", "float32", _TS, "deg"),
    Column("PROJECTED_DIAMETER", "float32", (), "pixel", comment="Single midtime value"),
    Column("CENTER_Y", "float32", (), "pixel", comment="Body centre along slit axis"),
    Column("CENTER_Z", "float32", (), "pixel", comment="Body centre along readout axis"),
    Column("FULLY_INSIDE_FLAG", "bool", (), comment="1 if body fully inside FOV"),
)

BODY_GEOM_COLUMNS: tuple[Column, ...] = (
    Column("NAME", "char", char_len=12, comment="Resolved body this row applies to"),
    Column("LAT_CENTRIC", "float32", _BP, "deg"),
    Column("LAT_GRAPHIC", "float32", _BP, "deg"),
    Column("LON", "float32", _BP, "deg"),
    Column("SOLAR_HOUR_ANGLE", "float32", _BP, "deg"),
    Column("EMISSION_ANGLE", "float32", _BP, "deg"),
    Column("INCIDENCE_ANGLE", "float32", _BP, "deg", comment=">90 is dark face"),
    Column("PHASE_ANGLE", "float32", _BP, "deg"),
    Column("DISTANCE", "float32", _BP, "km"),
    Column("RAYHEIGHT", "float32", _BP, "km"),
    Column("RESOLUTION_FINE", "float32", _BP, "km/pixel"),
    Column("RESOLUTION_COARSE", "float32", _BP, "km/pixel"),
    Column("RING_SHADOW_FLAG", "bool", _BP, comment="1 if shadowed by rings"),
    Column("BEHIND_RING_FLAG", "bool", _BP, comment="1 if behind rings"),
)

# GENERAL_GEOM: proposal header dump says TFIELDS=7 but only lists these three
# columns (flagged discrepancy). We implement the three that are actually
# specified; extras can be appended here if Mark clarifies.
GENERAL_GEOM_COLUMNS: tuple[Column, ...] = (
    Column("RA", "float32", _BP, "deg"),
    Column("DEC", "float32", _BP, "deg"),
    Column("TIME_ET", "float64", _TS, "s", comment="SPICE ET, double precision"),
)

RING_GEOM_COLUMNS: tuple[Column, ...] = (
    Column("RING_RADIUS", "float32", _BP, "km"),
    Column("RING_LONGITUDE", "float32", _BP, "deg"),
    Column("RING_AZIMUTH", "float32", _BP, "deg"),
    Column("RING_HOUR_ANGLE", "float32", _BP, "deg"),
    Column("RING_INTERCEPT_DISTANCE", "float32", _BP, "km"),
    Column("RING_EMISSION", "float32", _BP, "deg"),
    Column("RING_INCIDENCE", "float32", _BP, "deg", comment=">90 is unlit face"),
    Column("RING_PHASE_ANGLE", "float32", _BP, "deg"),
    Column("IN_SATURN_SHADOW", "bool", _BP, comment="1 if shadowed by Saturn"),
    Column("IN_FRONT_OF_SATURN", "bool", _BP, comment="1 if in front of Saturn"),
)

# Appended to RING_GEOM only when include condition "edge_on" holds
# (ring opening angle < 5 deg). Keeps base TFIELDS at 10 per the proposal.
RING_GEOM_EDGE_ON_COLUMNS: tuple[Column, ...] = (
    Column("EDGE_ON_RADIUS", "float32", _BP, "km"),
    Column("EDGE_ON_ELEVATION", "float32", _BP, "km"),
)

KERNELS_COLUMNS: tuple[Column, ...] = (
    Column("FILENAME", "char", char_len=32, comment="SPICE kernel file name"),
    Column("KERNEL_TYPE", "char", char_len=4, comment="SPK, PCK, LSK, INST, ..."),
)


# --- HDU inventory -----------------------------------------------------------

def hdu_specs(*, rings_in_fov: bool = False, edge_on: bool = False) -> list[HDUSpec]:
    """Return the ordered HDU specs for one product.

    ``rings_in_fov`` toggles the conditional ``RING_GEOM`` HDU; ``edge_on``
    additionally appends the two edge-on ring columns (proposal p.9).
    """
    ring_cols = RING_GEOM_COLUMNS + (RING_GEOM_EDGE_ON_COLUMNS if edge_on else ())
    specs = [
        HDUSpec("PRIMARY", "PRIMARY", "singleton",
                description="Calibrated spectral cube (NX, NY, NZ)."),
        HDUSpec("RAW_COUNTS", "IMAGE", "singleton",
                description="Raw detector counts, signed int16/int32 (NX, NY, NZ)."),
        HDUSpec("CAL_FACTOR", "IMAGE", "singleton",
                description=f"Calibration factor (NX, NY); NULL={CAL_FACTOR_NULL:g}."),
        HDUSpec("WAVELENGTH", "IMAGE", "singleton",
                description="Centre wavelengths of the spectral samples (NX)."),
        HDUSpec("SC_GEOM", "BINTABLE", "per_body", columns=SC_GEOM_COLUMNS,
                description="Per-body spacecraft/solar geometry (one row per body)."),
        HDUSpec("BODY_GEOM", "BINTABLE", "per_resolved_body", columns=BODY_GEOM_COLUMNS,
                description="Per-resolved-body surface backplanes."),
        HDUSpec("GENERAL_GEOM", "BINTABLE", "singleton", columns=GENERAL_GEOM_COLUMNS,
                description="Body-independent backplanes + TIME_ET (absorbs old TIME HDU)."),
    ]
    if rings_in_fov:
        specs.append(
            HDUSpec("RING_GEOM", "BINTABLE", "singleton", include="rings_in_fov",
                    columns=ring_cols, description="Ring-plane backplanes.")
        )
    specs.append(
        HDUSpec("KERNELS", "ASCII_TABLE", "per_body", columns=KERNELS_COLUMNS,
                description="SPICE kernels used to compute the geometry.")
    )
    return specs


# --- primary-header keyword inventory ---------------------------------------

@dataclass(frozen=True)
class Keyword:
    name: str
    kind: str  # "str" | "int" | "float" | "utc" | "date"
    unit: str | None = None
    comment: str = ""


# Promoted CONFIG quantities + identification, in proposal order (p.1-2).
PRIMARY_KEYWORDS: tuple[Keyword, ...] = (
    Keyword("FILENAME", "str", comment="Name of this file"),
    Keyword("PROD_ID", "str", comment="PDS product ID"),
    Keyword("DATE", "date", comment="Date this file was written"),
    Keyword("MISSION", "str", comment="Mission name"),
    Keyword("INSTRUME", "str", comment="Instrument"),
    Keyword("VERSION", "float", comment="File version number"),
    Keyword("OBS_ID", "str", comment="Observation ID"),
    Keyword("MPHASE", "str", comment="Mission phase"),
    Keyword("TARGET", "str", comment="Primary target name"),
    Keyword("ORBNUM", "int", comment="Orbit (REV) number"),
    Keyword("OBS_ET", "float", "s", "Observation start ET (J2000)"),
    Keyword("END_ET", "float", "s", "Observation stop ET (J2000)"),
    Keyword("OBS_UTC", "utc", comment="Observation start UTC (no time zone)"),
    Keyword("END_UTC", "utc", comment="Observation stop UTC (no time zone)"),
    Keyword("OBS_SCLK", "str", comment="Spacecraft clock start count"),
    Keyword("END_SCLK", "str", comment="Spacecraft clock stop count"),
    Keyword("CHANNEL", "str", comment="FUV or EUV channel"),
    Keyword("IMG_XMIN", "int", comment="Window min index, spectral axis"),
    Keyword("IMG_XMAX", "int", comment="Window max index, spectral axis"),
    Keyword("IMG_YMIN", "int", comment="Window min index, slit axis"),
    Keyword("IMG_YMAX", "int", comment="Window max index, slit axis"),
    Keyword("IMG_XBIN", "int", comment="Binning factor, spectral axis"),
    Keyword("IMG_YBIN", "int", comment="Binning factor, slit axis"),
    Keyword("INT_TIME", "float", "s", "Integration time"),
    Keyword("SLITANGL", "float", "deg", "Slit angle projected on sky"),
    Keyword("UNIT", "str", comment="Calibrated units of the data array"),
    Keyword("PIPESTAT", "str", comment="GEOMETRY_ONLY or CALIBRATED"),
)


def window_height(img_ymin: int, img_ymax: int, img_ybin: int = 1) -> int:
    """Window slit height NY from the IMG_Y bounds (proposal: windowed-only).

    ``IMG_YMAX`` is the slit *max* index (proposal comment "min" is a typo).
    """
    return (img_ymax - img_ymin + 1) // img_ybin
