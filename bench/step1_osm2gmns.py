"""Step 1: build the reference GMNS network from an OSM extract with osm2gmns."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import LINK_TYPES, MODES, REGIONS, osm_dir


def run(region: str) -> Path:
    spec = REGIONS[region]
    pbf = Path(spec["pbf"])
    if not pbf.exists():
        raise FileNotFoundError(
            f"OSM extract not found: {pbf}. Download it into dev/osmmap/ first."
        )
    import osm2gmns as og

    output = osm_dir(region)
    output.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    net = og.getNetFromFile(str(pbf), mode_types=list(MODES), link_types=list(LINK_TYPES))
    og.fillLinkAttributesWithDefaultValues(
        net, default_lanes=True, default_speed=True, default_capacity=True
    )
    og.generateNodeActivityInfo(net)
    og.outputNetToCSV(net, output_folder=str(output))
    elapsed = time.perf_counter() - started

    meta = {
        "tool": "osm2gmns",
        "version": og.__version__,
        "source": str(pbf),
        "modes": list(MODES),
        "link_types": list(LINK_TYPES),
        "nodes": net.number_of_nodes,
        "links": net.number_of_links,
        "seconds": round(elapsed, 2),
    }
    (output / "build_meta.json").write_text(json.dumps(meta, indent=2))
    print(f"[step1:{region}] {meta['nodes']} nodes, {meta['links']} links in {elapsed:.1f}s -> {output}")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("region", choices=sorted(REGIONS))
    run(parser.parse_args().region)
