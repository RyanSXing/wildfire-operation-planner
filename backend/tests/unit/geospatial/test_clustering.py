from datetime import UTC, datetime, timedelta
from math import inf, nan

import pytest

from wildfireops.domain.observations import NormalizedObservation
from wildfireops.geospatial.clustering import ClusteringConfig, cluster_detections


def _detection(
    record_id: str,
    *,
    observed_at: datetime,
    longitude: float,
    latitude: float,
) -> NormalizedObservation:
    return NormalizedObservation(
        source_name="nasa_firms",
        source_record_id=record_id,
        observed_at=observed_at,
        longitude=longitude,
        latitude=latitude,
        confidence=0.9,
        intensity=None,
        raw_payload={"record_id": record_id},
    )


def test_cluster_detections_is_deterministic_for_reversed_input() -> None:
    start = datetime(2024, 7, 24, 18, tzinfo=UTC)
    records = (
        _detection(
            "alpha-1",
            observed_at=start,
            longitude=-121.6000,
            latitude=39.8000,
        ),
        _detection(
            "alpha-2",
            observed_at=start + timedelta(seconds=30),
            longitude=-121.5995,
            latitude=39.8003,
        ),
        _detection(
            "bravo-1",
            observed_at=start + timedelta(minutes=10),
            longitude=-121.0000,
            latitude=40.2000,
        ),
        _detection(
            "bravo-2",
            observed_at=start + timedelta(minutes=10, seconds=30),
            longitude=-120.9995,
            latitude=40.2003,
        ),
        _detection(
            "noise",
            observed_at=start + timedelta(minutes=20),
            longitude=-120.5000,
            latitude=40.8000,
        ),
    )
    config = ClusteringConfig(
        spatial_radius_meters=200.0,
        temporal_window_seconds=120.0,
        minimum_points=2,
        algorithm_version="dbscan-v1",
    )

    first = cluster_detections(records, config)
    reversed_result = cluster_detections(tuple(reversed(records)), config)

    assert tuple(cluster.member_identities for cluster in first) == (
        ("nasa_firms:alpha-1", "nasa_firms:alpha-2"),
        ("nasa_firms:bravo-1", "nasa_firms:bravo-2"),
    )
    assert tuple(cluster.member_identities for cluster in reversed_result) == tuple(
        cluster.member_identities for cluster in first
    )
    assert len(first) == 2
    for cluster, reversed_cluster in zip(first, reversed_result, strict=True):
        assert reversed_cluster.centroid_longitude == pytest.approx(
            cluster.centroid_longitude
        )
        assert reversed_cluster.centroid_latitude == pytest.approx(
            cluster.centroid_latitude
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("spatial_radius_meters", 0, "spatial_radius_meters"),
        ("spatial_radius_meters", -1.0, "spatial_radius_meters"),
        ("spatial_radius_meters", inf, "spatial_radius_meters"),
        ("spatial_radius_meters", nan, "spatial_radius_meters"),
        ("spatial_radius_meters", 10**400, "spatial_radius_meters"),
        ("spatial_radius_meters", True, "spatial_radius_meters"),
        ("temporal_window_seconds", 0, "temporal_window_seconds"),
        ("temporal_window_seconds", -1.0, "temporal_window_seconds"),
        ("temporal_window_seconds", inf, "temporal_window_seconds"),
        ("temporal_window_seconds", nan, "temporal_window_seconds"),
        ("temporal_window_seconds", 10**400, "temporal_window_seconds"),
        ("temporal_window_seconds", False, "temporal_window_seconds"),
        ("minimum_points", 0, "minimum_points"),
        ("minimum_points", -1, "minimum_points"),
        ("minimum_points", True, "minimum_points"),
        ("minimum_points", 1.5, "minimum_points"),
        ("algorithm_version", "", "algorithm_version"),
        ("algorithm_version", "   ", "algorithm_version"),
        ("algorithm_version", 1, "algorithm_version"),
    ),
)
def test_clustering_config_rejects_invalid_values(
    field: str,
    value: object,
    message: str,
) -> None:
    values: dict[str, object] = {
        "spatial_radius_meters": 200.0,
        "temporal_window_seconds": 120.0,
        "minimum_points": 2,
        "algorithm_version": "dbscan-v1",
    }
    values[field] = value

    with pytest.raises(ValueError, match=message):
        ClusteringConfig(**values)  # type: ignore[arg-type]


def test_cluster_detections_rejects_non_finite_coordinates() -> None:
    record = _detection(
        "not-a-coordinate",
        observed_at=datetime(2024, 7, 24, 18, tzinfo=UTC),
        longitude=-121.6,
        latitude=39.8,
    )
    object.__setattr__(record, "longitude", nan)
    config = ClusteringConfig(
        spatial_radius_meters=200.0,
        temporal_window_seconds=120.0,
        minimum_points=1,
        algorithm_version="dbscan-v1",
    )

    with pytest.raises(ValueError, match="coordinates must be finite"):
        cluster_detections((record,), config)


def test_cluster_detections_rejects_oversized_coordinates() -> None:
    record = _detection(
        "oversized-coordinate",
        observed_at=datetime(2024, 7, 24, 18, tzinfo=UTC),
        longitude=-121.6,
        latitude=39.8,
    )
    object.__setattr__(record, "longitude", 10**400)
    config = ClusteringConfig(
        spatial_radius_meters=200.0,
        temporal_window_seconds=120.0,
        minimum_points=1,
        algorithm_version="dbscan-v1",
    )

    with pytest.raises(ValueError, match="coordinates must be finite"):
        cluster_detections((record,), config)


def test_cluster_detections_rejects_boolean_coordinates() -> None:
    record = _detection(
        "boolean-coordinate",
        observed_at=datetime(2024, 7, 24, 18, tzinfo=UTC),
        longitude=-121.6,
        latitude=39.8,
    )
    object.__setattr__(record, "longitude", True)
    config = ClusteringConfig(
        spatial_radius_meters=200.0,
        temporal_window_seconds=120.0,
        minimum_points=1,
        algorithm_version="dbscan-v1",
    )

    with pytest.raises(ValueError, match="coordinates must be finite"):
        cluster_detections((record,), config)
