"""Registry of open MPO GMNS networks used as QA/QC references.

Each entry declares the unit and CRS conventions of the agency network so the
bench can normalize before comparing against osm2gmns/overture2gmns outputs.
"""

from __future__ import annotations

from pathlib import Path

KERNEL_ROOT = Path("C:/source_codes/0_source_code_new/dtalite_with_taplite_Cpp_kernel")

MPO_NETWORKS: dict[str, dict] = {
    "arc_atlanta": {
        "folder": KERNEL_ROOT / "github_taplite" / "examples" / "arc_atlanta" / "gmns",
        "label": "ARC (Atlanta Regional Commission) activity-based model network",
        "crs_epsg": 2240,          # NAD83 / Georgia West (ftUS) -> reproject to 4326
        "length_unit": "meter",    # link.csv 'length' column
        "speed_unit": "kmh",       # link.csv 'free_speed' column
        # Centroid connectors: name column value
        "connector_test": lambda row: str(row.get("name", "")).strip().upper() == "CENTROID CONNECTOR",
        "class_field": "factype",  # ARC facility type code
    },
    "nvta": {
        # AGENCY-RESTRICTED data (bring-your-own): QA outputs stay local.
        "folder": KERNEL_ROOT / "private" / "nvta_internal",
        "label": "NVTA (Northern Virginia) PM 6-mode network (MWCOG-derived)",
        "crs_epsg": 2248,          # NAD83 / Maryland ftUS (MWCOG convention)
        "length_unit": "mile",     # vdf_length_mi authoritative
        "speed_unit": "kmh",       # free_speed km/h + vdf_free_speed_mph dual
        # Centroid connectors: link_type is areatype*100 (+ftype); x00 = connector
        "connector_test": lambda row: str(row.get("link_type", "")).strip().isdigit()
                                      and int(row["link_type"]) % 100 == 0,
        "class_field": "FTYPE",
    },
    "trm_triangle": {
        "folder": KERNEL_ROOT / "4step" / "trmg2_gmns" / "gmns",
        "label": "TRMG2 (Triangle Regional Model G2, NC) network",
        "crs_epsg": 4326,
        "length_unit": "mile",
        "speed_unit": "kmh",       # free_speed 72.4 vs vdf_free_speed_mph 45
        "connector_test": lambda row: str(row.get("link_type_name", "")).strip().upper() == "CC",
        "class_field": "link_type_name",
    },
}


def mpo_out_dir(name: str) -> Path:
    return Path(__file__).resolve().parent / "out" / "mpo" / name
