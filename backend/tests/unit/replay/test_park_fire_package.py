from pathlib import Path

from pyproj import Geod

from wildfireops.domain.observations import NormalizedObservation, WeatherObservation
from wildfireops.geospatial.exposure import ExposureConfig
from wildfireops.geospatial.road_graph import RoadGraph
from wildfireops.replay.loader import ReplayLoader


def test_committed_park_fire_package_is_complete() -> None:
    package = Path(__file__).parents[4] / "data/replay/park-fire"
    loader = ReplayLoader(package)

    assert loader.manifest.package_id == "park-fire-2024-v1"
    assert loader.static_data is not None
    observations = tuple(loader.iter_until(loader.manifest.end_at))
    assert {item.source_name for item in observations} == {
        "nasa_firms",
        "noaa_ncei",
    }
    assert all(
        item.raw_metadata["simulated"] is True for item in loader.static_data.resources
    )
    assert all(
        citation.startswith("https://")
        for citation in loader.static_data.source_citations.values()
    )
    west, south, east, north = loader.manifest.region
    assert all(
        loader.manifest.start_at <= item.observed_at <= loader.manifest.end_at
        and west <= item.longitude <= east
        and south <= item.latitude <= north
        for item in observations
    )
    for item in observations:
        if isinstance(item, NormalizedObservation):
            assert (
                item.confidence
                == {"l": 0.3, "n": 0.6, "h": 0.9}[item.raw_payload["confidence"]]
            )
            assert item.intensity == float(item.raw_payload["bright_ti4"])
        elif isinstance(item, WeatherObservation):
            wind = item.raw_payload["WND"].split(",")
            temperature = item.raw_payload["TMP"].split(",")
            assert item.wind_speed_mps == int(wind[3]) / 10
            assert item.temperature_celsius == int(temperature[0]) / 10
    geod = Geod(ellps="WGS84")
    assert (
        min(
            abs(
                geod.inv(
                    item.longitude,
                    item.latitude,
                    asset.geometry_geojson["coordinates"][0],
                    asset.geometry_geojson["coordinates"][1],
                )[2]
            )
            for item in observations
            if isinstance(item, NormalizedObservation)
            for asset in loader.static_data.assets
        )
        <= ExposureConfig().buffer_meters
    )
    assert loader.manifest.road_graph is not None
    graph = RoadGraph.load(package / loader.manifest.road_graph.filename)
    assert graph.graph_version == loader.manifest.road_graph.graph_version
