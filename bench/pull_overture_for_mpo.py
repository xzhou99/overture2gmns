"""Download + convert an Overture network for an MPO QA subarea."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from config import LINK_TYPES, MODES
from mpo_config import mpo_out_dir

# Urban-core QA subareas (west, south, east, north).
SUBAREAS = {
    "arc_atlanta": (-84.60, 33.55, -84.20, 33.95),   # I-285 perimeter + margin
    "trm_triangle": (-79.10, 35.70, -78.40, 36.15),  # Raleigh-Durham-Chapel Hill
    "nvta": (-77.55, 38.70, -77.05, 39.05),          # Arlington-Fairfax-Tysons core
}


def run(name: str) -> None:
    import overture2gmns as o2g

    bbox = SUBAREAS[name]
    raw = mpo_out_dir(name) / "overture_raw"
    out = mpo_out_dir(name) / "overture2gmns"

    started = time.perf_counter()
    segment = raw / "segment.parquet"
    connector = raw / "connector.parquet"
    if not (segment.exists() and connector.exists()):
        files = o2g.downloadOvertureData(bbox, raw)
        segment, connector = files["segment"], files["connector"]
    download_s = time.perf_counter() - started

    started = time.perf_counter()
    net = o2g.getNetFromFile(segment, connector, mode_types=MODES, link_types=LINK_TYPES)
    o2g.fillLinkAttributesWithDefaultValues(
        net, default_lanes=True, default_speed=True, default_capacity=True
    )
    o2g.outputNetToCSV(net, out)
    print(f"[pull:{name}] bbox={bbox} {net.number_of_nodes} nodes, {net.number_of_links} links "
          f"(download {download_s:.0f}s, convert {time.perf_counter()-started:.0f}s) -> {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("network", choices=sorted(SUBAREAS))
    run(parser.parse_args().network)
