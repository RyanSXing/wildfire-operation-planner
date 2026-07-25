import json
import multiprocessing
import os
import time
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from shutil import copyfile

import networkx as nx
import pytest

from wildfireops.geospatial import road_graph as road_graph_module
from wildfireops.geospatial.road_graph import (
    RoadGraph,
    RoadGraphBuildError,
    RoadGraphInvalid,
    RetrievedRoadGraph,
    RouteStatus,
    build_road_graph,
    compute_route,
    main,
    nearest_road_node,
)
from wildfireops.replay.manifest import ReplayManifest
from wildfireops.replay.loader import ReplayLoader


def test_closed_roads_change_the_shortest_route_and_can_make_it_unreachable() -> None:
    graph = nx.MultiDiGraph()
    graph.add_edge(
        "A",
        "B",
        edge_id="AB",
        travel_minutes=5.0,
        distance_meters=500.0,
    )
    graph.add_edge(
        "B",
        "C",
        edge_id="BC",
        travel_minutes=5.0,
        distance_meters=500.0,
    )
    graph.add_edge(
        "A",
        "C",
        edge_id="AC",
        travel_minutes=15.0,
        distance_meters=1_200.0,
    )
    roads = RoadGraph.from_graph(graph)

    baseline = compute_route(roads, "A", "C", ())
    fallback = compute_route(roads, "A", "C", ("BC",))
    unreachable = compute_route(roads, "A", "C", ("BC", "AC"))

    assert baseline.status is RouteStatus.REACHABLE
    assert baseline.edge_ids == ("AB", "BC")
    assert baseline.travel_minutes == 10.0
    assert fallback.status is RouteStatus.REACHABLE
    assert fallback.edge_ids == ("AC",)
    assert fallback.travel_minutes == 15.0
    assert unreachable.status is RouteStatus.UNREACHABLE
    assert unreachable.edge_ids == ()


def test_load_pins_the_graphml_digest_and_preserves_parallel_directed_edges(
    tmp_path: Path,
) -> None:
    graph = nx.MultiDiGraph()
    graph.add_edge(
        "A",
        "B",
        key="slow",
        edge_id="AB-slow",
        travel_minutes=9.0,
        distance_meters=900.0,
    )
    graph.add_edge(
        "A",
        "B",
        key="fast",
        edge_id="AB-fast",
        travel_minutes=4.0,
        distance_meters=450.0,
    )
    graph.add_edge(
        "B",
        "C",
        edge_id="BC",
        travel_minutes=3.0,
        distance_meters=300.0,
    )
    path = tmp_path / "roads.graphml.gz"
    nx.write_graphml(graph, path)

    roads = RoadGraph.load(path)
    result = compute_route(roads, "A", "C", ())

    assert roads.graph_version == sha256(path.read_bytes()).hexdigest()
    assert result.edge_ids == ("AB-fast", "BC")
    assert result.travel_minutes == 7.0
    assert result.distance_meters == 750.0


def test_literal_toy_edges_without_distance_default_to_zero_meters() -> None:
    graph = nx.DiGraph()
    graph.add_edge("A", "B", edge_id="AB", travel_minutes=5.0)

    result = compute_route(RoadGraph.from_graph(graph), "A", "B", ())

    assert result.status is RouteStatus.REACHABLE
    assert result.distance_meters == 0.0


def test_graphml_coordinate_strings_are_normalized_for_routing() -> None:
    graph = _coordinate_graph(x="-121.7", y="39.7")

    roads = RoadGraph.from_graph(graph)

    assert roads._graph.nodes["A"] == {"x": -121.7, "y": 39.7}
    assert nearest_road_node(roads, -121.7, 39.7) == "A"


@pytest.mark.parametrize(
    ("coordinate", "value"),
    [
        ("x", "nan"),
        ("y", "inf"),
        ("x", True),
        ("y", False),
        ("x", ""),
        ("y", "not-a-coordinate"),
    ],
)
def test_present_graph_node_coordinates_must_be_finite_numbers(
    coordinate: str,
    value: object,
) -> None:
    coordinates: dict[str, object] = {"x": -121.7, "y": 39.7}
    coordinates[coordinate] = value

    with pytest.raises(
        RoadGraphInvalid, match=f"node {coordinate} must be a finite number"
    ):
        RoadGraph.from_graph(_coordinate_graph(**coordinates))


@pytest.mark.parametrize(
    ("coordinates", "node"),
    [
        ({"x": 181, "y": 0}, "A"),
        ({"x": 0, "y": 90.1}, "A"),
    ],
)
def test_node_position_rejects_coordinates_outside_wgs84_bounds(
    coordinates: dict[str, object],
    node: str,
) -> None:
    roads = RoadGraph.from_graph(_coordinate_graph(**coordinates))

    assert roads.node_coordinates == ((-121.6, 39.8),)
    with pytest.raises(
        RoadGraphInvalid,
        match=rf"^road node has coordinates outside WGS84 bounds: {node!r}$",
    ):
        roads.node_position(node)


def test_road_edge_catalog_is_stable_geographic_and_read_only() -> None:
    graph = nx.MultiDiGraph()
    graph.add_node("A", x=-121.7, y=39.7)
    graph.add_node("B", x=-121.6, y=39.8)
    graph.add_nodes_from(("missing-origin", "missing-destination"))
    graph.add_edge(
        "A",
        "B",
        edge_id="z-shaped",
        name="  Ridge Road  ",
        geometry="LINESTRING (-121.7 39.7, -121.65 39.76, -121.6 39.8)",
        travel_minutes=4.5,
        distance_meters=450.0,
    )
    graph.add_edge(
        "B",
        "A",
        edge_id="a-fallback",
        name="   ",
        travel_minutes=5.0,
        distance_meters=500.0,
    )
    graph.add_edge(
        "missing-origin",
        "missing-destination",
        edge_id="m-unavailable",
        travel_minutes=7.0,
        distance_meters=700.0,
    )
    roads = RoadGraph.from_graph(graph)
    version = roads.graph_version
    route = compute_route(roads, "A", "B", ())

    assert roads.road_edges == (
        road_graph_module.RoadEdge(
            edge_id="a-fallback",
            label="a-fallback",
            geometry=((-121.6, 39.8), (-121.7, 39.7)),
            travel_minutes=5.0,
            distance_meters=500.0,
        ),
        road_graph_module.RoadEdge(
            edge_id="m-unavailable",
            label="m-unavailable",
            geometry=None,
            travel_minutes=7.0,
            distance_meters=700.0,
        ),
        road_graph_module.RoadEdge(
            edge_id="z-shaped",
            label="Ridge Road",
            geometry=(
                (-121.7, 39.7),
                (-121.65, 39.76),
                (-121.6, 39.8),
            ),
            travel_minutes=4.5,
            distance_meters=450.0,
        ),
    )
    assert roads.node_coordinates == ((-121.7, 39.7), (-121.6, 39.8))
    assert roads.node_position("A") == (-121.7, 39.7)
    with pytest.raises(RoadGraphInvalid, match="unknown road node"):
        roads.node_position("missing")
    with pytest.raises(RoadGraphInvalid, match="has no finite coordinates"):
        roads.node_position("missing-origin")
    with pytest.raises(FrozenInstanceError):
        setattr(roads.road_edges[0], "label", "Changed")
    assert roads.graph_version == version
    assert compute_route(roads, "A", "B", ()) == route


def test_parallel_ties_and_zero_cost_cycles_use_deterministic_hop_edge_order() -> None:
    first = nx.MultiDiGraph()
    first.add_edge(
        "A",
        "A",
        key="cycle",
        edge_id="AA",
        travel_minutes=0.0,
        distance_meters=0.0,
    )
    first.add_edge(
        "A",
        "B",
        key="higher",
        edge_id="AB-2",
        travel_minutes=5.0,
        distance_meters=500.0,
    )
    first.add_edge(
        "A",
        "B",
        key="lower",
        edge_id="AB-1",
        travel_minutes=5.0,
        distance_meters=500.0,
    )
    second = nx.MultiDiGraph()
    for origin, destination, key, data in reversed(
        list(first.edges(keys=True, data=True))
    ):
        second.add_edge(origin, destination, key=key, **data)

    first_roads = RoadGraph.from_graph(first)
    second_roads = RoadGraph.from_graph(second)

    assert first_roads.graph_version == second_roads.graph_version
    assert compute_route(first_roads, "A", "B", ()).edge_ids == ("AB-1",)
    assert compute_route(second_roads, "A", "B", ()).edge_ids == ("AB-1",)


def test_closure_hash_and_route_cache_canonicalize_duplicate_input_order() -> None:
    graph = nx.MultiDiGraph()
    graph.add_edge(
        "A",
        "B",
        edge_id="AB",
        travel_minutes=5.0,
        distance_meters=500.0,
    )
    graph.add_edge(
        "A",
        "C",
        edge_id="AC",
        travel_minutes=6.0,
        distance_meters=600.0,
    )
    roads = RoadGraph.from_graph(graph)

    first = compute_route(roads, "A", "B", ("AC", "AC"))
    second = compute_route(roads, "A", "B", ["AC"])

    assert second is first
    assert second.closure_hash == first.closure_hash


def test_load_reads_and_parses_each_resolved_graph_path_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = nx.MultiDiGraph()
    graph.add_edge(
        "A",
        "B",
        edge_id="AB",
        travel_minutes="5.0",
        length="450.0",
    )
    path = tmp_path / "roads.graphml"
    nx.write_graphml(graph, path)
    from wildfireops.geospatial import road_graph

    reads = 0
    original = road_graph._read_graph_bytes

    def counting_read(graph_path: Path) -> bytes:
        nonlocal reads
        reads += 1
        return original(graph_path)

    monkeypatch.setattr(road_graph, "_read_graph_bytes", counting_read)

    first = RoadGraph.load(path)
    second = RoadGraph.load(path)

    assert second is first
    assert reads == 1
    assert compute_route(first, "A", "B", ()).distance_meters == 450.0


def test_load_wraps_a_truncated_gzip_as_invalid_graphml(tmp_path: Path) -> None:
    path = tmp_path / "roads.graphml.gz"
    path.write_bytes(b"\x1f\x8btruncated")

    with pytest.raises(RoadGraphInvalid, match="not valid GraphML"):
        RoadGraph.load(path)


@pytest.mark.parametrize(
    ("first_data", "second_data", "message"),
    [
        (
            {"edge_id": " ", "travel_minutes": 1.0, "distance_meters": 1.0},
            None,
            "edge_id must be a nonblank string",
        ),
        (
            {"edge_id": "same", "travel_minutes": 1.0, "distance_meters": 1.0},
            {"edge_id": "same", "travel_minutes": 2.0, "distance_meters": 2.0},
            "duplicate edge_id: same",
        ),
        (
            {
                "edge_id": "bad-time",
                "travel_minutes": "nan",
                "distance_meters": 1.0,
            },
            None,
            "travel_minutes must be a finite nonnegative number",
        ),
        (
            {
                "edge_id": "bad-distance",
                "travel_minutes": 1.0,
                "distance_meters": -1.0,
            },
            None,
            "distance_meters must be a finite nonnegative number",
        ),
    ],
)
def test_malformed_graph_edges_are_rejected_deliberately(
    first_data: dict[str, object],
    second_data: dict[str, object] | None,
    message: str,
) -> None:
    graph = nx.MultiDiGraph()
    graph.add_edge("A", "B", **first_data)
    if second_data is not None:
        graph.add_edge("B", "C", **second_data)

    with pytest.raises(RoadGraphInvalid, match=message):
        RoadGraph.from_graph(graph)


def test_missing_route_endpoint_is_explicitly_unreachable() -> None:
    graph = nx.MultiDiGraph()
    graph.add_edge(
        "A",
        "B",
        edge_id="AB",
        travel_minutes=1.0,
        distance_meters=100.0,
    )
    roads = RoadGraph.from_graph(graph)

    result = compute_route(roads, "missing", "B", ())

    assert result.status is RouteStatus.UNREACHABLE
    assert result.edge_ids == ()
    assert result.graph_version == roads.graph_version


def test_parallel_edge_closure_falls_back_to_the_open_parallel_edge() -> None:
    graph = nx.MultiDiGraph()
    graph.add_edge(
        "A",
        "B",
        key="fast",
        edge_id="AB-fast",
        travel_minutes=2.0,
        distance_meters=200.0,
    )
    graph.add_edge(
        "A",
        "B",
        key="slow",
        edge_id="AB-slow",
        travel_minutes=5.0,
        distance_meters=400.0,
    )
    roads = RoadGraph.from_graph(graph)

    result = compute_route(roads, "A", "B", ("AB-fast",))

    assert result.edge_ids == ("AB-slow",)
    assert result.travel_minutes == 5.0


def test_road_graph_version_identity_is_immutable() -> None:
    graph = nx.MultiDiGraph()
    graph.add_edge(
        "A",
        "B",
        edge_id="AB",
        travel_minutes=1.0,
        distance_meters=100.0,
    )
    roads = RoadGraph.from_graph(graph)

    with pytest.raises(FrozenInstanceError):
        roads.graph_version = "changed"


def _coordinate_graph(**coordinates: object) -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph()
    graph.add_node("A", **coordinates)
    graph.add_node("B", x=-121.6, y=39.8)
    graph.add_edge(
        "A",
        "B",
        edge_id="AB",
        travel_minutes=5.0,
        distance_meters=500.0,
    )
    return graph


def _raw_osm_graph() -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph()
    graph.graph["crs"] = "EPSG:4326"
    graph.add_node(100, x=-121.6, y=39.8)
    graph.add_node(200, x=-121.5, y=39.9)
    graph.add_edge(
        100,
        200,
        key=0,
        osmid=12345,
        length=1_000.0,
        speed_kph=60.0,
        travel_time=60.0,
    )
    return graph


def _build_test_graph(output: Path) -> Path:
    return build_road_graph(
        bbox=(-122.4, 39.2, -120.3, 41.0),
        output=output,
        retriever=lambda bbox, network_type: RetrievedRoadGraph(
            _raw_osm_graph(),
            "2.1.0-test",
        ),
        clock=lambda: datetime(2024, 7, 25, 12, tzinfo=UTC),
    )


def _canonical_json(payload: object) -> str:
    return (
        json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    )


def _wait_for_path(path: Path, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.01)
    return path.exists()


def _concurrent_build_worker(
    package: Path,
    label: str,
    entered: Path | None,
    retrieved: Path,
    release: Path | None,
    result: Path,
) -> None:
    if entered is not None:
        entered.touch()

    def retrieve(
        bbox: tuple[float, float, float, float],
        network_type: str,
    ) -> RetrievedRoadGraph:
        retrieved.touch()
        if release is not None and not _wait_for_path(release, timeout=10.0):
            raise RuntimeError("timed out waiting to release retrieval")
        graph = _raw_osm_graph()
        graph.edges[100, 200, 0]["length"] = 1_000.0 if label == "first" else 2_000.0
        return RetrievedRoadGraph(graph, f"2.1.0-{label}")

    try:
        build_road_graph(
            bbox=(-122.4, 39.2, -120.3, 41.0),
            output=package / "roads.graphml.gz",
            retriever=retrieve,
            clock=lambda: datetime(2024, 7, 25, 12, tzinfo=UTC),
        )
    except RoadGraphBuildError as error:
        result.write_text(f"error:{error}", encoding="utf-8")
    else:
        result.write_text("ok", encoding="utf-8")


def _concurrent_manifest_writer(
    package: Path,
    commit_ready: Path,
    write_started: Path,
    result: Path,
) -> None:
    if not _wait_for_path(commit_ready, timeout=10.0):
        result.write_text("error:timed out waiting for commit", encoding="utf-8")
        return
    try:
        manifest_path = package / "manifest.json"
        original = manifest_path.read_bytes()
        manifest = ReplayManifest.load(manifest_path)
        write_started.touch()
        replace(manifest, package_id="concurrent-writer").write_atomic(
            manifest_path,
            expected_digest=sha256(original).hexdigest(),
        )
    except Exception as error:
        result.write_text(f"error:{error}", encoding="utf-8")
    else:
        result.write_text("ok", encoding="utf-8")


def _recover_without_retrieval(output: Path) -> ReplayManifest:
    retrieved = False

    def retrieve(
        bbox: tuple[float, float, float, float],
        network_type: str,
    ) -> RetrievedRoadGraph:
        nonlocal retrieved
        retrieved = True
        return RetrievedRoadGraph(_raw_osm_graph(), "2.1.0-test")

    assert (
        build_road_graph(
            bbox=(-122.4, 39.2, -120.3, 41.0),
            output=output,
            retriever=retrieve,
            clock=lambda: datetime(2024, 7, 25, 12, tzinfo=UTC),
        )
        == output
    )
    assert retrieved is False
    return ReplayManifest.load(output.parent / "manifest.json")


def _interrupt_after_graph_claim(
    package: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, bytes]:
    manifest_path = package / "manifest.json"
    copyfile(Path("tests/fixtures/replay-small/manifest.json"), manifest_path)
    manifest_before = manifest_path.read_bytes()
    output = package / "roads.graphml.gz"
    from wildfireops.geospatial import road_graph

    original_replace = road_graph._replace_file

    def interrupt_manifest_replace(*args: object, **kwargs: object) -> None:
        if Path(args[1]).name == manifest_path.name:
            raise KeyboardInterrupt
        original_replace(*args, **kwargs)

    monkeypatch.setattr(road_graph, "_replace_file", interrupt_manifest_replace)
    with pytest.raises(KeyboardInterrupt):
        _build_test_graph(output)
    monkeypatch.undo()
    assert output.exists()
    assert manifest_path.read_bytes() == manifest_before
    return output, manifest_before


def test_build_cli_records_exact_graph_provenance_without_live_download(
    tmp_path: Path,
) -> None:
    package = tmp_path / "park-fire"
    package.mkdir()
    fixture_manifest = Path("tests/fixtures/replay-small/manifest.json")
    copyfile(fixture_manifest, package / "manifest.json")
    copyfile(
        Path("tests/fixtures/replay-small/fire_detections.jsonl"),
        package / "fire_detections.jsonl",
    )
    output = package / "roads.graphml.gz"
    calls: list[tuple[tuple[float, float, float, float], str]] = []

    def retrieve(
        bbox: tuple[float, float, float, float],
        network_type: str,
    ) -> RetrievedRoadGraph:
        calls.append((bbox, network_type))
        return RetrievedRoadGraph(_raw_osm_graph(), "2.1.0-test")

    result = main(
        [
            "build",
            "--bbox=-122.40,39.20,-120.30,41.00",
            "--output",
            str(output),
        ],
        retriever=retrieve,
        clock=lambda: datetime(2024, 7, 25, 12, 34, 56, tzinfo=UTC),
    )

    assert result == 0
    assert calls == [((-122.4, 39.2, -120.3, 41.0), "drive")]
    assert output.read_bytes().startswith(b"\x1f\x8b")
    manifest = ReplayManifest.load(package / "manifest.json")
    assert manifest.package_id == "replay-small-v1"
    assert manifest.algorithm_config_version == "test-config-v1"
    assert manifest.road_graph is not None
    assert manifest.road_graph.filename == "roads.graphml.gz"
    assert manifest.road_graph.retrieved_at == datetime(
        2024,
        7,
        25,
        12,
        34,
        56,
        tzinfo=UTC,
    )
    assert manifest.road_graph.bbox == (-122.4, 39.2, -120.3, 41.0)
    assert manifest.road_graph.network_type == "drive"
    assert manifest.road_graph.osmnx_version == "2.1.0-test"
    assert manifest.road_graph.edge_count == 1
    assert manifest.road_graph.graph_digest == sha256(output.read_bytes()).hexdigest()
    assert manifest.files["roads.graphml.gz"] == manifest.road_graph.graph_digest
    roads = RoadGraph.load(output)
    assert len(roads.edge_ids) == 1
    assert roads.graph_version == manifest.road_graph.graph_version
    assert ReplayLoader(package).manifest.road_graph == manifest.road_graph


def test_concurrent_builds_are_serialized_across_processes(tmp_path: Path) -> None:
    package = tmp_path / "park-fire"
    package.mkdir()
    copyfile(
        Path("tests/fixtures/replay-small/manifest.json"), package / "manifest.json"
    )
    first_retrieved = tmp_path / "first-retrieved"
    first_result = tmp_path / "first-result"
    second_entered = tmp_path / "second-entered"
    second_retrieved = tmp_path / "second-retrieved"
    second_result = tmp_path / "second-result"
    release = tmp_path / "release"
    context = multiprocessing.get_context("fork")
    first = context.Process(
        target=_concurrent_build_worker,
        args=(
            package,
            "first",
            None,
            first_retrieved,
            release,
            first_result,
        ),
    )
    second = context.Process(
        target=_concurrent_build_worker,
        args=(
            package,
            "second",
            second_entered,
            second_retrieved,
            None,
            second_result,
        ),
    )

    first.start()
    assert _wait_for_path(first_retrieved)
    second.start()
    try:
        assert _wait_for_path(second_entered)
        second_retrieved_before_release = _wait_for_path(
            second_retrieved,
            timeout=1.0,
        )
    finally:
        release.touch()
        first.join(timeout=10.0)
        second.join(timeout=10.0)

    assert first.exitcode == 0
    assert second.exitcode == 0
    assert second_retrieved_before_release is False
    assert first_result.read_text(encoding="utf-8") == "ok"
    assert second_result.read_text(encoding="utf-8").startswith("error:")
    output = package / "roads.graphml.gz"
    manifest = ReplayManifest.load(package / "manifest.json")
    assert manifest.road_graph is not None
    assert manifest.road_graph.graph_digest == sha256(output.read_bytes()).hexdigest()


def test_manifest_writer_cannot_enter_between_base_check_and_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = tmp_path / "park-fire"
    package.mkdir()
    copyfile(
        Path("tests/fixtures/replay-small/manifest.json"), package / "manifest.json"
    )
    commit_ready = tmp_path / "commit-ready"
    write_started = tmp_path / "write-started"
    writer_result = tmp_path / "writer-result"
    writer_completed_during_commit = False
    context = multiprocessing.get_context("fork")
    writer = context.Process(
        target=_concurrent_manifest_writer,
        args=(package, commit_ready, write_started, writer_result),
    )
    from wildfireops.geospatial import road_graph

    original_replace = road_graph._replace_file

    def pause_before_manifest_replace(*args: object, **kwargs: object) -> None:
        nonlocal writer_completed_during_commit
        destination = Path(args[1])
        if destination.name == "manifest.json" and not commit_ready.exists():
            commit_ready.touch()
            assert _wait_for_path(write_started)
            writer_completed_during_commit = _wait_for_path(
                writer_result,
                timeout=0.25,
            )
        original_replace(*args, **kwargs)

    monkeypatch.setattr(road_graph, "_replace_file", pause_before_manifest_replace)
    writer.start()
    try:
        _build_test_graph(package / "roads.graphml.gz")
    finally:
        writer.join(timeout=10.0)
        if writer.is_alive():
            writer.terminate()
            writer.join(timeout=5.0)

    assert writer.exitcode == 0
    assert writer_result.read_text(encoding="utf-8") == (
        "error:manifest.json changed before write"
    )
    assert writer_completed_during_commit is False
    manifest = ReplayManifest.load(package / "manifest.json")
    output = package / "roads.graphml.gz"
    assert manifest.package_id == "replay-small-v1"
    assert manifest.road_graph is not None
    assert manifest.road_graph.graph_digest == sha256(output.read_bytes()).hexdigest()


def test_graph_path_replacement_at_manifest_commit_restores_the_base_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = tmp_path / "park-fire"
    package.mkdir()
    manifest_path = package / "manifest.json"
    copyfile(Path("tests/fixtures/replay-small/manifest.json"), manifest_path)
    manifest_before = manifest_path.read_bytes()
    output = package / "roads.graphml.gz"
    displaced = package / "claimed.graphml.gz"
    unrelated = b"replacement graph"
    raced = False
    from wildfireops.geospatial import road_graph

    original_replace = road_graph._replace_file

    def replace_graph_at_commit(*args: object, **kwargs: object) -> None:
        nonlocal raced
        destination = Path(args[1])
        if destination.name == "manifest.json" and not raced:
            output.replace(displaced)
            output.write_bytes(unrelated)
            raced = True
        original_replace(*args, **kwargs)

    monkeypatch.setattr(road_graph, "_replace_file", replace_graph_at_commit)

    with pytest.raises(RoadGraphBuildError, match="road graph changed"):
        _build_test_graph(output)

    assert raced is True
    assert output.read_bytes() == unrelated
    assert displaced.exists()
    assert manifest_path.read_bytes() == manifest_before


def test_package_directory_swap_never_redirects_publication(tmp_path: Path) -> None:
    package = tmp_path / "park-fire"
    package.mkdir()
    fixture = Path("tests/fixtures/replay-small/manifest.json")
    copyfile(fixture, package / "manifest.json")
    displaced = tmp_path / "opened-package"
    replacement_marker = b"replacement package"

    def retrieve(
        bbox: tuple[float, float, float, float],
        network_type: str,
    ) -> RetrievedRoadGraph:
        package.rename(displaced)
        package.mkdir()
        copyfile(fixture, package / "manifest.json")
        (package / "marker").write_bytes(replacement_marker)
        return RetrievedRoadGraph(_raw_osm_graph(), "2.1.0-test")

    with pytest.raises(RoadGraphBuildError, match="output directory changed"):
        build_road_graph(
            bbox=(-122.4, 39.2, -120.3, 41.0),
            output=package / "roads.graphml.gz",
            retriever=retrieve,
            clock=lambda: datetime(2024, 7, 25, 12, tzinfo=UTC),
        )

    assert (package / "marker").read_bytes() == replacement_marker
    assert (package / "manifest.json").read_bytes() == fixture.read_bytes()
    assert not (package / "roads.graphml.gz").exists()


def test_journal_replacement_during_retirement_is_preserved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = tmp_path / "park-fire"
    package.mkdir()
    copyfile(
        Path("tests/fixtures/replay-small/manifest.json"), package / "manifest.json"
    )
    output = package / "roads.graphml.gz"
    unrelated = b"journal replacement owned by another writer"
    from wildfireops.geospatial import road_graph

    journal_path = package / road_graph._BUILD_JOURNAL_FILENAME
    original_lstat = Path.lstat
    original_rename = os.rename
    raced = False

    def replace_after_ownership_check(
        path: Path,
        *args: object,
        **kwargs: object,
    ) -> os.stat_result:
        nonlocal raced
        current = original_lstat(path, *args, **kwargs)
        if path == journal_path and not raced:
            path.unlink()
            path.write_bytes(unrelated)
            raced = True
        return current

    def replace_before_quarantine(
        source: str | os.PathLike[str],
        destination: str | os.PathLike[str],
        *args: object,
        **kwargs: object,
    ) -> None:
        nonlocal raced
        source_directory = kwargs.get("src_dir_fd")
        if (
            str(source) == road_graph._BUILD_JOURNAL_FILENAME
            and isinstance(source_directory, int)
            and not raced
        ):
            os.unlink(source, dir_fd=source_directory)
            descriptor = os.open(
                source,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=source_directory,
            )
            try:
                os.write(descriptor, unrelated)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            raced = True
        original_rename(source, destination, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", replace_after_ownership_check)
    monkeypatch.setattr(os, "rename", replace_before_quarantine)

    with pytest.raises(RoadGraphBuildError, match="journal changed"):
        _build_test_graph(output)

    assert raced is True
    assert any(
        path.read_bytes() == unrelated for path in package.rglob("*") if path.is_file()
    )


@pytest.mark.parametrize("case", ["missing_manifest", "bbox_mismatch"])
def test_build_preflight_fails_before_retrieval(
    tmp_path: Path,
    case: str,
) -> None:
    package = tmp_path / "park-fire"
    package.mkdir()
    if case == "bbox_mismatch":
        payload = json.loads(
            Path("tests/fixtures/replay-small/manifest.json").read_text(
                encoding="utf-8"
            )
        )
        payload["region"]["bbox"] = [-122.0, 39.2, -120.3, 41.0]
        (package / "manifest.json").write_text(
            json.dumps(payload),
            encoding="utf-8",
        )
    retrieved = False

    def retrieve(
        bbox: tuple[float, float, float, float],
        network_type: str,
    ) -> RetrievedRoadGraph:
        nonlocal retrieved
        retrieved = True
        return RetrievedRoadGraph(_raw_osm_graph(), "2.1.0-test")

    with pytest.raises(RoadGraphBuildError):
        build_road_graph(
            bbox=(-122.4, 39.2, -120.3, 41.0),
            output=package / "roads.graphml.gz",
            retriever=retrieve,
            clock=lambda: datetime(2024, 7, 25, 12, tzinfo=UTC),
        )

    assert retrieved is False
    assert not (package / "roads.graphml.gz").exists()


def test_same_osm_graph_build_is_byte_deterministic(tmp_path: Path) -> None:
    outputs: list[Path] = []
    fixture_manifest = Path("tests/fixtures/replay-small/manifest.json")
    for name in ("first", "second"):
        package = tmp_path / name
        package.mkdir()
        copyfile(fixture_manifest, package / "manifest.json")
        output = package / "roads.graphml.gz"
        build_road_graph(
            bbox=(-122.4, 39.2, -120.3, 41.0),
            output=output,
            retriever=lambda bbox, network_type: RetrievedRoadGraph(
                _raw_osm_graph(),
                "2.1.0-test",
            ),
            clock=lambda: datetime(2024, 7, 25, 12, tzinfo=UTC),
        )
        outputs.append(output)

    assert outputs[0].read_bytes() == outputs[1].read_bytes()
    first = RoadGraph.load(outputs[0])
    second = RoadGraph.load(outputs[1])
    assert first.graph_version == second.graph_version
    assert first.edge_ids == second.edge_ids


def test_manifest_publish_failure_leaves_a_recoverable_graph(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = tmp_path / "park-fire"
    package.mkdir()
    manifest_path = package / "manifest.json"
    copyfile(Path("tests/fixtures/replay-small/manifest.json"), manifest_path)
    manifest_before = manifest_path.read_bytes()
    output = package / "roads.graphml.gz"
    from wildfireops.geospatial import road_graph

    original_replace = road_graph._replace_file

    def fail_manifest_replace(*args: object, **kwargs: object) -> None:
        if Path(args[1]).name == manifest_path.name:
            raise OSError("simulated manifest publish failure")
        original_replace(*args, **kwargs)

    monkeypatch.setattr(road_graph, "_replace_file", fail_manifest_replace)

    with pytest.raises(
        RoadGraphBuildError,
        match="simulated manifest publish failure",
    ):
        _build_test_graph(output)

    assert output.exists()
    assert manifest_path.read_bytes() == manifest_before
    assert (package / road_graph._BUILD_JOURNAL_FILENAME).exists()

    monkeypatch.undo()
    manifest = _recover_without_retrieval(output)
    assert manifest.road_graph is not None
    assert manifest.road_graph.graph_digest == sha256(output.read_bytes()).hexdigest()


def test_interrupted_publication_recovers_without_retrieval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = tmp_path / "park-fire"
    package.mkdir()
    output, _ = _interrupt_after_graph_claim(package, monkeypatch)
    unrelated_temporary = package / ".manifest.json.tmp"
    unrelated_temporary.write_bytes(b"user-owned temporary")

    manifest = _recover_without_retrieval(output)

    assert unrelated_temporary.read_bytes() == b"user-owned temporary"
    assert manifest.road_graph is not None
    assert manifest.road_graph.graph_digest == sha256(output.read_bytes()).hexdigest()


def test_recovery_rejects_a_journal_that_changes_the_base_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = tmp_path / "park-fire"
    package.mkdir()
    output, manifest_before = _interrupt_after_graph_claim(package, monkeypatch)
    from wildfireops.geospatial import road_graph

    journal_path = package / road_graph._BUILD_JOURNAL_FILENAME
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    staged_manifest = json.loads(journal["manifest"])
    staged_manifest["package_id"] = "tampered-package"
    journal["manifest"] = _canonical_json(staged_manifest)
    journal_path.write_text(
        _canonical_json(journal),
        encoding="utf-8",
    )

    with pytest.raises(RoadGraphBuildError, match="journal manifest"):
        _recover_without_retrieval(output)

    assert (package / "manifest.json").read_bytes() == manifest_before
    assert output.exists()


def test_recovery_preserves_a_base_manifest_changed_after_graph_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = tmp_path / "park-fire"
    package.mkdir()
    output, _ = _interrupt_after_graph_claim(package, monkeypatch)
    manifest_path = package / "manifest.json"
    changed_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    changed_manifest["files"][output.name] = "f" * 64
    manifest_path.write_text(json.dumps(changed_manifest), encoding="utf-8")
    changed_bytes = manifest_path.read_bytes()

    with pytest.raises(RoadGraphBuildError, match="base manifest"):
        _recover_without_retrieval(output)

    assert manifest_path.read_bytes() == changed_bytes
    assert output.exists()


def test_graph_directory_fsync_failure_keeps_recovery_journal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = tmp_path / "park-fire"
    package.mkdir()
    manifest_path = package / "manifest.json"
    copyfile(Path("tests/fixtures/replay-small/manifest.json"), manifest_path)
    output = package / "roads.graphml.gz"
    from wildfireops.geospatial import road_graph

    original_fsync = road_graph._fsync_directory
    package_stat = package.stat()
    package_syncs = 0

    def fail_graph_fsync(directory: int) -> None:
        nonlocal package_syncs
        current = os.fstat(directory)
        if (
            current.st_dev == package_stat.st_dev
            and current.st_ino == package_stat.st_ino
        ):
            package_syncs += 1
        if package_syncs == 3:
            raise OSError("simulated graph directory fsync failure")
        original_fsync(directory)

    monkeypatch.setattr(road_graph, "_fsync_directory", fail_graph_fsync)

    with pytest.raises(
        RoadGraphBuildError,
        match="simulated graph directory fsync failure",
    ):
        _build_test_graph(output)

    monkeypatch.undo()
    manifest = _recover_without_retrieval(output)
    assert manifest.road_graph is not None
    assert manifest.road_graph.graph_digest == sha256(output.read_bytes()).hexdigest()


def test_output_created_after_preflight_is_never_overwritten(tmp_path: Path) -> None:
    package = tmp_path / "park-fire"
    package.mkdir()
    manifest_path = package / "manifest.json"
    copyfile(Path("tests/fixtures/replay-small/manifest.json"), manifest_path)
    manifest_before = manifest_path.read_bytes()
    output = package / "roads.graphml.gz"
    unrelated = b"user-owned output"

    def retrieve(
        bbox: tuple[float, float, float, float],
        network_type: str,
    ) -> RetrievedRoadGraph:
        output.write_bytes(unrelated)
        return RetrievedRoadGraph(_raw_osm_graph(), "2.1.0-test")

    with pytest.raises(RoadGraphBuildError, match="exists"):
        build_road_graph(
            bbox=(-122.4, 39.2, -120.3, 41.0),
            output=output,
            retriever=retrieve,
            clock=lambda: datetime(2024, 7, 25, 12, tzinfo=UTC),
        )

    assert output.read_bytes() == unrelated
    assert manifest_path.read_bytes() == manifest_before
