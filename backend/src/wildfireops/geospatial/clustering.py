from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite

import numpy as np
from numpy.typing import NDArray
from pyproj import Transformer
from sklearn.cluster import DBSCAN  # type: ignore[import-untyped]

from wildfireops.domain.observations import NormalizedObservation


_TO_EPSG_3310 = Transformer.from_crs("EPSG:4326", "EPSG:3310", always_xy=True)
_TO_EPSG_4326 = Transformer.from_crs("EPSG:3310", "EPSG:4326", always_xy=True)


@dataclass(frozen=True, slots=True)
class ClusteringConfig:
    spatial_radius_meters: float
    temporal_window_seconds: float
    minimum_points: int
    algorithm_version: str

    def __post_init__(self) -> None:
        _require_positive_number(
            self.spatial_radius_meters,
            "spatial_radius_meters",
        )
        _require_positive_number(
            self.temporal_window_seconds,
            "temporal_window_seconds",
        )
        if (
            isinstance(self.minimum_points, bool)
            or not isinstance(self.minimum_points, int)
            or self.minimum_points <= 0
        ):
            raise ValueError("minimum_points must be a positive integer")
        if (
            not isinstance(self.algorithm_version, str)
            or not self.algorithm_version.strip()
        ):
            raise ValueError("algorithm_version must be a nonblank string")


@dataclass(frozen=True, slots=True)
class DetectionCluster:
    member_identities: tuple[str, ...]
    centroid_longitude: float
    centroid_latitude: float


def cluster_detections(
    records: Sequence[NormalizedObservation],
    config: ClusteringConfig,
) -> tuple[DetectionCluster, ...]:
    if not records:
        return ()
    ordered = sorted(records, key=lambda item: (item.observed_at, item.identity))
    projected = project_to_epsg_3310(ordered)
    features = build_normalized_space_time_features(projected, ordered, config)
    labels = DBSCAN(eps=1.0, min_samples=config.minimum_points).fit_predict(features)
    clusters = build_clusters(ordered, labels)
    return tuple(sorted(clusters, key=lambda item: item.member_identities))


def project_to_epsg_3310(
    records: Sequence[NormalizedObservation],
) -> NDArray[np.float64]:
    if any(
        not _is_finite_number(record.longitude)
        or not _is_finite_number(record.latitude)
        for record in records
    ):
        raise ValueError("detection coordinates must be finite")
    longitudes = np.asarray([record.longitude for record in records], dtype=float)
    latitudes = np.asarray([record.latitude for record in records], dtype=float)
    eastings, northings = _TO_EPSG_3310.transform(longitudes, latitudes)
    projected = np.column_stack((eastings, northings)).astype(float, copy=False)
    if not np.isfinite(projected).all():
        raise ValueError("projected detection coordinates must be finite")
    return projected


def build_normalized_space_time_features(
    projected: NDArray[np.float64],
    records: Sequence[NormalizedObservation],
    config: ClusteringConfig,
) -> NDArray[np.float64]:
    origin = projected[0]
    spatial = (projected - origin) / config.spatial_radius_meters
    first_observed_at = records[0].observed_at
    elapsed = np.asarray(
        [
            (record.observed_at - first_observed_at).total_seconds()
            / config.temporal_window_seconds
            for record in records
        ],
        dtype=float,
    )
    return np.column_stack((spatial, elapsed))


def build_clusters(
    records: Sequence[NormalizedObservation],
    labels: Sequence[int],
) -> tuple[DetectionCluster, ...]:
    projected = project_to_epsg_3310(records)
    clusters: list[DetectionCluster] = []
    for label in sorted(set(labels) - {-1}):
        member_indexes = [index for index, value in enumerate(labels) if value == label]
        member_points = projected[member_indexes]
        centroid_easting, centroid_northing = np.mean(member_points, axis=0)
        longitude, latitude = _TO_EPSG_4326.transform(
            centroid_easting,
            centroid_northing,
        )
        clusters.append(
            DetectionCluster(
                member_identities=tuple(
                    sorted(records[index].identity for index in member_indexes)
                ),
                centroid_longitude=float(longitude),
                centroid_latitude=float(latitude),
            )
        )
    return tuple(clusters)


def _require_positive_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite positive number")
    try:
        parsed = float(value)
    except OverflowError:
        raise ValueError(f"{field} must be a finite positive number") from None
    if not isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{field} must be a finite positive number")
    return parsed


def _is_finite_number(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return isfinite(value)
    except OverflowError:
        return False
