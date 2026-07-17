"""Region registry for the osm2gmns vs overture2gmns benchmark environment.

Each region defines the OSM extract to feed osm2gmns and (optionally) a fixed
bbox for the Overture download. When ``bbox`` is None, step 2 derives it from
the node extent of the osm2gmns output so both converters cover the same area.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OSMMAP = ROOT / "dev" / "osmmap"
OUT = ROOT / "bench" / "out"

# Modes and link classes used for the apples-to-apples comparison. Start with
# drivable classes only: TAP assignment is auto-based, and OSM footway/cycleway
# coverage differs too much from Overture's to compare meaningfully in v1.
MODES = ("auto",)
LINK_TYPES = (
    "motorway", "trunk", "primary", "secondary", "tertiary",
    "residential", "unclassified", "living_street",
    # OSM tags ramps as separate *_link highway types; Overture models them as
    # the parent class with subclass=link. Without these, the osm2gmns side
    # drops every ramp and the comparison is unfair (motorway length -60%).
    "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link",
)

REGIONS: dict[str, dict] = {
    "tempe": {
        "pbf": OSMMAP / "tempe.osm.pbf",
        "bbox": None,          # derived from osm2gmns node extent
        "size_class": "small",
    },
    "mag_mpo": {
        "pbf": OSMMAP / "mag_mpo_bbbike.pbf",
        "bbox": None,
        "size_class": "large",
    },
    "arizona": {
        "pbf": OSMMAP / "arizona.pbf",
        "bbox": None,
        "size_class": "xlarge",
    },
    "chicago": {
        "pbf": OSMMAP / "chicago.osm.pbf",
        "bbox": None,
        "size_class": "large",
    },
    # Northern Virginia (BBBike WashingtonDC extract) — NVTA QA companion.
    "nova": {
        "pbf": OSMMAP / "washingtondc.osm.pbf",
        "bbox": None,
        "size_class": "large",
    },
}


def region_dir(region: str) -> Path:
    return OUT / region


def osm_dir(region: str) -> Path:
    return region_dir(region) / "osm2gmns"


def overture_dir(region: str) -> Path:
    return region_dir(region) / "overture2gmns"


def raw_overture_dir(region: str) -> Path:
    return region_dir(region) / "overture_raw"
