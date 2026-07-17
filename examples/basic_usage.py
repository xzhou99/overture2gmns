"""Minimal osm2gmns-style workflow on the bundled test fixtures."""

from pathlib import Path

import overture2gmns as o2g

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

net = o2g.getNetFromFile(
    FIXTURES / "segments.geojson",
    FIXTURES / "connectors.geojson",
    mode_types=("auto", "bike", "walk"),
)

o2g.fillLinkAttributesWithDefaultValues(net, default_lanes=True, default_capacity=True)
o2g.generateNodeActivityInfo(net)

o2g.outputNetToCSV(net, "gmns_demo_output")
print(f"nodes={net.number_of_nodes} links={net.number_of_links}")
