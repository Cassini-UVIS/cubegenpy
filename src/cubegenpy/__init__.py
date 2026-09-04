"""cubegenpy — build PDS4-compliant FITS cubes for Cassini UVIS observations."""

from .build import build_cube
from .builder import CubeBuilder
from .calibrate import (
    Background,
    Calibrator,
    CalModel,
    PyuvisCalModel,
    SpicaCalModel,
    StoredCalModel,
    UnitCalModel,
)
from .config import DEFAULT_CONFIG, BuildConfig
from .demo import make_synthetic_product
from .fitsio import read_product
from .product import CubeProduct, ProductInputs
from .sources import FitsReadbackSource, Source, SyntheticSource
from .writer import Dims, build_hdulist, write_product

__all__ = [
    # functional / writer layer
    "build_cube",
    "build_hdulist",
    "write_product",
    "read_product",
    "Dims",
    "make_synthetic_product",
    # OO core
    "CubeBuilder",
    "BuildConfig",
    "DEFAULT_CONFIG",
    "ProductInputs",
    "CubeProduct",
    # calibration
    "Calibrator",
    "Background",
    "CalModel",
    "StoredCalModel",
    "UnitCalModel",
    "PyuvisCalModel",
    "SpicaCalModel",
    # sources
    "Source",
    "SyntheticSource",
    "FitsReadbackSource",
]
__version__ = "0.1.0"
