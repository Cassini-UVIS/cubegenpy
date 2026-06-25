"""cubegenpy — build PDS4-compliant FITS cubes for Cassini UVIS observations."""

from .build import build_cube
from .demo import make_synthetic_product
from .writer import Dims, build_hdulist, write_product

__all__ = [
    "build_cube",
    "build_hdulist",
    "write_product",
    "Dims",
    "make_synthetic_product",
]
__version__ = "0.1.0"
