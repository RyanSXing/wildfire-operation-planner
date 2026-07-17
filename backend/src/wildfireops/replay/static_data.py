import json
from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from types import MappingProxyType
from typing import NoReturn, cast

from shapely.geometry import shape  # type: ignore[import-untyped]

from wildfireops.domain.observations import FrozenJsonObject, freeze_json_object
from wildfireops.replay.manifest import ReplayManifest


STATIC_DATA_FILENAMES = (
    "static_data_versions.json",
    "source_citations.json",
    "exposed_assets.geojson",
    "resources.json",
)
_ASSET_PROPERTIES = {
    "asset_id",
    "asset_kind",
    "name",
    "population",
    "capacity",
    "source_name",
    "source_version",
    "raw_metadata",
}
_RESOURCE_FIELDS = {
    "resource_id",
    "resource_type",
    "capabilities",
    "capacity",
    "available",
    "status",
    "geometry_geojson",
    "raw_metadata",
}


class ReplayStaticDataInvalid(ValueError):
    """Raised when replay static context is missing or malformed."""


@dataclass(frozen=True, slots=True)
class ReplayAsset:
    asset_id: str
    asset_kind: str
    name: str
    population: int | None
    capacity: int | None
    source_name: str
    source_version: str
    geometry_geojson: FrozenJsonObject
    raw_metadata: FrozenJsonObject

    def __post_init__(self) -> None:
        context = f"exposed_assets.geojson: {self.asset_id}"
        try:
            geometry = freeze_json_object(self.geometry_geojson)
            metadata = freeze_json_object(self.raw_metadata)
        except RecursionError:
            raise ReplayStaticDataInvalid(
                f"{context}: JSON is too deeply nested"
            ) from None
        except ValueError as error:
            raise ReplayStaticDataInvalid(f"{context}: {error}") from None
        object.__setattr__(self, "geometry_geojson", geometry)
        object.__setattr__(self, "raw_metadata", metadata)


@dataclass(frozen=True, slots=True)
class ReplayResource:
    resource_id: str
    resource_type: str
    capabilities: tuple[str, ...]
    capacity: int
    available: bool
    status: str
    geometry_geojson: FrozenJsonObject
    raw_metadata: FrozenJsonObject

    def __post_init__(self) -> None:
        context = f"resources.json: {self.resource_id}"
        try:
            geometry = freeze_json_object(self.geometry_geojson)
            metadata = freeze_json_object(self.raw_metadata)
        except RecursionError:
            raise ReplayStaticDataInvalid(
                f"{context}: JSON is too deeply nested"
            ) from None
        except ValueError as error:
            raise ReplayStaticDataInvalid(f"{context}: {error}") from None
        object.__setattr__(self, "geometry_geojson", geometry)
        object.__setattr__(self, "raw_metadata", metadata)


@dataclass(frozen=True, slots=True)
class ReplayStaticData:
    static_data_versions: Mapping[str, str]
    source_citations: Mapping[str, str]
    assets: tuple[ReplayAsset, ...]
    resources: tuple[ReplayResource, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "static_data_versions",
            MappingProxyType(dict(sorted(self.static_data_versions.items()))),
        )
        object.__setattr__(
            self,
            "source_citations",
            MappingProxyType(dict(sorted(self.source_citations.items()))),
        )
        object.__setattr__(self, "assets", tuple(self.assets))
        object.__setattr__(self, "resources", tuple(self.resources))


def parse_replay_static_data(
    files: Mapping[str, bytes], manifest: ReplayManifest
) -> ReplayStaticData:
    missing = [name for name in STATIC_DATA_FILENAMES if name not in files]
    if missing:
        raise ReplayStaticDataInvalid(f"missing required static file: {missing[0]}")
    versions = _string_map(
        _strict_json(files["static_data_versions.json"], "static_data_versions.json"),
        "static_data_versions.json",
    )
    citations = _string_map(
        _strict_json(files["source_citations.json"], "source_citations.json"),
        "source_citations.json",
    )
    assets = _assets(
        _strict_json(files["exposed_assets.geojson"], "exposed_assets.geojson"),
        versions,
        citations,
        manifest.region,
    )
    resources = _resources(
        _strict_json(files["resources.json"], "resources.json"), manifest.region
    )
    for filename, values in (
        ("static_data_versions.json", versions),
        ("source_citations.json", citations),
    ):
        if "simulated_resources" not in values:
            raise ReplayStaticDataInvalid(
                f"{filename} missing required key: simulated_resources"
            )
    return ReplayStaticData(
        static_data_versions=versions,
        source_citations=citations,
        assets=tuple(sorted(assets, key=lambda item: item.asset_id)),
        resources=tuple(sorted(resources, key=lambda item: item.resource_id)),
    )


def static_data_payloads(data: ReplayStaticData) -> dict[str, object]:
    return {
        "static_data_versions.json": dict(data.static_data_versions),
        "source_citations.json": dict(data.source_citations),
        "exposed_assets.geojson": {
            "type": "FeatureCollection",
            "features": [_asset_feature(item) for item in data.assets],
        },
        "resources.json": [_resource_record(item) for item in data.resources],
    }


def _strict_json(content: bytes, filename: str) -> object:
    try:
        decoded = content.decode("utf-8")
        return json.loads(
            decoded,
            object_pairs_hook=lambda pairs: _unique_object(pairs, filename),
            parse_constant=lambda value: _invalid_json_number(value, filename),
        )
    except ReplayStaticDataInvalid:
        raise
    except RecursionError:
        raise ReplayStaticDataInvalid(
            f"{filename}: JSON is too deeply nested"
        ) from None
    except (
        AttributeError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ):
        raise ReplayStaticDataInvalid(f"{filename}: invalid JSON") from None


def _unique_object(pairs: list[tuple[str, object]], filename: str) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ReplayStaticDataInvalid(f"{filename}: duplicate JSON key: {key}")
        result[key] = value
    return result


def _invalid_json_number(value: str, filename: str) -> object:
    raise ReplayStaticDataInvalid(f"{filename}: invalid JSON number: {value}")


def _string_map(value: object, filename: str) -> dict[str, str]:
    mapping = _object(value, f"{filename}: must be an object")
    if not mapping:
        raise ReplayStaticDataInvalid(f"{filename}: must be a nonempty object")
    result: dict[str, str] = {}
    for key, item in mapping.items():
        if isinstance(key, str) and (
            key in {".", ".."}
            or "/" in key
            or "\\" in key
            or "\x00" in key
            or key != key.strip()
        ):
            raise ReplayStaticDataInvalid(f"unsafe {filename} key: {key}")
        normalized_key = _nonblank(key, f"{filename}: key")
        result[normalized_key] = _nonblank(item, f"{filename}: value for {key}")
    return result


def _assets(
    value: object,
    versions: Mapping[str, str],
    citations: Mapping[str, str],
    bbox: tuple[float, float, float, float],
) -> list[ReplayAsset]:
    collection = _object(
        value, "exposed_assets.geojson: FeatureCollection must be an object"
    )
    _exact_fields(collection, {"type", "features"}, "exposed_assets.geojson")
    if collection["type"] != "FeatureCollection":
        raise ReplayStaticDataInvalid(
            "exposed_assets.geojson: type must be FeatureCollection"
        )
    features = collection["features"]
    if not isinstance(features, list) or not features:
        raise ReplayStaticDataInvalid(
            "exposed_assets.geojson: features must be nonempty"
        )
    result: list[ReplayAsset] = []
    ids: set[str] = set()
    for value in features:
        feature = _object(value, "exposed_assets.geojson: Feature must be an object")
        _exact_fields(
            feature,
            {"type", "geometry", "properties"},
            "exposed_assets.geojson: Feature",
        )
        if feature["type"] != "Feature":
            raise ReplayStaticDataInvalid(
                "exposed_assets.geojson: feature type must be Feature"
            )
        properties = _object(
            feature["properties"],
            "exposed_assets.geojson: properties must be an object",
        )
        asset_id = _nonblank(
            properties.get("asset_id"), "exposed_assets.geojson: asset_id"
        )
        context = f"exposed_assets.geojson: {asset_id}"
        _exact_fields(properties, _ASSET_PROPERTIES, context, label="property")
        if asset_id in ids:
            raise ReplayStaticDataInvalid(
                f"exposed_assets.geojson: duplicate asset_id: {asset_id}"
            )
        geometry = _geometry(
            feature["geometry"], context, bbox, {"Point", "Polygon", "MultiPolygon"}
        )
        raw_metadata = _object(
            properties["raw_metadata"], f"{context}: raw_metadata must be an object"
        )
        demand = _object(
            raw_metadata.get("demand"), f"{context}: raw_metadata.demand is required"
        )
        _exact_fields(
            demand,
            {"required_capability", "required_capacity"},
            f"{context}: raw_metadata.demand",
        )
        source_name = _nonblank(properties["source_name"], f"{context}: source_name")
        source_version = _nonblank(
            properties["source_version"], f"{context}: source_version"
        )
        if versions.get(source_name) != source_version:
            raise ReplayStaticDataInvalid(
                f"{context}: source_version does not match static_data_versions"
            )
        if source_name not in citations:
            raise ReplayStaticDataInvalid(
                f"{context}: source_name is missing from source_citations"
            )
        _nonblank(
            demand["required_capability"],
            f"{context}: raw_metadata.demand.required_capability",
        )
        _positive_integer(
            demand["required_capacity"],
            f"{context}: raw_metadata.demand.required_capacity",
        )
        ids.add(asset_id)
        result.append(
            ReplayAsset(
                asset_id=asset_id,
                asset_kind=_nonblank(
                    properties["asset_kind"], f"{context}: asset_kind"
                ),
                name=_nonblank(properties["name"], f"{context}: name"),
                population=_optional_nonnegative_integer(
                    properties["population"], f"{context}: population"
                ),
                capacity=_optional_nonnegative_integer(
                    properties["capacity"], f"{context}: capacity"
                ),
                source_name=source_name,
                source_version=source_version,
                geometry_geojson=cast(FrozenJsonObject, geometry),
                raw_metadata=cast(FrozenJsonObject, raw_metadata),
            )
        )
    return result


def _resources(
    value: object, bbox: tuple[float, float, float, float]
) -> list[ReplayResource]:
    if not isinstance(value, list) or not value:
        raise ReplayStaticDataInvalid("resources.json: must be a nonempty array")
    result: list[ReplayResource] = []
    ids: set[str] = set()
    for value in value:
        resource = _object(value, "resources.json: resource must be an object")
        resource_id = _nonblank(
            resource.get("resource_id"), "resources.json: resource_id"
        )
        context = f"resources.json: {resource_id}"
        _exact_fields(resource, _RESOURCE_FIELDS, context)
        if resource_id in ids:
            raise ReplayStaticDataInvalid(
                f"resources.json: duplicate resource_id: {resource_id}"
            )
        capabilities = resource["capabilities"]
        if not isinstance(capabilities, list) or not capabilities:
            raise ReplayStaticDataInvalid(
                f"{context}: capabilities must be a nonempty array"
            )
        parsed_capabilities = tuple(
            _nonblank(value, f"{context}: capability") for value in capabilities
        )
        if len(set(parsed_capabilities)) != len(parsed_capabilities):
            raise ReplayStaticDataInvalid(f"{context}: capabilities contain duplicates")
        raw_metadata = _object(
            resource["raw_metadata"], f"{context}: raw_metadata must be an object"
        )
        if raw_metadata.get("simulated") is not True:
            raise ReplayStaticDataInvalid(
                f"{context}: raw_metadata.simulated must be true"
            )
        ids.add(resource_id)
        result.append(
            ReplayResource(
                resource_id=resource_id,
                resource_type=_nonblank(
                    resource["resource_type"], f"{context}: resource_type"
                ),
                capabilities=tuple(sorted(parsed_capabilities)),
                capacity=_positive_integer(
                    resource["capacity"], f"{context}: capacity"
                ),
                available=_boolean(resource["available"], f"{context}: available"),
                status=_nonblank(resource["status"], f"{context}: status"),
                geometry_geojson=cast(
                    FrozenJsonObject,
                    _geometry(
                        resource["geometry_geojson"],
                        context,
                        bbox,
                        {"Point"},
                        field="geometry_geojson",
                    ),
                ),
                raw_metadata=cast(FrozenJsonObject, raw_metadata),
            )
        )
    return result


def _geometry(
    value: object,
    context: str,
    bbox: tuple[float, float, float, float],
    allowed_types: set[str],
    *,
    field: str = "geometry",
) -> dict[str, object]:
    geometry = _object(value, f"{context}: {field} must be an object")
    _exact_fields(geometry, {"type", "coordinates"}, context, label=field)
    geometry_type = geometry["type"]
    if not isinstance(geometry_type, str) or geometry_type not in allowed_types:
        expected = (
            "a Point"
            if allowed_types == {"Point"}
            else "a Point, Polygon, or MultiPolygon"
        )
        raise ReplayStaticDataInvalid(f"{context}: {field} must be {expected}")
    _coordinates(geometry["coordinates"], geometry_type, context)
    try:
        parsed = shape(geometry)
    except (IndexError, TypeError, ValueError):
        raise ReplayStaticDataInvalid(
            f"{context}: {field} must be nonempty and valid"
        ) from None
    if parsed.is_empty or not parsed.is_valid:
        raise ReplayStaticDataInvalid(f"{context}: {field} must be nonempty and valid")
    west, south, east, north = bbox
    min_x, min_y, max_x, max_y = parsed.bounds
    if min_x < west or min_y < south or max_x > east or max_y > north:
        raise ReplayStaticDataInvalid(
            f"{context}: geometry is outside manifest region.bbox"
        )
    return geometry


def _coordinates(value: object, geometry_type: str, context: str) -> None:
    if geometry_type == "Point":
        _position(value, context)
    elif geometry_type == "Polygon":
        _polygon(value, context)
    else:
        _multipolygon(value, context)


def _polygon(value: object, context: str) -> None:
    if not isinstance(value, list):
        _coordinate_error(context)
    if not value:
        _geometry_error(context)
    for ring in value:
        if not isinstance(ring, list):
            _coordinate_error(context)
        for position in ring:
            _position(position, context)
        if len(ring) < 4 or ring[0] != ring[-1]:
            _geometry_error(context)


def _multipolygon(value: object, context: str) -> None:
    if not isinstance(value, list):
        _coordinate_error(context)
    if not value:
        _geometry_error(context)
    for polygon in value:
        _polygon(polygon, context)


def _position(value: object, context: str) -> None:
    if (
        not isinstance(value, list)
        or len(value) != 2
        or any(
            isinstance(item, bool) or not isinstance(item, (int, float))
            for item in value
        )
    ):
        _coordinate_error(context)
    try:
        if not all(isfinite(float(item)) for item in value):
            _coordinate_error(context)
    except OverflowError:
        _coordinate_error(context)


def _coordinate_error(context: str) -> NoReturn:
    raise ReplayStaticDataInvalid(
        f"{context}: geometry coordinates must be finite two-dimensional numbers"
    )


def _geometry_error(context: str) -> NoReturn:
    raise ReplayStaticDataInvalid(f"{context}: geometry must be nonempty and valid")


def _object(value: object, message: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ReplayStaticDataInvalid(message)
    return dict(value)


def _exact_fields(
    value: Mapping[str, object],
    expected: set[str],
    context: str,
    *,
    label: str = "field",
) -> None:
    missing = sorted(expected - value.keys())
    if missing:
        raise ReplayStaticDataInvalid(
            f"{context}: missing required {label}: {missing[0]}"
        )
    unsupported = sorted(value.keys() - expected)
    if unsupported:
        raise ReplayStaticDataInvalid(
            f"{context}: unsupported {label}: {unsupported[0]}"
        )


def _nonblank(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or "\x00" in value
        or any(not character.isprintable() for character in value)
    ):
        raise ReplayStaticDataInvalid(f"{field} must be a nonblank string")
    return value


def _optional_nonnegative_integer(value: object, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ReplayStaticDataInvalid(f"{field} must be a nonnegative integer or null")
    return value


def _positive_integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ReplayStaticDataInvalid(f"{field} must be a positive integer")
    return value


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ReplayStaticDataInvalid(f"{field} must be a boolean")
    return value


def _asset_feature(asset: ReplayAsset) -> dict[str, object]:
    return {
        "type": "Feature",
        "geometry": _materialize_json(asset.geometry_geojson),
        "properties": {
            "asset_id": asset.asset_id,
            "asset_kind": asset.asset_kind,
            "name": asset.name,
            "population": asset.population,
            "capacity": asset.capacity,
            "source_name": asset.source_name,
            "source_version": asset.source_version,
            "raw_metadata": _materialize_json(asset.raw_metadata),
        },
    }


def _resource_record(resource: ReplayResource) -> dict[str, object]:
    return {
        "resource_id": resource.resource_id,
        "resource_type": resource.resource_type,
        "capabilities": list(resource.capabilities),
        "capacity": resource.capacity,
        "available": resource.available,
        "status": resource.status,
        "geometry_geojson": _materialize_json(resource.geometry_geojson),
        "raw_metadata": _materialize_json(resource.raw_metadata),
    }


def _materialize_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _materialize_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_materialize_json(item) for item in value]
    return value
