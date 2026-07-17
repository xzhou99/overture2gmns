from pathlib import Path

import pytest

from overture2gmns import get_net_from_file, output_net_to_csv

FIXTURES = Path(__file__).parent / "fixtures"


def test_connector_topology_and_directionality(tmp_path):
    network = get_net_from_file(
        FIXTURES / "segments.geojson",
        FIXTURES / "connectors.geojson",
        mode_types=("auto",),
    )
    assert network.number_of_nodes == 5
    # Main Street: 2 forward-only pieces. Cross Street: 2 pieces x 2 headings.
    assert network.number_of_links == 6

    main_links = [
        link for link in network.links.values()
        if link.overture_segment_id == "segment-main-street"
    ]
    assert {link.overture_heading for link in main_links} == {"forward"}
    assert sorted(link.free_speed for link in main_links) == [25.0, 35.0]

    center_nodes = [
        node for node in network.nodes.values()
        if node.overture_connector_id == "connector-center"
    ]
    assert len(center_nodes) == 1

    output_net_to_csv(network, tmp_path)
    assert (tmp_path / "node.csv").exists()
    assert (tmp_path / "link.csv").exists()
    assert (tmp_path / "diagnostics.json").exists()


def test_multimodal_defaults():
    network = get_net_from_file(
        FIXTURES / "segments.geojson",
        FIXTURES / "connectors.geojson",
        mode_types=("auto", "bike", "walk"),
    )
    cross_links = [
        link for link in network.links.values()
        if link.overture_segment_id == "segment-cross-street"
    ]
    assert all(link.allowed_uses == "auto,bike,walk" for link in cross_links)


def test_mode_types_accepts_plain_string():
    network = get_net_from_file(
        FIXTURES / "segments.geojson",
        FIXTURES / "connectors.geojson",
        mode_types="auto",
    )
    assert network.number_of_links == 6


def test_network_types_alias_still_works():
    network = get_net_from_file(
        FIXTURES / "segments.geojson",
        FIXTURES / "connectors.geojson",
        network_types=("auto",),
    )
    assert network.number_of_links == 6


def test_link_types_filter():
    network = get_net_from_file(
        FIXTURES / "segments.geojson",
        FIXTURES / "connectors.geojson",
        mode_types="auto",
        link_types="primary",
    )
    assert {link.overture_class for link in network.links.values()} == {"primary"}
    assert network.diagnostics["skipped_filtered_link_type"] == 1


def test_invalid_mode_raises():
    with pytest.raises(ValueError, match="Unsupported mode types"):
        get_net_from_file(FIXTURES / "segments.geojson", mode_types="hovercraft")
