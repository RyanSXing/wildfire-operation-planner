from pathlib import Path

from wildfireops.geospatial.road_graph import RoadGraph
from wildfireops.replay.loader import ReplayLoader


def test_committed_park_fire_package_is_complete() -> None:
    package = Path(__file__).parents[4] / "data/replay/park-fire"
    loader = ReplayLoader(package)

    assert loader.manifest.package_id == "park-fire-2024-v1"
    assert loader.static_data is not None
    assert {item.source_name for item in loader.iter_until(loader.manifest.end_at)} == {
        "nasa_firms",
        "noaa_ncei",
    }
    assert loader.manifest.road_graph is not None
    graph = RoadGraph.load(package / loader.manifest.road_graph.filename)
    assert graph.graph_version == loader.manifest.road_graph.graph_version
