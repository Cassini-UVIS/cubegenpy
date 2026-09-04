"""Draft PDS4 label generation.

Intentionally a *stub* for this draft: it emits a small, well-formed XML file
that enumerates the FITS HDUs as ``File_Area_Observational`` entries with their
descriptions. It is **not** schema-valid PDS4 and is not meant to be — the focus
of the draft is the FITS file. Swap this for the full ``lxml`` builder (porting
``fits_writer2/uvis_fits_writer/pds4_label_creator.py``) once the layout and
LIDVID scheme are settled.

PDS4 label structure, from the MAVEN IUVS precedent
---------------------------------------------------
IUVS is the most thorough FITS-in-PDS4 archive we found; its labels were read
directly (l1b/limb, 18 HDUs, 2456-line label) and are the model to follow:

* **One** ``File_Area_Observational`` for the whole FITS file, with **every** HDU
  described -- a ``Header`` object immediately followed by its data object, in
  file order, each with an explicit byte ``offset``. 18 HDUs -> 18 Header + 18
  data objects. ``local_identifier`` is systematically ``header_<EXTNAME>`` /
  ``data_<EXTNAME>``, which makes the pairing machine-checkable.
* Every ``Header`` carries ``parsing_standard_id`` = ``FITS 3.0``.
* Image HDUs use the specialised ``Array_3D_Spectrum``, not bare ``Array_3D``.

.. warning::
   **FITS ``TDIM`` maps to nested ``Group_Field_Binary`` in REVERSED axis
   order.** IUVS's ``PIXEL_VEC`` is ``TFORM='105D'``, ``TDIM='(5,7,3)'`` --
   fastest axis first -- and its label nests ``repetitions`` 3, then 7, then 5,
   slowest outermost, with the scalar ``Field_Binary`` innermost. Getting this
   backwards still validates but describes the wrong memory layout. Our
   backplanes are ``(5, NY, NZ, NT)``, so they nest NT -> NZ -> NY -> 5.

.. warning::
   **Validate against the Schematron, not just the XSD.** The ``data_type``
   enumeration lives in the ``.sch``; in the ``.xsd`` every field type is only a
   1-255 character string, so ``xmllint --schema`` accepts a garbage data_type.

Booleans: PDS4 has no binary boolean encoding, and ``ASCII_Boolean`` -- though a
legal ``data_type`` on ``Field_Binary`` -- permits ``true``/``false``/``1``/``0``
and so misdescribes FITS ``'L'`` bytes (``T``/``F``/0x00) while still validating.
IUVS avoids ``'L'`` entirely, using int16 flags. See the plan's C.9.
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
