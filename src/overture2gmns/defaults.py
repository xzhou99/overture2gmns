"""Application defaults used where Overture intentionally leaves local policy implicit."""

from __future__ import annotations

# Overture explicitly states that implied access and speed depend on local rules.
# These values are therefore transparent, user-replaceable modeling defaults.
ROAD_DEFAULTS: dict[str, dict[str, object]] = {
    "motorway": {"speed_mph": 65.0, "lanes": 2, "capacity": 2200.0, "modes": {"auto", "bus", "truck"}},
    "trunk": {"speed_mph": 55.0, "lanes": 2, "capacity": 2000.0, "modes": {"auto", "bus", "truck"}},
    "primary": {"speed_mph": 45.0, "lanes": 2, "capacity": 1800.0, "modes": {"auto", "bus", "truck", "bike", "walk"}},
    "secondary": {"speed_mph": 35.0, "lanes": 1, "capacity": 1600.0, "modes": {"auto", "bus", "truck", "bike", "walk"}},
    "tertiary": {"speed_mph": 30.0, "lanes": 1, "capacity": 1400.0, "modes": {"auto", "bus", "truck", "bike", "walk"}},
    "residential": {"speed_mph": 25.0, "lanes": 1, "capacity": 1000.0, "modes": {"auto", "bus", "truck", "bike", "walk"}},
    "unclassified": {"speed_mph": 25.0, "lanes": 1, "capacity": 1000.0, "modes": {"auto", "bus", "truck", "bike", "walk"}},
    "living_street": {"speed_mph": 15.0, "lanes": 1, "capacity": 600.0, "modes": {"auto", "bus", "truck", "bike", "walk"}},
    "service": {"speed_mph": 15.0, "lanes": 1, "capacity": 600.0, "modes": {"auto", "bus", "truck", "bike", "walk"}},
    "track": {"speed_mph": 15.0, "lanes": 1, "capacity": 400.0, "modes": {"auto", "truck", "bike", "walk"}},
    "cycleway": {"speed_mph": 12.0, "lanes": 0, "capacity": 0.0, "modes": {"bike", "walk"}},
    "footway": {"speed_mph": 3.0, "lanes": 0, "capacity": 0.0, "modes": {"walk"}},
    "pedestrian": {"speed_mph": 3.0, "lanes": 0, "capacity": 0.0, "modes": {"walk"}},
    "steps": {"speed_mph": 2.0, "lanes": 0, "capacity": 0.0, "modes": {"walk"}},
    "path": {"speed_mph": 8.0, "lanes": 0, "capacity": 0.0, "modes": {"bike", "walk"}},
    "bridleway": {"speed_mph": 6.0, "lanes": 0, "capacity": 0.0, "modes": {"bike", "walk"}},
    "unknown": {"speed_mph": 20.0, "lanes": 1, "capacity": 800.0, "modes": {"auto", "bus", "truck", "bike", "walk"}},
}

SUPPORTED_MODES = {"auto", "bus", "truck", "bike", "walk"}

# Facts used to evaluate Overture's hierarchical travel-mode scopes.
MODE_FACTS: dict[str, set[str]] = {
    "auto": {"vehicle", "motor_vehicle", "motorcar", "car"},
    "bus": {"vehicle", "motor_vehicle", "bus"},
    "truck": {"vehicle", "motor_vehicle", "hgv"},
    "bike": {"vehicle", "bicycle"},
    "walk": {"pedestrian", "foot"},
}
