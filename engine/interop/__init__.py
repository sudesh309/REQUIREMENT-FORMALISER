"""Interop, automation and reporting (System Composer style).

- ``tables``        architecture <-> tables (ZIP of CSV / .xlsx) and ``ModelBuilder``
- ``xlsx``          stdlib SpreadsheetML / CSV containers, safe XML parsing
- ``report``        HTML system architecture report
- ``diff``          model comparison and three-way merge of project JSON
- ``sysml_export``  SysML v2 textual notation export (re-parsable by ``engine.parse``)
- ``xmi_import``    SysML 1.x XMI 2.5.1 (Cameo / MagicDraw) import
- ``checks``        Model Advisor style checks (registered validator rules) + runner

See docs/features/interop.md.
"""
from __future__ import annotations

from .common import InteropError, load_feature_modules, register_table_kind

# Every feature's kinds, link kinds and codecs are registered before any interop
# operation runs, so imports and exports never change the codec set midway.
load_feature_modules()

from .tables import (  # noqa: E402
    ImportReport, ModelBuilder, export_tables, export_tables_file, import_tables,
    read_tables_file, register_reference_attribute, tables_to_project,
)
from .xlsx import read_csv_zip, read_xlsx, safe_xml, write_csv_zip, write_xlsx  # noqa: E402

__all__ = [
    "InteropError", "load_feature_modules", "register_table_kind", "register_reference_attribute",
    "ImportReport", "ModelBuilder", "export_tables", "export_tables_file", "import_tables",
    "read_tables_file", "tables_to_project",
    "read_csv_zip", "read_xlsx", "safe_xml", "write_csv_zip", "write_xlsx",
]
