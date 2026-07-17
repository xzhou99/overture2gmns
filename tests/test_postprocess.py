from pathlib import Path

from overture2gmns import (
    consolidateComplexIntersections,
    fillLinkAttributesWithDefaultValues,
    generateNodeActivityInfo,
    getNetFromFile,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _network(**kwargs):
    return getNetFromFile(
        FIXTURES / "segments.geojson",
        FIXTURES / "connectors.geojson",
        **kwargs,
    )


def test_fill_link_attributes_overrides_inferred_but_not_observed():
    network = _network(mode_types="auto")
    fillLinkAttributesWithDefaultValues(
        network,
        default_lanes=True,
        default_lanes_dict={"primary": 3},
        default_speed=True,
        default_speed_dict={"primary": 99.0},
        default_capacity=True,
        default_capacity_dict={"secondary": 1234.0},
    )
    primary_links = [l for l in network.links.values() if l.overture_class == "primary"]
    secondary_links = [l for l in network.links.values() if l.overture_class == "secondary"]

    assert all(link.lanes == 3 for link in primary_links)
    assert all(link.lanes_source == "user_default" for link in primary_links)
    # Observed Overture speed limits must never be overwritten.
    assert sorted(link.free_speed for link in primary_links) == [25.0, 35.0]
    assert all(link.speed_source == "overture" for link in primary_links)
    assert all(link.capacity == 1234.0 for link in secondary_links)


def test_generate_node_activity_info():
    network = _network(mode_types="auto")
    generateNodeActivityInfo(network)

    center = next(
        node for node in network.nodes.values()
        if node.overture_connector_id == "connector-center"
    )
    assert center.activity_type in {"primary", "secondary"}
    assert center.is_boundary == 0
    assert center.zone_id == ""

    boundary_nodes = [node for node in network.nodes.values() if node.is_boundary == 1]
    assert len(boundary_nodes) == 4
    assert all(node.zone_id == node.node_id for node in boundary_nodes)


def test_consolidate_from_intersection_file(tmp_path):
    network = _network(mode_types="auto")
    intersections = tmp_path / "intersections.csv"
    # Center of the fixture cross; 60 m buffer captures only connector-center.
    intersections.write_text("x_coord,y_coord,int_buffer\n-111.9350,33.4200,60\n")
    consolidateComplexIntersections(network, intersection_filepath=intersections)
    # Only one node within the buffer: nothing merged, network intact.
    assert network.number_of_nodes == 5

    wide = tmp_path / "wide.csv"
    wide.write_text("x_coord,y_coord,int_buffer\n-111.9350,33.4200,300\n")
    consolidateComplexIntersections(network, intersection_filepath=wide)
    merged = [n for n in network.nodes.values() if n.node_type == "complex_intersection"]
    assert len(merged) == 1
    assert merged[0].intersection_id == 1
    # Links formerly ending at merged nodes now reference the keeper node.
    node_ids = set(network.nodes)
    assert all(
        link.from_node_id in node_ids and link.to_node_id in node_ids
        for link in network.links.values()
    )


def test_consolidate_auto_identify_short_links():
    network = _network(mode_types="auto")
    before_nodes = network.number_of_nodes
    # Fixture links are hundreds of meters long; a 1 m buffer merges nothing.
    consolidateComplexIntersections(network, auto_identify=True, int_buffer=1.0)
    assert network.number_of_nodes == before_nodes
    # A 1 km buffer merges every connector node into one intersection.
    consolidateComplexIntersections(network, auto_identify=True, int_buffer=1000.0)
    assert network.number_of_nodes == 1
    assert network.number_of_links == 0
