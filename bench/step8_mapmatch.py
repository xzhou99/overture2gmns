"""Step 8: cross-network QA via map matching (mapmatcher4gmns).

Idea: sample link geometries from network A as synthetic probe traces (points
every ~50 m with heading), then HMM-match them onto network B. If B contains
the same streets, traces match at high rates; failures localize disagreement
(missing facilities, offset geometry, direction errors). This is the same
machinery agencies use to conflate probe data (INRIX/RITIS) onto model
networks, so the match rate doubles as a 'probe-data readiness' score.

Usage:
  python bench/step8_mapmatch.py --probe <folder> --base <folder> --out <folder>
      [--probe-connector-col is_connector] [--per-class 40] [--radius 25]
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

csv.field_size_limit(10_000_000)

METERS_PER_DEG_LAT = 111_320.0
POINT_SPACING_M = 50.0
MIN_TRACE_POINTS = 4


def _read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def _coords(wkt: str) -> list[tuple[float, float]]:
    if not wkt or "(" not in wkt:
        return []
    body = wkt[wkt.index("(") + 1: wkt.rindex(")")]
    out = []
    for token in body.split(","):
        parts = token.split()
        if len(parts) >= 2:
            out.append((float(parts[0]), float(parts[1])))
    return out


def _seg_meters(a: tuple[float, float], b: tuple[float, float]) -> float:
    mean_lat = math.radians((a[1] + b[1]) / 2.0)
    dx = (b[0] - a[0]) * METERS_PER_DEG_LAT * math.cos(mean_lat)
    dy = (b[1] - a[1]) * METERS_PER_DEG_LAT
    return math.hypot(dx, dy)


def _heading(a: tuple[float, float], b: tuple[float, float]) -> float:
    mean_lat = math.radians((a[1] + b[1]) / 2.0)
    dx = (b[0] - a[0]) * math.cos(mean_lat)
    dy = b[1] - a[1]
    return (math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0


def _trace_points(coords: list[tuple[float, float]]) -> list[tuple[float, float, float]]:
    """(lon, lat, heading) every POINT_SPACING_M along the polyline."""
    points = []
    carry = 0.0
    for a, b in zip(coords, coords[1:]):
        seg = _seg_meters(a, b)
        if seg <= 0:
            continue
        heading = _heading(a, b)
        position = carry
        while position < seg:
            t = position / seg
            points.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, heading))
            position += POINT_SPACING_M
        carry = position - seg
    if coords:
        points.append((coords[-1][0], coords[-1][1], _heading(coords[-2], coords[-1]) if len(coords) > 1 else 0.0))
    return points


def _class_of(row: dict) -> str:
    for key in ("facility", "overture_class", "facility_type", "link_type_name", "factype"):
        value = str(row.get(key) or "").strip()
        if value:
            return value.split("_")[0].lower()
    return "?"


def build_probe_csv(
    probe_folder: Path,
    out_csv: Path,
    per_class: int = 40,
    connector_col: str | None = None,
    min_length_m: float = 200.0,
    bbox: tuple[float, float, float, float] | None = None,
    inset: float = 0.02,
) -> dict:
    links = _read_csv(probe_folder / "link.csv")
    if bbox:
        # Inset so probes never run off the edge of the base network's extent.
        west, south, east, north = (bbox[0] + inset, bbox[1] + inset,
                                    bbox[2] - inset, bbox[3] - inset)
    by_class: dict[str, list[dict]] = defaultdict(list)
    for row in links:
        if connector_col and str(row.get(connector_col, "0")).strip() in ("1", "True", "true"):
            continue
        coords = _coords(row.get("geometry", ""))
        if len(coords) < 2:
            continue
        if bbox and not all(west <= x <= east and south <= y <= north for x, y in coords):
            continue
        length_m = sum(_seg_meters(a, b) for a, b in zip(coords, coords[1:]))
        if length_m < min_length_m:
            continue
        row["_coords"] = coords
        by_class[_class_of(row)].append(row)

    picked: list[dict] = []
    for cls, rows in sorted(by_class.items()):
        rows.sort(key=lambda r: str(r.get("link_id", "")))
        step = max(1, len(rows) // per_class)
        picked.extend(rows[::step][:per_class])

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = defaultdict(int)
    with out_csv.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["journey_id", "longitude", "latitude", "heading", "link_class"])
        for row in picked:
            points = _trace_points(row["_coords"])
            if len(points) < MIN_TRACE_POINTS:
                continue
            journey = f"{_class_of(row)}|{row.get('link_id')}"
            counts[_class_of(row)] += 1
            for lon, lat, heading in points:
                writer.writerow([journey, f"{lon:.6f}", f"{lat:.6f}", f"{heading:.1f}", _class_of(row)])
    return dict(counts)


def _patch_pandas_compat() -> None:
    """mapmatcher4gmns 0.1.9 passes infer_datetime_format=, removed in pandas 2+."""
    import pandas as pd

    original = pd.to_datetime
    if getattr(original, "_o2g_patched", False):
        return

    def to_datetime(*args, **kwargs):
        kwargs.pop("infer_datetime_format", None)
        return original(*args, **kwargs)

    to_datetime._o2g_patched = True
    pd.to_datetime = to_datetime


def match(base_folder: Path, probe_csv: Path, out_dir: Path, radius: float = 25.0) -> dict:
    _patch_pandas_compat()
    import mapmatcher4gmns as mm

    network = mm.LoadNetFromCSV(
        node_file=str(base_folder / "node.csv"),
        link_file=str(base_folder / "link.csv"),
        coordinate_type="lonlat",
    )
    matcher = mm.MapMatcher(
        network,
        agent_field="journey_id",
        lng_field="longitude",
        lat_field="latitude",
        time_field=None,
        speed_field=None,
        heading_field="heading",
        search_radius=radius,
        max_candidates=10,
        use_heading=True,
        export_csv=True,
        export_route=True,
        out_dir=str(out_dir),
        verbose=False,
        show_progress=False,
    )
    result_df, info, failures = matcher.match(str(probe_csv))
    return {"result_df": result_df, "info": info, "failures": failures}


def evaluate(probe_csv: Path, out_dir: Path) -> dict:
    """Per-class match rates from the matcher outputs."""
    trace_class: dict[str, str] = {}
    trace_points: dict[str, int] = defaultdict(int)
    for row in _read_csv(probe_csv):
        trace_class[row["journey_id"]] = row["link_class"]
        trace_points[row["journey_id"]] += 1

    matched_points: dict[str, int] = defaultdict(int)
    result_file = out_dir / "matched_result.csv"
    if result_file.exists():
        for row in _read_csv(result_file):
            journey = row.get("journey_id") or row.get("agent_id") or ""
            link_ref = (row.get("link_id") or row.get("matched_link_id") or "").strip()
            if journey and link_ref not in ("", "-1", "None"):
                matched_points[journey] += 1

    per_class: dict[str, dict] = {}
    for journey, cls in trace_class.items():
        entry = per_class.setdefault(cls, {"traces": 0, "matched_traces": 0,
                                           "points": 0, "matched_points": 0})
        entry["traces"] += 1
        entry["points"] += trace_points[journey]
        entry["matched_points"] += matched_points.get(journey, 0)
        if matched_points.get(journey, 0) >= 0.5 * trace_points[journey]:
            entry["matched_traces"] += 1

    total_traces = sum(e["traces"] for e in per_class.values())
    total_matched = sum(e["matched_traces"] for e in per_class.values())
    for entry in per_class.values():
        entry["trace_match_rate"] = round(entry["matched_traces"] / max(entry["traces"], 1), 3)
        entry["point_match_rate"] = round(entry["matched_points"] / max(entry["points"], 1), 3)
    return {
        "traces": total_traces,
        "trace_match_rate": round(total_matched / max(total_traces, 1), 3),
        "per_class": per_class,
    }


def run(probe: Path, base: Path, out: Path, per_class: int, radius: float,
        connector_col: str | None, bbox: tuple[float, float, float, float] | None = None) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    probe_csv = out / "probe_traces.csv"
    counts = build_probe_csv(probe, probe_csv, per_class=per_class,
                             connector_col=connector_col, bbox=bbox)
    print(f"[step8] probes from {probe.name}: {sum(counts.values())} traces {dict(counts)}")

    match(base, probe_csv, out, radius=radius)
    report = evaluate(probe_csv, out)
    report["probe"] = str(probe)
    report["base"] = str(base)
    report["search_radius_m"] = radius
    (out / "mapmatch_report.json").write_text(json.dumps(report, indent=2))
    print(f"[step8] {probe.name} -> {base.name}: trace match rate "
          f"{report['trace_match_rate']:.1%} over {report['traces']} traces")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", type=Path, required=True, help="network sampled as traces")
    parser.add_argument("--base", type=Path, required=True, help="network matched onto")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--per-class", type=int, default=40)
    parser.add_argument("--radius", type=float, default=25.0)
    parser.add_argument("--probe-connector-col", default=None)
    parser.add_argument("--bbox", nargs=4, type=float, default=None, metavar=("W", "S", "E", "N"))
    args = parser.parse_args()
    run(args.probe, args.base, args.out, args.per_class, args.radius,
        args.probe_connector_col, tuple(args.bbox) if args.bbox else None)
