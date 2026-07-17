"""Step 9: tokenize a GMNS freeway subnetwork (token2net 'reading' direction).

Levels:
  L0 junction tokens  — MERGE / DIVERGE on mainline gores
  L1 ramp tokens      — LOOP / SEMI_DIRECT / DIRECTIONAL chains with length,
                        total heading change, and endpoint context (service
                        ramp vs freeway-to-freeway)
  L2 interchange motifs — proximity clusters of ramps classified as
                        SYSTEM_* / CLOVERLEAF / PARCLO_n / DIAMOND_4 / PARTIAL_n

Outputs per network: tokens.json, token_histogram.md. Cross-network diff via
--diff mode. Ramp identification: overture2gmns carries subclass 'link' in
facility_type; osm2gmns 1.0.x collapses ramps into facility_type='motorway'
(gotcha #1), so an osm heuristic (short motorway chains touching arterials)
is applied and flagged as approximate.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

csv.field_size_limit(10_000_000)

RAMP_MAX_MILES = 1.5           # heuristic cap for osm ramp chains
LOOP_TURN_DEG = 210.0
DIRECTIONAL_TURN_DEG = 120.0
INTERCHANGE_RADIUS_M = 500.0
WEAVE_MAX_MILES = 0.5
METERS_PER_DEG_LAT = 111_320.0


def _read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def _f(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


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


def _meters(a, b) -> float:
    mean_lat = math.radians((a[1] + b[1]) / 2.0)
    dx = (b[0] - a[0]) * METERS_PER_DEG_LAT * math.cos(mean_lat)
    dy = (b[1] - a[1]) * METERS_PER_DEG_LAT
    return math.hypot(dx, dy)


def _bearing(a, b) -> float:
    mean_lat = math.radians((a[1] + b[1]) / 2.0)
    return math.degrees(math.atan2((b[0] - a[0]) * math.cos(mean_lat), b[1] - a[1]))


def _base_class(row: dict) -> str:
    for key in ("facility_type", "overture_class", "link_type_name"):
        value = str(row.get(key) or "").strip().lower()
        if value:
            return value
    return "?"


class FreewayTokenizer:
    def __init__(self, folder: Path):
        self.folder = folder
        self.links = _read_csv(folder / "link.csv")
        self.osm_heuristic_used = False
        self._classify_links()

    # ---------------------------------------------------------- classify --
    def _classify_links(self) -> None:
        self.mainline: list[dict] = []
        self.ramps: list[dict] = []
        other_nodes: set[str] = set()
        motorway_rows: list[dict] = []

        has_explicit_ramps = any("motorway_link" in _base_class(r) for r in self.links)
        for row in self.links:
            cls = _base_class(row)
            row["_coords"] = _coords(row.get("geometry", ""))
            if not row["_coords"]:
                continue
            row["_miles"] = _f(row.get("vdf_length_mi")) or sum(
                _meters(a, b) for a, b in zip(row["_coords"], row["_coords"][1:])) / 1609.344
            if "motorway_link" in cls:
                self.ramps.append(row)
            elif cls.startswith("motorway"):
                motorway_rows.append(row)
            else:
                other_nodes.add(str(row["from_node_id"]))
                other_nodes.add(str(row["to_node_id"]))

        if has_explicit_ramps:
            self.mainline = motorway_rows
            return

        # osm2gmns 1.0.x collapses ramps into 'motorway' — heuristic split:
        # walk degree-2 chains of motorway links; a chain touching an arterial
        # node and shorter than RAMP_MAX_MILES is a ramp chain.
        self.osm_heuristic_used = True
        chains = _chains(motorway_rows)
        for chain in chains:
            ends = {chain[0]["_chain_ends"][0], chain[-1]["_chain_ends"][1]}
            miles = sum(r["_miles"] for r in chain)
            if miles <= RAMP_MAX_MILES and ends & other_nodes:
                self.ramps.extend(chain)
            else:
                self.mainline.extend(chain)

    # -------------------------------------------------------------- L0 ----
    def junction_tokens(self) -> list[dict]:
        main_out = defaultdict(list)
        main_in = defaultdict(list)
        for row in self.mainline:
            main_out[str(row["from_node_id"])].append(row)
            main_in[str(row["to_node_id"])].append(row)
        ramp_out = defaultdict(list)
        ramp_in = defaultdict(list)
        for row in self.ramps:
            ramp_out[str(row["from_node_id"])].append(row)
            ramp_in[str(row["to_node_id"])].append(row)

        tokens = []
        for node in set(main_out) | set(main_in):
            n_ramp_in = len(ramp_in.get(node, ()))
            n_ramp_out = len(ramp_out.get(node, ()))
            if not (n_ramp_in or n_ramp_out):
                continue
            xy = None
            rows = main_in.get(node) or main_out.get(node)
            if rows:
                geometry = rows[0]["_coords"]
                xy = geometry[-1] if main_in.get(node) else geometry[0]
            kind = "MERGE" if n_ramp_in and not n_ramp_out else (
                "DIVERGE" if n_ramp_out and not n_ramp_in else "MERGE_DIVERGE")
            tokens.append({"token": kind, "node": node, "xy": xy,
                           "ramp_in": n_ramp_in, "ramp_out": n_ramp_out})
        return tokens

    # -------------------------------------------------------------- L1 ----
    def ramp_tokens(self) -> list[dict]:
        mainline_nodes = set()
        for row in self.mainline:
            mainline_nodes.add(str(row["from_node_id"]))
            mainline_nodes.add(str(row["to_node_id"]))

        tokens = []
        for chain in _chains(self.ramps):
            coords: list[tuple[float, float]] = []
            for row in chain:
                pts = row["_coords"]
                coords.extend(pts if not coords or pts[0] == coords[-1] else pts)
            if len(coords) < 3:
                continue
            miles = sum(r["_miles"] for r in chain)
            bearings = [_bearing(a, b) for a, b in zip(coords, coords[1:]) if _meters(a, b) > 1]
            turn = 0.0
            for b1, b2 in zip(bearings, bearings[1:]):
                delta = (b2 - b1 + 180) % 360 - 180
                turn += delta
            start, end = chain[0]["_chain_ends"][0], chain[-1]["_chain_ends"][1]
            start_on = start in mainline_nodes
            end_on = end in mainline_nodes
            ff = start_on and end_on
            shape = ("LOOP" if abs(turn) >= LOOP_TURN_DEG else
                     "DIRECTIONAL" if abs(turn) <= DIRECTIONAL_TURN_DEG else "SEMI_DIRECT")
            # Anchor at the gore (mainline-touching end); interior pieces
            # anchor at their midpoint. Clustering on gores keeps adjacent
            # interchanges separate (midpoint clustering chained them in v1).
            anchor = (coords[0] if start_on else
                      coords[-1] if end_on else coords[len(coords) // 2])
            tokens.append({
                "token": f"RAMP_{shape}",
                "kind": "FF" if ff else "SERVICE",
                "gores": int(start_on) + int(end_on),
                "miles": round(miles, 3),
                "turn_deg": round(turn, 1),
                "mid_xy": coords[len(coords) // 2],
                "anchor_xy": anchor,
                "start": start, "end": end,
            })
        return tokens

    # -------------------------------------------------------------- L2 ----
    def interchange_tokens(self, ramps: list[dict]) -> list[dict]:
        n = len(ramps)
        parent = list(range(n))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for i in range(n):
            for j in range(i + 1, n):
                if _meters(ramps[i]["anchor_xy"], ramps[j]["anchor_xy"]) <= INTERCHANGE_RADIUS_M:
                    parent[find(i)] = find(j)

        clusters = defaultdict(list)
        for i in range(n):
            clusters[find(i)].append(ramps[i])

        tokens = []
        for members in clusters.values():
            # Size an interchange by GORE CONNECTIONS (mainline-touching ramp
            # ends), not chain segments — converter splits inflate segments.
            gores = sum(r["gores"] for r in members)
            gore_members = [r for r in members if r["gores"]]
            loops = sum(1 for r in gore_members if r["token"] == "RAMP_LOOP")
            ff = sum(1 for r in gore_members if r["kind"] == "FF")
            count = len(members)
            if gores < 2:
                motif = "SLIP_RAMP"
            elif ff >= max(2, len(gore_members) // 2):
                motif = ("SYSTEM_CLOVERLEAF" if loops >= 2 else
                         "SYSTEM_DIRECTIONAL" if loops == 0 else "SYSTEM_HYBRID")
            elif loops >= 3:
                motif = "CLOVERLEAF"
            elif loops >= 1:
                motif = f"PARCLO_G{gores}"
            elif gores >= 8:
                motif = f"MAJOR_SERVICE_G{gores}"
            elif gores >= 4:
                motif = "DIAMOND_LIKE_G4" if gores == 4 else f"SERVICE_G{gores}"
            else:
                motif = f"PARTIAL_G{gores}"
            cx = sum(r["anchor_xy"][0] for r in members) / count
            cy = sum(r["anchor_xy"][1] for r in members) / count
            tokens.append({"token": motif, "gores": gores, "chains": count,
                           "loops": loops, "ff_ramps": ff,
                           "xy": (round(cx, 5), round(cy, 5)),
                           "total_ramp_miles": round(sum(r["miles"] for r in members), 2)})
        return tokens


def _chains(rows: list[dict]) -> list[list[dict]]:
    """Group directed links into undirected degree-2 chains; annotate ends."""
    degree = Counter()
    by_node = defaultdict(list)
    seen_pairs = set()
    for row in rows:
        a, b = str(row["from_node_id"]), str(row["to_node_id"])
        row["_chain_ends"] = (a, b)
        pair = (min(a, b), max(a, b))
        if pair in seen_pairs:
            continue  # count reverse twin once for degree purposes
        seen_pairs.add(pair)
        degree[a] += 1
        degree[b] += 1
    for row in rows:
        by_node[str(row["from_node_id"])].append(row)

    visited = set()
    chains = []
    for row in rows:
        if id(row) in visited:
            continue
        chain = [row]
        visited.add(id(row))
        # extend forward through degree-2 nodes
        while True:
            tail = chain[-1]["_chain_ends"][1]
            if degree[tail] != 2:
                break
            nxt = [r for r in by_node.get(tail, ()) if id(r) not in visited
                   and r["_chain_ends"][1] != chain[-1]["_chain_ends"][0]]
            if not nxt:
                break
            visited.add(id(nxt[0]))
            chain.append(nxt[0])
        chains.append(chain)
    return chains


def run(folder: Path, out_dir: Path, label: str) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    tokenizer = FreewayTokenizer(folder)
    junctions = tokenizer.junction_tokens()
    ramps = tokenizer.ramp_tokens()
    interchanges = tokenizer.interchange_tokens(ramps)

    hist = {
        "junctions": dict(Counter(t["token"] for t in junctions)),
        "ramps": dict(Counter(f"{t['token']}({t['kind']})" for t in ramps)),
        "interchanges": dict(Counter(t["token"] for t in interchanges)),
    }
    payload = {
        "network": label, "folder": str(folder),
        "mainline_links": len(tokenizer.mainline), "ramp_links": len(tokenizer.ramps),
        "osm_ramp_heuristic": tokenizer.osm_heuristic_used,
        "histogram": hist,
        "interchanges": sorted(interchanges, key=lambda t: -t["gores"]),
        "junction_tokens": junctions,
        "ramp_tokens": ramps,
    }
    (out_dir / f"tokens_{label}.json").write_text(json.dumps(payload, indent=1))

    lines = [f"# Token histogram — {label}",
             f"(mainline links {len(tokenizer.mainline)}, ramp links {len(tokenizer.ramps)}"
             + (", osm ramp heuristic)" if tokenizer.osm_heuristic_used else ")"), ""]
    for level, counts in hist.items():
        lines.append(f"## {level}")
        for token, count in sorted(counts.items(), key=lambda kv: -kv[1]):
            lines.append(f"- {token}: {count}")
        lines.append("")
    lines.append("## Largest interchanges")
    for t in payload["interchanges"][:12]:
        lines.append(f"- {t['token']} @ {t['xy']} gores={t['gores']} loops={t['loops']} ff={t['ff_ramps']}")
    (out_dir / f"token_histogram_{label}.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"[step9:{label}] mainline={len(tokenizer.mainline)} ramps={len(tokenizer.ramps)} "
          f"junctions={hist['junctions']} interchanges={hist['interchanges']}")
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--network", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    run(args.network, args.out, args.label)
