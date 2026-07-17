"""Step 3: self-comparison of osm2gmns vs overture2gmns GMNS outputs.

Normalizes units (osm2gmns emits meters / km/h; overture2gmns emits miles /
mph), aggregates by road class, and correlates spatial link-length density on
a grid. Writes comparison_report.json and comparison_report.md per region.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import osm_dir, overture_dir, region_dir, REGIONS

KMH_TO_MPH = 0.621371192237334
METERS_TO_MILES = 1.0 / 1609.344
GRID_DEG = 0.005  # ~500 m cells


def _read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def _f(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _base_class(row: dict) -> str:
    # overture2gmns keeps the raw class; osm2gmns uses facility_type/link_type_name.
    for key in ("overture_class", "facility_type", "link_type_name"):
        value = (row.get(key) or "").strip().lower()
        if value:
            return value.split("_")[0] if key == "facility_type" else value
    return "unknown"


def _geometry_midpoint(row: dict, nodes_xy: dict, cache: dict) -> tuple[float, float] | None:
    from_id, to_id = row.get("from_node_id"), row.get("to_node_id")
    a = nodes_xy.get(str(from_id))
    b = nodes_xy.get(str(to_id))
    if a and b:
        return ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
    return None


def summarize(network_folder: Path) -> dict:
    meta = {}
    meta_file = network_folder / "build_meta.json"
    if meta_file.exists():
        meta = json.loads(meta_file.read_text())
    tool = meta.get("tool") or ("overture2gmns" if "overture" in network_folder.name else "osm2gmns")
    length_scale = METERS_TO_MILES if tool == "osm2gmns" else 1.0
    speed_scale = KMH_TO_MPH if tool == "osm2gmns" else 1.0

    nodes = _read_csv(network_folder / "node.csv")
    links = _read_csv(network_folder / "link.csv")
    nodes_xy = {str(row["node_id"]): (_f(row["x_coord"]), _f(row["y_coord"])) for row in nodes}

    length_by_class: dict[str, float] = defaultdict(float)
    speed_len_by_class: dict[str, float] = defaultdict(float)
    lanes_len_by_class: dict[str, float] = defaultdict(float)
    grid: dict[tuple[int, int], float] = defaultdict(float)
    out_degree: Counter = Counter()
    adjacency: dict[str, set[str]] = defaultdict(set)
    total_length = 0.0

    for row in links:
        length = _f(row.get("length")) * length_scale
        speed = _f(row.get("free_speed")) * speed_scale
        lanes = _f(row.get("lanes"), 1.0)
        cls = _base_class(row)
        total_length += length
        length_by_class[cls] += length
        speed_len_by_class[cls] += speed * length
        lanes_len_by_class[cls] += lanes * length
        out_degree[str(row.get("from_node_id"))] += 1
        adjacency[str(row.get("from_node_id"))].add(str(row.get("to_node_id")))
        adjacency[str(row.get("to_node_id"))].add(str(row.get("from_node_id")))
        mid = _geometry_midpoint(row, nodes_xy, {})
        if mid:
            grid[(int(mid[0] / GRID_DEG), int(mid[1] / GRID_DEG))] += length

    # Weakly connected components over the undirected adjacency.
    seen: set[str] = set()
    components = []
    for start in adjacency:
        if start in seen:
            continue
        stack, size = [start], 0
        seen.add(start)
        while stack:
            current = stack.pop()
            size += 1
            for neighbor in adjacency[current]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    stack.append(neighbor)
        components.append(size)
    components.sort(reverse=True)

    return {
        "tool": tool,
        "meta": meta,
        "nodes": len(nodes),
        "links": len(links),
        "total_length_mi": round(total_length, 1),
        "length_by_class_mi": {k: round(v, 1) for k, v in sorted(length_by_class.items())},
        "mean_speed_mph_by_class": {
            k: round(speed_len_by_class[k] / v, 1)
            for k, v in length_by_class.items() if v > 0
        },
        "mean_lanes_by_class": {
            k: round(lanes_len_by_class[k] / v, 2)
            for k, v in length_by_class.items() if v > 0
        },
        "mean_out_degree": round(sum(out_degree.values()) / max(len(out_degree), 1), 2),
        "weak_components": len(components),
        "largest_component_share": round(components[0] / max(sum(components), 1), 4) if components else 0.0,
        "grid": {f"{k[0]},{k[1]}": round(v, 4) for k, v in grid.items()},
    }


def _pearson(xs: list[float], ys: list[float]) -> float:
    if len(xs) < 3:
        return float("nan")
    mean_x, mean_y = sum(xs) / len(xs), sum(ys) / len(ys)
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    var_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    var_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    return cov / (var_x * var_y) if var_x and var_y else float("nan")


def grid_stats(a: dict[str, float], b: dict[str, float]) -> dict:
    """Separate coverage difference from per-cell disagreement.

    Correlation over the union of cells punishes coverage mismatch (polygon
    OSM extract vs rectangular Overture bbox); correlation over the common
    cells isolates genuine conversion disagreement.
    """
    union = sorted(set(a) | set(b))
    common = sorted(set(a) & set(b))
    return {
        "cells_osm_only": len(set(a) - set(b)),
        "cells_overture_only": len(set(b) - set(a)),
        "cells_common": len(common),
        "coverage_jaccard": round(len(common) / max(len(union), 1), 4),
        "correlation_union": round(
            _pearson([a.get(c, 0.0) for c in union], [b.get(c, 0.0) for c in union]), 4),
        "correlation_common": round(
            _pearson([a[c] for c in common], [b[c] for c in common]), 4),
    }


def _pct(reference: float, candidate: float) -> str:
    if not reference:
        return "n/a"
    return f"{100.0 * (candidate - reference) / reference:+.1f}%"


def run(region: str) -> Path:
    osm = summarize(osm_dir(region))
    ovr = summarize(overture_dir(region))
    grids = grid_stats(osm.pop("grid"), ovr.pop("grid"))

    report = {"region": region, "osm2gmns": osm, "overture2gmns": ovr, "grid": grids}
    out_json = region_dir(region) / "comparison_report.json"
    out_json.write_text(json.dumps(report, indent=2))

    classes = sorted(set(osm["length_by_class_mi"]) | set(ovr["length_by_class_mi"]))
    lines = [
        f"# {region}: osm2gmns vs overture2gmns",
        "",
        "| metric | osm2gmns | overture2gmns | diff |",
        "|---|---:|---:|---:|",
        f"| nodes | {osm['nodes']} | {ovr['nodes']} | {_pct(osm['nodes'], ovr['nodes'])} |",
        f"| directed links | {osm['links']} | {ovr['links']} | {_pct(osm['links'], ovr['links'])} |",
        f"| total length (mi) | {osm['total_length_mi']} | {ovr['total_length_mi']} | {_pct(osm['total_length_mi'], ovr['total_length_mi'])} |",
        f"| mean out-degree | {osm['mean_out_degree']} | {ovr['mean_out_degree']} | |",
        f"| weak components | {osm['weak_components']} | {ovr['weak_components']} | |",
        f"| largest component share | {osm['largest_component_share']} | {ovr['largest_component_share']} | |",
        f"| grid cells (only / common / only) | {grids['cells_osm_only']} | {grids['cells_common']} common | {grids['cells_overture_only']} |",
        f"| coverage jaccard | | | {grids['coverage_jaccard']} |",
        f"| length correlation (union / common cells) | | | {grids['correlation_union']} / {grids['correlation_common']} |",
        "",
        "## Directed length by road class (mi)",
        "",
        "| class | osm2gmns | overture2gmns | diff |",
        "|---|---:|---:|---:|",
    ]
    for cls in classes:
        a = osm["length_by_class_mi"].get(cls, 0.0)
        b = ovr["length_by_class_mi"].get(cls, 0.0)
        lines.append(f"| {cls} | {a} | {b} | {_pct(a, b)} |")
    lines += [
        "",
        "## Length-weighted mean free speed (mph)",
        "",
        "| class | osm2gmns | overture2gmns |",
        "|---|---:|---:|",
    ]
    for cls in classes:
        lines.append(
            f"| {cls} | {osm['mean_speed_mph_by_class'].get(cls, '-')} "
            f"| {ovr['mean_speed_mph_by_class'].get(cls, '-')} |"
        )
    out_md = region_dir(region) / "comparison_report.md"
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"[step3:{region}] wrote {out_md}")
    print("\n".join(lines[:12]))
    return out_md


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("region", choices=sorted(REGIONS))
    run(parser.parse_args().region)
