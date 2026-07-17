"""Step 6: render both networks side by side (and overlaid) for visual diffing.

Produces bench/out/<region>/side_by_side.png with three panels:
osm2gmns, overture2gmns, and an overlay (reference gray, candidate red) that
makes coverage gaps pop out.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import osm_dir, overture_dir, region_dir, REGIONS

CLASS_COLORS = {
    "motorway": "#d62728", "trunk": "#ff7f0e", "primary": "#e6b117",
    "secondary": "#2ca02c", "tertiary": "#17becf", "residential": "#9ca3af",
    "unclassified": "#c7c9cf", "living_street": "#c7c9cf",
}


def _segments(network_folder: Path) -> tuple[list[list[tuple[float, float]]], list[str]]:
    nodes: dict[str, tuple[float, float]] = {}
    with (network_folder / "node.csv").open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            nodes[str(row["node_id"])] = (float(row["x_coord"]), float(row["y_coord"]))

    lines, colors = [], []
    with (network_folder / "link.csv").open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            geometry = row.get("geometry") or ""
            coords: list[tuple[float, float]] = []
            if geometry.startswith("LINESTRING"):
                body = geometry[geometry.index("(") + 1: geometry.rindex(")")]
                for pair in body.split(","):
                    x, y = pair.split()[:2]
                    coords.append((float(x), float(y)))
            else:
                a = nodes.get(str(row["from_node_id"]))
                b = nodes.get(str(row["to_node_id"]))
                if a and b:
                    coords = [a, b]
            if len(coords) >= 2:
                lines.append(coords)
                cls = (row.get("overture_class") or row.get("facility_type") or "").split("_")[0]
                colors.append(CLASS_COLORS.get(cls.lower(), "#c7c9cf"))
    return lines, colors


def run(region: str) -> Path:
    osm_lines, osm_colors = _segments(osm_dir(region))
    ovr_lines, ovr_colors = _segments(overture_dir(region))

    fig, axes = plt.subplots(1, 3, figsize=(21, 7), sharex=True, sharey=True)
    for ax, (lines, colors, title) in zip(
        axes,
        [
            (osm_lines, osm_colors, f"osm2gmns ({len(osm_lines)} links)"),
            (ovr_lines, ovr_colors, f"overture2gmns ({len(ovr_lines)} links)"),
            (None, None, "overlay: osm gray / overture red"),
        ],
    ):
        if lines is not None:
            ax.add_collection(LineCollection(lines, colors=colors, linewidths=0.4))
        else:
            ax.add_collection(LineCollection(osm_lines, colors="#6b7280", linewidths=0.7))
            ax.add_collection(LineCollection(ovr_lines, colors="#d62728", linewidths=0.3))
        ax.set_title(title)
        ax.autoscale()
        ax.set_aspect("equal")
        ax.tick_params(labelsize=7)

    fig.suptitle(f"{region}: network comparison", fontsize=14)
    fig.tight_layout()
    output = region_dir(region) / "side_by_side.png"
    fig.savefig(output, dpi=200)
    plt.close(fig)
    print(f"[step6:{region}] wrote {output}")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("region", choices=sorted(REGIONS))
    run(parser.parse_args().region)
