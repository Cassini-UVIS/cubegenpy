"""Draft PDS4 label generation.

Intentionally a *stub* for this draft: it emits a small, well-formed XML file
that enumerates the FITS HDUs as ``File_Area_Observational`` entries with their
descriptions. It is **not** schema-valid PDS4 and is not meant to be — the focus
of the draft is the FITS file. Swap this for the full ``lxml`` builder (porting
``fits_writer2/uvis_fits_writer/pds4_label_creator.py``) once the layout and
LIDVID scheme are settled.
"""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

from astropy.io import fits


def build_draft_label(product_id: str, hdulist: fits.HDUList) -> ET.ElementTree:
    root = ET.Element("Product_Observational")
    root.set("draft", "true")

    ident = ET.SubElement(root, "Identification_Area")
    ET.SubElement(ident, "logical_identifier").text = (
        f"urn:nasa:pds:cassini_uvis:data:{product_id.lower()}"
    )
    ET.SubElement(ident, "version_id").text = "1.0"
    ET.SubElement(ident, "title").text = f"Cassini UVIS product {product_id}"
    ET.SubElement(ident, "product_class").text = "Product_Observational"

    area = ET.SubElement(root, "File_Area_Observational")
    fobj = ET.SubElement(area, "File")
    ET.SubElement(fobj, "file_name").text = f"{product_id}.fits"

    for index, hdu in enumerate(hdulist):
        name = hdu.header.get("EXTNAME", "PRIMARY" if index == 0 else f"HDU{index}")
        node = ET.SubElement(area, "HDU_Stub")
        ET.SubElement(node, "local_identifier").text = name
        ET.SubElement(node, "hdu_index").text = str(index)
        kind = type(hdu).__name__
        ET.SubElement(node, "fits_class").text = kind
        if getattr(hdu, "data", None) is not None and hasattr(hdu.data, "shape"):
            ET.SubElement(node, "array_shape").text = ",".join(map(str, hdu.data.shape))

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    return tree


def write_draft_label(out_dir: str | Path, product_id: str,
                      hdulist: fits.HDUList) -> Path:
    out_path = Path(out_dir) / f"{product_id}.xml"
    build_draft_label(product_id, hdulist).write(
        out_path, encoding="utf-8", xml_declaration=True
    )
    return out_path
