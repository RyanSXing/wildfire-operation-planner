import json
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from types import MappingProxyType

import pytest

from wildfireops.replay.manifest import ReplayManifest
from wildfireops.replay.static_data import (
    ReplayAsset,
    ReplayStaticDataInvalid,
    parse_replay_static_data,
    static_data_payloads,
)


def _manifest() -> ReplayManifest:
    return ReplayManifest(
        package_id="synthetic-replay-v1",
        region=(-122.4, 39.2, -120.3, 41.0),
        start_at=datetime(2024, 7, 24, tzinfo=UTC),
        end_at=datetime(2024, 7, 25, tzinfo=UTC),
        schema_version=1,
        algorithm_config_version="test-config-v1",
        files={"fire_detections.jsonl": "0" * 64},
    )


def _asset(asset_id: str, *, coordinates: object = [-121.6, 39.8]) -> dict[str, object]:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": coordinates},
        "properties": {
            "asset_id": asset_id,
            "asset_kind": "community",
            "name": asset_id.title(),
            "population": 5000,
            "capacity": None,
            "source_name": "census",
            "source_version": "2023-acs5",
            "raw_metadata": {
                "demand": {"required_capability": "water", "required_capacity": 2},
                "nested": {"labels": ["priority"]},
            },
        },
    }


def _resource(resource_id: str) -> dict[str, object]:
    return {
        "resource_id": resource_id,
        "resource_type": "engine",
        "capabilities": ["water", "medical"],
        "capacity": 4,
        "available": True,
        "status": "available",
        "geometry_geojson": {"type": "Point", "coordinates": [-121.61, 39.81]},
        "raw_metadata": {"simulated": True},
    }


def _complete_payloads() -> dict[str, object]:
    return {
        "static_data_versions.json": {
            "census": "2023-acs5",
            "simulated_resources": "synthetic-v1",
        },
        "source_citations.json": {
            "census": "https://www.census.gov/",
            "simulated_resources": "WildfireOps portfolio simulation",
        },
        "exposed_assets.geojson": {
            "type": "FeatureCollection",
            "features": [_asset("zebra-2"), _asset("community-1")],
        },
        "resources.json": [_resource("z-engine"), _resource("engine-1")],
    }


def _complete_files() -> dict[str, bytes]:
    return {
        filename: json.dumps(payload).encode()
        for filename, payload in _complete_payloads().items()
    }


def _files(payloads: dict[str, object]) -> dict[str, bytes]:
    return {
        filename: json.dumps(payload).encode() for filename, payload in payloads.items()
    }


def test_static_data_is_sorted_immutable_and_projects_canonically() -> None:
    data = parse_replay_static_data(_complete_files(), _manifest())
    payloads = static_data_payloads(data)

    assert [item.asset_id for item in data.assets] == ["community-1", "zebra-2"]
    assert [item.resource_id for item in data.resources] == ["engine-1", "z-engine"]
    assert data.resources[0].capabilities == ("medical", "water")
    assert payloads["exposed_assets.geojson"]["type"] == "FeatureCollection"
    assert payloads["resources.json"][0]["raw_metadata"] == {"simulated": True}
    with pytest.raises(AttributeError):
        data.assets[0].asset_id = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        data.assets[0].raw_metadata["new"] = "value"  # type: ignore[index]
    nested = data.assets[0].raw_metadata["nested"]
    assert isinstance(nested, Mapping)
    with pytest.raises(TypeError):
        nested["new"] = "value"  # type: ignore[index]
    assert isinstance(data.static_data_versions, MappingProxyType)

    first_projection = static_data_payloads(data)
    second_projection = static_data_payloads(data)
    first_metadata = first_projection["exposed_assets.geojson"]["features"][0][
        "properties"
    ]["raw_metadata"]
    assert isinstance(first_metadata, dict)
    first_metadata["changed"] = True
    assert (
        "changed"
        not in second_projection["exposed_assets.geojson"]["features"][0]["properties"][
            "raw_metadata"
        ]
    )


def test_replay_asset_translates_deep_metadata_at_constructor_boundary() -> None:
    nested: object = 0
    for _ in range(500):
        nested = [nested]

    with pytest.raises(
        ReplayStaticDataInvalid,
        match=r"^exposed_assets\.geojson: deep-asset: JSON is too deeply nested$",
    ):
        ReplayAsset(
            asset_id="deep-asset",
            asset_kind="community",
            name="Deep Asset",
            population=None,
            capacity=None,
            source_name="census",
            source_version="2023-acs5",
            geometry_geojson={"type": "Point", "coordinates": [-121.6, 39.8]},
            raw_metadata={"nested": nested},
        )


def _mutated_complete_files(case: str) -> dict[str, bytes]:
    payloads = _complete_payloads()
    assets = payloads["exposed_assets.geojson"]
    resources = payloads["resources.json"]
    assert isinstance(assets, dict)
    assert isinstance(resources, list)
    first_asset = assets["features"][1]
    first_resource = resources[1]
    assert isinstance(first_asset, dict)
    assert isinstance(first_resource, dict)
    properties = first_asset["properties"]
    assert isinstance(properties, dict)

    if case == "duplicate_asset":
        first_asset["properties"] = {**properties, "asset_id": "zebra-2"}
    elif case == "missing_demand":
        properties["raw_metadata"] = {}
    elif case == "unknown_asset_field":
        properties["extra"] = True
    elif case == "asset_source_version_mismatch":
        properties["source_version"] = "wrong"
    elif case == "asset_outside_bbox":
        first_asset["geometry"] = {"type": "Point", "coordinates": [-120.2, 39.8]}
    elif case == "boolean_asset_coordinate":
        first_asset["geometry"] = {"type": "Point", "coordinates": [True, 39.8]}
    elif case == "three_dimensional_asset":
        first_asset["geometry"] = {"type": "Point", "coordinates": [-121.6, 39.8, 1]}
    elif case == "nested_asset_point":
        first_asset["geometry"] = {
            "type": "Point",
            "coordinates": [[-121.6, 39.8]],
        }
    elif case == "unclosed_polygon":
        first_asset["geometry"] = {
            "type": "Polygon",
            "coordinates": [
                [[-121.6, 39.8], [-121.5, 39.8], [-121.5, 39.9]],
            ],
        }
    elif case == "multipolygon_empty_member":
        first_asset["geometry"] = {
            "type": "MultiPolygon",
            "coordinates": [
                [
                    [
                        [-121.6, 39.8],
                        [-121.5, 39.8],
                        [-121.5, 39.9],
                        [-121.6, 39.8],
                    ]
                ],
                [],
            ],
        }
    elif case == "resource_not_point":
        first_resource["geometry_geojson"] = {
            "type": "LineString",
            "coordinates": [[-121.6, 39.8], [-121.5, 39.9]],
        }
    elif case == "resource_outside_bbox":
        first_resource["geometry_geojson"] = {
            "type": "Point",
            "coordinates": [-120.2, 39.8],
        }
    elif case == "resource_not_simulated":
        first_resource["raw_metadata"] = {"simulated": False}
    elif case == "nested_resource_point":
        first_resource["geometry_geojson"] = {
            "type": "Point",
            "coordinates": [[-121.61, 39.81]],
        }
    elif case == "duplicate_capability":
        first_resource["capabilities"] = ["water", "water"]
    elif case == "partial_static_group":
        del payloads["resources.json"]
    else:
        raise AssertionError(f"unknown case: {case}")
    return _files(payloads)


@pytest.mark.parametrize(
    ("case", "message"),
    [
        (
            "duplicate_asset",
            r"^exposed_assets\.geojson: duplicate asset_id: zebra-2$",
        ),
        (
            "missing_demand",
            r"^exposed_assets\.geojson: community-1: raw_metadata\.demand is required$",
        ),
        (
            "unknown_asset_field",
            r"^exposed_assets\.geojson: community-1: unsupported property: extra$",
        ),
        (
            "asset_source_version_mismatch",
            r"^exposed_assets\.geojson: community-1: source_version does not match static_data_versions$",
        ),
        (
            "asset_outside_bbox",
            r"^exposed_assets\.geojson: community-1: geometry is outside manifest region\.bbox$",
        ),
        (
            "boolean_asset_coordinate",
            r"^exposed_assets\.geojson: community-1: geometry coordinates must be finite two-dimensional numbers$",
        ),
        (
            "three_dimensional_asset",
            r"^exposed_assets\.geojson: community-1: geometry coordinates must be finite two-dimensional numbers$",
        ),
        (
            "nested_asset_point",
            r"^exposed_assets\.geojson: community-1: geometry coordinates must be finite two-dimensional numbers$",
        ),
        (
            "unclosed_polygon",
            r"^exposed_assets\.geojson: community-1: geometry must be nonempty and valid$",
        ),
        (
            "multipolygon_empty_member",
            r"^exposed_assets\.geojson: community-1: geometry must be nonempty and valid$",
        ),
        (
            "resource_not_point",
            r"^resources\.json: engine-1: geometry_geojson must be a Point$",
        ),
        (
            "resource_outside_bbox",
            r"^resources\.json: engine-1: geometry is outside manifest region\.bbox$",
        ),
        (
            "nested_resource_point",
            r"^resources\.json: engine-1: geometry coordinates must be finite two-dimensional numbers$",
        ),
        (
            "resource_not_simulated",
            r"^resources\.json: engine-1: raw_metadata\.simulated must be true$",
        ),
        (
            "duplicate_capability",
            r"^resources\.json: engine-1: capabilities contain duplicates$",
        ),
        (
            "partial_static_group",
            r"^missing required static file: resources\.json$",
        ),
    ],
)
def test_static_data_rejects_invalid_contract(case: str, message: str) -> None:
    with pytest.raises(ReplayStaticDataInvalid, match=message):
        parse_replay_static_data(_mutated_complete_files(case), _manifest())


@pytest.mark.parametrize(
    ("filename", "context", "target", "replacement"),
    [
        (
            "exposed_assets.geojson",
            "zebra-2",
            b'"labels": ["priority"]',
            b'"overflow": 1e999',
        ),
        (
            "resources.json",
            "z-engine",
            b'"simulated": true',
            b'"simulated": true, "overflow": 1e999',
        ),
    ],
)
def test_static_data_translates_literal_overflow_in_raw_metadata(
    filename: str, context: str, target: bytes, replacement: bytes
) -> None:
    files = _complete_files()
    assert target in files[filename]
    files[filename] = files[filename].replace(target, replacement, 1)

    with pytest.raises(
        ReplayStaticDataInvalid,
        match=rf"^{filename}: {context}: raw_payload contains unsupported JSON value: non-finite float$",
    ):
        parse_replay_static_data(files, _manifest())


def test_static_data_translates_deep_asset_raw_metadata() -> None:
    files = _complete_files()
    target = b'"labels": ["priority"]'
    deeply_nested = b'"deep": ' + b"[" * 500 + b"0" + b"]" * 500
    assert target in files["exposed_assets.geojson"]
    files["exposed_assets.geojson"] = files["exposed_assets.geojson"].replace(
        target, deeply_nested, 1
    )

    with pytest.raises(
        ReplayStaticDataInvalid,
        match=r"^exposed_assets\.geojson: zebra-2: JSON is too deeply nested$",
    ):
        parse_replay_static_data(files, _manifest())


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda files: files.__setitem__(
                "static_data_versions.json", b'{"census":"a","census":"b"}'
            ),
            r"static_data_versions\.json: duplicate JSON key: census",
        ),
        (
            lambda files: files.__setitem__("resources.json", b"[NaN]"),
            r"resources\.json: invalid JSON number: NaN",
        ),
        (
            lambda files: files.__setitem__("resources.json", b"\xff"),
            r"resources\.json: invalid JSON",
        ),
        (
            lambda files: files.__setitem__("exposed_assets.geojson", b"[]"),
            r"exposed_assets\.geojson: FeatureCollection must be an object",
        ),
        (
            lambda files: files.__setitem__(
                "exposed_assets.geojson", b'{"type":"FeatureCollection","features":[]}'
            ),
            r"exposed_assets\.geojson: features must be nonempty",
        ),
        (
            lambda files: files.__setitem__("resources.json", b"[]"),
            r"resources\.json: must be a nonempty array",
        ),
    ],
)
def test_static_data_rejects_malformed_top_level_values(
    mutate: Callable[[dict[str, bytes]], None], message: str
) -> None:
    files = _complete_files()
    mutate(files)
    with pytest.raises(ReplayStaticDataInvalid, match=message):
        parse_replay_static_data(files, _manifest())


@pytest.mark.parametrize(
    ("filename", "message"),
    [
        (
            "static_data_versions.json",
            r"static_data_versions\.json missing required key: simulated_resources",
        ),
        (
            "source_citations.json",
            r"source_citations\.json missing required key: simulated_resources",
        ),
    ],
)
def test_static_data_requires_simulated_resource_provenance(
    filename: str, message: str
) -> None:
    payloads = _complete_payloads()
    provenance = payloads[filename]
    assert isinstance(provenance, dict)
    del provenance["simulated_resources"]

    with pytest.raises(ReplayStaticDataInvalid, match=message):
        parse_replay_static_data(_files(payloads), _manifest())


@pytest.mark.parametrize(
    "filename", ["static_data_versions.json", "source_citations.json"]
)
@pytest.mark.parametrize(
    "key", [".", "..", "../source", "nested/source", "nested\\source"]
)
def test_static_data_rejects_unsafe_provenance_keys(filename: str, key: str) -> None:
    payloads = _complete_payloads()
    provenance = payloads[filename]
    assert isinstance(provenance, dict)
    provenance[key] = "recorded-test-v1"

    with pytest.raises(
        ReplayStaticDataInvalid,
        match=rf"unsafe {filename} key: {re.escape(key)}",
    ):
        parse_replay_static_data(_files(payloads), _manifest())


def test_static_data_rejects_empty_and_unsafe_provenance_strings() -> None:
    payloads = _complete_payloads()
    versions = payloads["static_data_versions.json"]
    assert isinstance(versions, dict)
    versions["census"] = ""

    with pytest.raises(
        ReplayStaticDataInvalid,
        match=r"static_data_versions\.json: value for census must be a nonblank string",
    ):
        parse_replay_static_data(_files(payloads), _manifest())

    payloads = _complete_payloads()
    assets = payloads["exposed_assets.geojson"]
    assert isinstance(assets, dict)
    feature = assets["features"][1]
    assert isinstance(feature, dict)
    properties = feature["properties"]
    assert isinstance(properties, dict)
    properties["asset_kind"] = "community\n"

    with pytest.raises(
        ReplayStaticDataInvalid,
        match=r"^exposed_assets\.geojson: community-1: asset_kind must be a nonblank string$",
    ):
        parse_replay_static_data(_files(payloads), _manifest())


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda payloads: payloads["exposed_assets.geojson"]["features"][1][
                "properties"
            ].__setitem__("asset_id", " "),  # type: ignore[index]
            r"^exposed_assets\.geojson: asset_id must be a nonblank string$",
        ),
        (
            lambda payloads: payloads["exposed_assets.geojson"]["features"][1][
                "properties"
            ].__setitem__("population", -1),  # type: ignore[index]
            r"^exposed_assets\.geojson: community-1: population must be a nonnegative integer or null$",
        ),
        (
            lambda payloads: payloads["exposed_assets.geojson"]["features"][1][
                "properties"
            ]["raw_metadata"]["demand"].__setitem__("required_capacity", 0),  # type: ignore[index]
            r"^exposed_assets\.geojson: community-1: raw_metadata\.demand\.required_capacity must be a positive integer$",
        ),
        (
            lambda payloads: payloads["source_citations.json"].__delitem__("census"),  # type: ignore[union-attr]
            r"^exposed_assets\.geojson: zebra-2: source_name is missing from source_citations$",
        ),
        (
            lambda payloads: payloads["exposed_assets.geojson"]["features"][
                1
            ].__setitem__("geometry", {"type": "Polygon", "coordinates": []}),  # type: ignore[index]
            r"^exposed_assets\.geojson: community-1: geometry must be nonempty and valid$",
        ),
        (
            lambda payloads: payloads["resources.json"][1].__setitem__(
                "resource_id", "z-engine"
            ),  # type: ignore[index]
            r"^resources\.json: duplicate resource_id: z-engine$",
        ),
        (
            lambda payloads: payloads["resources.json"][1].__setitem__(
                "resource_id", " "
            ),  # type: ignore[index]
            r"^resources\.json: resource_id must be a nonblank string$",
        ),
        (
            lambda payloads: payloads["resources.json"][1].__setitem__(
                "capacity", True
            ),  # type: ignore[index]
            r"^resources\.json: engine-1: capacity must be a positive integer$",
        ),
        (
            lambda payloads: payloads["resources.json"][1].__setitem__("extra", True),  # type: ignore[index]
            r"^resources\.json: engine-1: unsupported field: extra$",
        ),
        (
            lambda payloads: payloads["exposed_assets.geojson"]["features"][1][
                "properties"
            ].__setitem__("capacity", True),  # type: ignore[index]
            r"^exposed_assets\.geojson: community-1: capacity must be a nonnegative integer or null$",
        ),
        (
            lambda payloads: payloads["exposed_assets.geojson"]["features"][1][
                "properties"
            ]["raw_metadata"]["demand"].__setitem__("required_capacity", True),  # type: ignore[index]
            r"^exposed_assets\.geojson: community-1: raw_metadata\.demand\.required_capacity must be a positive integer$",
        ),
        (
            lambda payloads: payloads["exposed_assets.geojson"]["features"][
                1
            ].__setitem__(
                "geometry",
                {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-121.6, 39.8],
                            [-121.5, 39.9],
                            [-121.6, 39.9],
                            [-121.5, 39.8],
                            [-121.6, 39.8],
                        ]
                    ],
                },
            ),  # type: ignore[index]
            r"^exposed_assets\.geojson: community-1: geometry must be nonempty and valid$",
        ),
    ],
)
def test_static_data_rejects_entity_invariants(
    mutate: Callable[[dict[str, object]], None], message: str
) -> None:
    payloads = _complete_payloads()
    mutate(payloads)
    with pytest.raises(ReplayStaticDataInvalid, match=message):
        parse_replay_static_data(_files(payloads), _manifest())
