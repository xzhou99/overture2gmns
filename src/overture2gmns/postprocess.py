"""Network post-processing mirroring the osm2gmns public API."""

from __future__ import annotations

import csv
from collections import Counter, defaultdict
from collections.abc import Mapping
from pathlib import Path

from pyproj import Geod
from shapely import wkt
from shapely.geometry import LineString, Point

from .converter import line_length_miles
from .defaults import ROAD_DEFAULTS
from .models import Network, Node

GEOD = Geod(ellps="WGS84")
METERS_PER_MILE = 1609.344


def _distance_meters(x1: float, y1: float, x2: float, y2: float) -> float:
    _, _, distance = GEOD.inv(x1, y1, x2, y2)
    return distance


def fill_link_attributes_with_default_values(
    network: Network,
    default_lanes: bool = False,
    default_lanes_dict: Mapping[str, int] = {},
    default_speed: bool = False,
    default_speed_dict: Mapping[str, float] = {},
    default_capacity: bool = False,
    default_capacity_dict: Mapping[str, float] = {},
) -> None:
    """Assign default lanes/speed/capacity to links lacking observed values.

    Mirrors ``osm2gmns.fillLinkAttributesWithDefaultValues``. Dictionaries are
    keyed by Overture road class (e.g. ``{'motorway': 3}``); speeds are in mph
    to stay consistent with the rest of this package. Only attributes whose
    ``*_source`` is not ``'overture'`` are touched, so observed Overture values
    are never overwritten.
    """
    for link in network.links.values():
        road_class = link.overture_class
        class_defaults = ROAD_DEFAULTS.get(road_class, ROAD_DEFAULTS["unknown"])
        if default_lanes and link.lanes_source != "overture":
            if road_class in default_lanes_dict:
                link.lanes = int(default_lanes_dict[road_class])
                link.lanes_source = "user_default"
            else:
                link.lanes = int(class_defaults["lanes"])
                link.lanes_source = "inferred_class_default"
        if default_speed and link.speed_source != "overture":
            if road_class in default_speed_dict:
                link.free_speed = float(default_speed_dict[road_class])
                link.speed_source = "user_default"
            else:
                link.free_speed = float(class_defaults["speed_mph"])
                link.speed_source = "inferred_class_default"
        if default_capacity and link.capacity_source != "overture":
            # Dict values are per lane (osm2gmns convention); the GMNS
            # capacity column is total, so scale by the link's lanes.
            lanes = max(1, int(link.lanes or 1))
            if road_class in default_capacity_dict:
                link.capacity = float(default_capacity_dict[road_class]) * lanes
                link.capacity_source = "user_default"
            else:
                link.capacity = float(class_defaults["capacity"]) * lanes
                link.capacity_source = "inferred_class_default"


def generate_node_activity_info(network: Network, zone_filepath: str | Path | None = None) -> None:
    """Generate ``activity_type``, ``is_boundary``, and ``zone_id`` for nodes.

    Mirrors ``osm2gmns.generateNodeActivityInfo``. ``activity_type`` is the
    most frequent Overture road class among incident links. A node is a
    boundary node when it touches exactly one undirected neighbor (dead end or
    clip edge). Boundary nodes receive ``zone_id = node_id`` unless a zone CSV
    (``zone_id``, ``x_coord``, ``y_coord``) assigns the nearest zone center.
    """
    incident_classes: dict[int, Counter] = defaultdict(Counter)
    neighbors: dict[int, set[int]] = defaultdict(set)
    for link in network.links.values():
        incident_classes[link.from_node_id][link.overture_class] += 1
        incident_classes[link.to_node_id][link.overture_class] += 1
        neighbors[link.from_node_id].add(link.to_node_id)
        neighbors[link.to_node_id].add(link.from_node_id)

    zones: list[tuple[int, float, float]] = []
    if zone_filepath is not None:
        with Path(zone_filepath).open(newline="", encoding="utf-8-sig") as stream:
            for row in csv.DictReader(stream):
                zones.append(
                    (int(row["zone_id"]), float(row["x_coord"]), float(row["y_coord"]))
                )

    for node in network.nodes.values():
        classes = incident_classes.get(node.node_id)
        node.activity_type = classes.most_common(1)[0][0] if classes else ""
        is_boundary = len(neighbors.get(node.node_id, ())) <= 1
        node.is_boundary = 1 if is_boundary else 0
        if not is_boundary:
            node.zone_id = ""
            continue
        if zones:
            node.zone_id = min(
                zones,
                key=lambda zone: _distance_meters(node.x_coord, node.y_coord, zone[1], zone[2]),
            )[0]
        else:
            node.zone_id = node.node_id


def consolidate_complex_intersections(
    network: Network,
    auto_identify: bool = False,
    intersection_filepath: str | Path | None = None,
    int_buffer: float = 20.0,
) -> None:
    """Merge nodes that represent one complex intersection into a single node.

    Mirrors ``osm2gmns.consolidateComplexIntersections``. ``int_buffer`` is in
    meters. With ``intersection_filepath`` (CSV: ``x_coord``, ``y_coord``,
    optional ``int_buffer``), nodes within the buffer of each center are
    merged. With ``auto_identify``, connector nodes joined by a link shorter
    than ``int_buffer`` are merged (Overture has no signal attribute, so the
    osm2gmns signal requirement is dropped).
    """
    groups: list[set[int]] = []

    if intersection_filepath is not None:
        with Path(intersection_filepath).open(newline="", encoding="utf-8-sig") as stream:
            for row in csv.DictReader(stream):
                center_x = float(row["x_coord"])
                center_y = float(row["y_coord"])
                buffer_m = float(row.get("int_buffer") or int_buffer)
                group = {
                    node.node_id
                    for node in network.nodes.values()
                    if _distance_meters(node.x_coord, node.y_coord, center_x, center_y) <= buffer_m
                }
                if len(group) >= 2:
                    groups.append(group)
    elif auto_identify:
        parent: dict[int, int] = {node_id: node_id for node_id in network.nodes}

        def find(item: int) -> int:
            while parent[item] != item:
                parent[item] = parent[parent[item]]
                item = parent[item]
            return item

        for link in network.links.values():
            from_node = network.nodes[link.from_node_id]
            to_node = network.nodes[link.to_node_id]
            if from_node.node_type != "intersection" or to_node.node_type != "intersection":
                continue
            if link.length * METERS_PER_MILE <= int_buffer:
                parent[find(link.from_node_id)] = find(link.to_node_id)

        clusters: dict[int, set[int]] = defaultdict(set)
        for node_id in network.nodes:
            clusters[find(node_id)].add(node_id)
        groups = [group for group in clusters.values() if len(group) >= 2]
    else:
        return

    next_intersection_id = 1
    for group in groups:
        members = [network.nodes[node_id] for node_id in sorted(group) if node_id in network.nodes]
        if len(members) < 2:
            continue
        keeper = members[0]
        keeper.x_coord = sum(node.x_coord for node in members) / len(members)
        keeper.y_coord = sum(node.y_coord for node in members) / len(members)
        keeper.geometry = Point(keeper.x_coord, keeper.y_coord).wkt
        keeper.node_type = "complex_intersection"
        keeper.intersection_id = next_intersection_id
        next_intersection_id += 1

        merged_ids = {node.node_id for node in members[1:]}
        for node_id in merged_ids:
            del network.nodes[node_id]

        drop_links = []
        for link in network.links.values():
            changed = False
            if link.from_node_id in merged_ids:
                link.from_node_id = keeper.node_id
                changed = True
            if link.to_node_id in merged_ids:
                link.to_node_id = keeper.node_id
                changed = True
            if link.from_node_id == keeper.node_id and link.to_node_id == keeper.node_id:
                drop_links.append(link.link_id)
                continue
            if changed:
                coordinates = list(wkt.loads(link.geometry).coords)
                if link.from_node_id == keeper.node_id:
                    coordinates[0] = (keeper.x_coord, keeper.y_coord)
                if link.to_node_id == keeper.node_id:
                    coordinates[-1] = (keeper.x_coord, keeper.y_coord)
                geometry = LineString(coordinates)
                link.geometry = geometry.wkt
                link.length = line_length_miles(geometry)
        for link_id in drop_links:
            del network.links[link_id]

    network.diagnostics["consolidated_intersections"] = (
        network.diagnostics.get("consolidated_intersections", 0) + len(groups)
    )


# Compatibility aliases patterned after osm2gmns.
fillLinkAttributesWithDefaultValues = fill_link_attributes_with_default_values
generateNodeActivityInfo = generate_node_activity_info
consolidateComplexIntersections = consolidate_complex_intersections
