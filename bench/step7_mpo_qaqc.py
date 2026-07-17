"""Step 7: QA/QC an open MPO GMNS network (ARC Atlanta, TRMG2).

Produces per-network:
  - structure summary (counts, connector share, class breakdown, units check)
  - a lon/lat normalized copy (node.csv/link.csv in EPSG:4326) for map matching
  - gmns-ready quick_check + validate_network reports
  - dtalite_qa (taplite4mpo) validation verdict
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mpo_config import MPO_NETWORKS, mpo_out_dir
from step4_gmns_ready import run_check

csv.field_size_limit(10_000_000)


def _read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def _f(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _reproject_wkt(wkt: str, transformer) -> str:
    if not wkt.startswith("LINESTRING"):
        return wkt
    body = wkt[wkt.index("(") + 1: wkt.rindex(")")]
    pairs = []
    for token in body.split(","):
        x, y = (float(v) for v in token.split()[:2])
        lon, lat = transformer.transform(x, y)
        pairs.append(f"{lon:.6f} {lat:.6f}")
    return "LINESTRING (" + ", ".join(pairs) + ")"


def normalize_to_lonlat(name: str) -> Path:
    """Write a lon/lat copy of the MPO network for map matching / bbox use."""
    spec = MPO_NETWORKS[name]
    out = mpo_out_dir(name) / "lonlat"
    out.mkdir(parents=True, exist_ok=True)

    transformer = None
    if spec["crs_epsg"] != 4326:
        from pyproj import Transformer

        transformer = Transformer.from_crs(spec["crs_epsg"], 4326, always_xy=True)

    nodes = _read_csv(spec["folder"] / "node.csv")
    with (out / "node.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["node_id", "zone_id", "x_coord", "y_coord"])
        for row in nodes:
            x, y = _f(row["x_coord"]), _f(row["y_coord"])
            if transformer:
                x, y = transformer.transform(x, y)
            writer.writerow([row["node_id"], row.get("zone_id", ""), f"{x:.6f}", f"{y:.6f}"])

    links = _read_csv(spec["folder"] / "link.csv")
    keep = ["link_id", "from_node_id", "to_node_id", "lanes", "capacity",
            "free_speed", "vdf_length_mi", "geometry", "is_connector", "facility"]
    with (out / "link.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(keep)
        for row in links:
            geometry = row.get("geometry", "")
            if transformer and geometry:
                geometry = _reproject_wkt(geometry, transformer)
            writer.writerow([
                row.get("link_id"), row.get("from_node_id"), row.get("to_node_id"),
                row.get("lanes"), row.get("capacity"), row.get("free_speed"),
                row.get("vdf_length_mi"), geometry,
                int(bool(spec["connector_test"](row))),
                row.get(spec["class_field"], ""),
            ])
    return out


def summarize(name: str) -> dict:
    spec = MPO_NETWORKS[name]
    nodes = _read_csv(spec["folder"] / "node.csv")
    links = _read_csv(spec["folder"] / "link.csv")

    length_to_mi = {"meter": 1 / 1609.344, "mile": 1.0, "foot": 1 / 5280.0}[spec["length_unit"]]
    connectors = 0
    connector_length = 0.0
    total_length = 0.0
    by_class: dict[str, float] = defaultdict(float)
    zones = {row.get("zone_id") for row in nodes if str(row.get("zone_id") or "").strip() not in ("", "0")}

    for row in links:
        length_mi = _f(row.get("vdf_length_mi")) or _f(row.get("length")) * length_to_mi
        total_length += length_mi
        if spec["connector_test"](row):
            connectors += 1
            connector_length += length_mi
        else:
            by_class[str(row.get(spec["class_field"], "")).strip() or "?"] += length_mi

    return {
        "network": name,
        "label": spec["label"],
        "nodes": len(nodes),
        "links": len(links),
        "zones": len(zones),
        "centroid_connectors": connectors,
        "connector_share_of_links": round(connectors / max(len(links), 1), 4),
        "total_length_mi": round(total_length, 0),
        "connector_length_mi": round(connector_length, 0),
        "roadway_length_by_class_mi": {k: round(v, 0) for k, v in sorted(by_class.items())},
        "units": {"length": spec["length_unit"], "speed": spec["speed_unit"],
                  "crs_epsg": spec["crs_epsg"]},
    }


def run(name: str) -> None:
    spec = MPO_NETWORKS[name]
    out = mpo_out_dir(name)
    out.mkdir(parents=True, exist_ok=True)

    summary = summarize(name)
    (out / "structure_summary.json").write_text(json.dumps(summary, indent=2))
    print(f"[step7:{name}] {summary['nodes']} nodes, {summary['links']} links, "
          f"{summary['zones']} zones, {summary['centroid_connectors']} connectors "
          f"({summary['connector_share_of_links']:.0%} of links)")

    lonlat = normalize_to_lonlat(name)
    print(f"[step7:{name}] lon/lat copy -> {lonlat}")

    chunks = [run_check(spec["folder"], check) for check in ("quick_check", "validate_network")]
    (out / "gmns_ready_report.txt").write_text("".join(chunks), encoding="utf-8", errors="replace")

    try:
        from dtalite_qa import validate

        rep = validate.validate(str(spec["folder"]))
        verdict = {"ok": rep.ok, "errors": [str(m) for m in rep.errors][:20],
                   "warnings": [str(m) for m in rep.warnings][:20]}
    except Exception as exc:
        verdict = {"ok": False, "errors": [repr(exc)], "warnings": []}
    (out / "dtalite_qa.json").write_text(json.dumps(verdict, indent=2))
    print(f"[step7:{name}] gmns-ready + dtalite_qa written (qa_ok={verdict['ok']})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("network", choices=sorted(MPO_NETWORKS))
    run(parser.parse_args().network)
