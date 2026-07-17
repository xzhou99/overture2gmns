"""Step 2: build the candidate GMNS network from Overture cloud data.

The download bbox defaults to the node extent of the osm2gmns output so both
converters cover the same area. Raw Overture files are cached in
``overture_raw/`` so repeated conversions don't re-download.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from config import LINK_TYPES, MODES, REGIONS, osm_dir, overture_dir, raw_overture_dir


def bbox_from_node_csv(node_csv: Path) -> tuple[float, float, float, float]:
    xs, ys = [], []
    with node_csv.open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            xs.append(float(row["x_coord"]))
            ys.append(float(row["y_coord"]))
    if not xs:
        raise ValueError(f"No nodes in {node_csv}")
    return (min(xs), min(ys), max(xs), max(ys))


def run(region: str, use_cache: bool = True) -> Path:
    import overture2gmns as o2g

    spec = REGIONS[region]
    bbox = spec["bbox"]
    if bbox is None:
        node_csv = osm_dir(region) / "node.csv"
        if not node_csv.exists():
            raise FileNotFoundError(
                f"{node_csv} missing - run step1_osm2gmns.py {region} first, "
                "or set an explicit bbox in config.py"
            )
        bbox = bbox_from_node_csv(node_csv)
        print(f"[step2:{region}] bbox from osm2gmns extent: {tuple(round(v, 4) for v in bbox)}")

    raw = raw_overture_dir(region)
    cached = None
    for extension in ("parquet", "geojson"):
        segment_file = raw / f"segment.{extension}"
        connector_file = raw / f"connector.{extension}"
        if segment_file.exists() and connector_file.exists():
            cached = (segment_file, connector_file)
            break

    started = time.perf_counter()
    if use_cache and cached:
        segment_file, connector_file = cached
        print(f"[step2:{region}] reusing cached download: {segment_file.name}")
    else:
        files = o2g.downloadOvertureData(bbox, raw)
        segment_file, connector_file = files["segment"], files["connector"]
    download_seconds = time.perf_counter() - started

    started = time.perf_counter()
    net = o2g.getNetFromFile(
        segment_file,
        connector_file,
        mode_types=MODES,
        link_types=LINK_TYPES,
    )
    o2g.fillLinkAttributesWithDefaultValues(
        net, default_lanes=True, default_speed=True, default_capacity=True
    )
    o2g.generateNodeActivityInfo(net)
    convert_seconds = time.perf_counter() - started

    output = overture_dir(region)
    output.mkdir(parents=True, exist_ok=True)
    o2g.outputNetToCSV(net, output)

    meta = {
        "tool": "overture2gmns",
        "version": o2g.__version__,
        "bbox": list(bbox),
        "modes": list(MODES),
        "link_types": list(LINK_TYPES),
        "nodes": net.number_of_nodes,
        "links": net.number_of_links,
        "download_seconds": round(download_seconds, 2),
        "convert_seconds": round(convert_seconds, 2),
    }
    (output / "build_meta.json").write_text(json.dumps(meta, indent=2))
    print(f"[step2:{region}] {meta['nodes']} nodes, {meta['links']} links "
          f"(download {download_seconds:.1f}s, convert {convert_seconds:.1f}s) -> {output}")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("region", choices=sorted(REGIONS))
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args()
    run(args.region, use_cache=not args.no_cache)
