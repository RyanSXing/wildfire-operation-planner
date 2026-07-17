"""Immutable versioned road graphs and closure-aware deterministic routing.

Loaded paths are immutable version locations and are parsed once per process.
Distance uses ``distance_meters``, then OSMnx ``length``; literal toy edges
without either field deliberately contribute zero meters.
"""

from __future__ import annotations

import argparse
import gzip
import heapq
import json
import os
import stat
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from io import BytesIO
from itertools import count
from math import hypot, isfinite
from pathlib import Path
from threading import Lock
from typing import Hashable
from uuid import uuid4
from xml.etree.ElementTree import ParseError

import networkx as nx

from wildfireops.replay.manifest import (
    ReplayManifest,
    ReplayManifestInvalid,
    RoadGraphMetadata,
    replay_package_writer,
)


class RoadGraphInvalid(ValueError):
    """Raised when road-graph data does not satisfy the routing contract."""


class RoadGraphBuildError(ValueError):
    """Raised when a versioned replay road graph cannot be built safely."""


@dataclass(frozen=True, slots=True)
class RetrievedRoadGraph:
    graph: nx.MultiDiGraph
    osmnx_version: str


type RoadGraphRetriever = Callable[
    [tuple[float, float, float, float], str],
    RetrievedRoadGraph,
]
type UtcClock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class _PublicationJournal:
    output_name: str
    graph_digest: str
    graph_inode: int
    base_manifest_digest: str
    manifest_content: bytes


class RouteStatus(StrEnum):
    REACHABLE = "reachable"
    UNREACHABLE = "unreachable"


@dataclass(frozen=True, slots=True)
class RouteResult:
    status: RouteStatus
    edge_ids: tuple[str, ...]
    distance_meters: float
    travel_minutes: float
    graph_version: str
    closure_hash: str


@dataclass(frozen=True, slots=True)
class RoadGraph:
    _graph: nx.MultiDiGraph
    graph_version: str
    _edge_ids: frozenset[str]
    _route_cache: dict[tuple[str, str, Hashable, Hashable], RouteResult] = field(
        default_factory=dict,
        repr=False,
    )

    @classmethod
    def from_graph(cls, graph: nx.Graph) -> RoadGraph:
        directed = _validated_multidigraph(graph)
        graph_version = sha256(_canonical_graph_payload(directed)).hexdigest()
        return cls._from_validated_graph(directed, graph_version)

    @classmethod
    def load(cls, path: Path) -> RoadGraph:
        resolved = Path(path).resolve(strict=False)
        with _LOAD_CACHE_LOCK:
            cached = _LOAD_CACHE.get(resolved)
            if cached is not None:
                return cached
            content = _read_graph_bytes(resolved)
            if not content:
                raise RoadGraphInvalid("road graph file must not be empty")
            graph_version = sha256(content).hexdigest()
            try:
                graphml = (
                    gzip.decompress(content)
                    if content.startswith(b"\x1f\x8b")
                    else content
                )
                parsed = nx.read_graphml(BytesIO(graphml), force_multigraph=True)
            except (
                EOFError,
                OSError,
                ParseError,
                ValueError,
                nx.NetworkXError,
            ) as error:
                raise RoadGraphInvalid(
                    "road graph file is not valid GraphML"
                ) from error
            directed = _validated_multidigraph(parsed)
            loaded = cls._from_validated_graph(directed, graph_version)
            _LOAD_CACHE[resolved] = loaded
            return loaded

    @classmethod
    def _from_validated_graph(
        cls,
        graph: nx.MultiDiGraph,
        graph_version: str,
    ) -> RoadGraph:
        edge_ids = frozenset(
            data["edge_id"] for _, _, _, data in graph.edges(keys=True, data=True)
        )
        return cls(
            _graph=nx.freeze(graph),
            graph_version=graph_version,
            _edge_ids=edge_ids,
        )

    @property
    def edge_ids(self) -> frozenset[str]:
        return self._edge_ids


def nearest_road_node(
    graph: RoadGraph,
    longitude: float,
    latitude: float,
) -> Hashable:
    """Return the deterministic nearest finite x/y node."""
    x = _finite_coordinate(longitude, "longitude")
    y = _finite_coordinate(latitude, "latitude")
    candidates: list[tuple[float, str, Hashable]] = []
    # ponytail: O(N) scan is the MVP ceiling; use a spatial index for large graphs.
    for node, data in graph._graph.nodes(data=True):
        node_x = data.get("x")
        node_y = data.get("y")
        if (
            isinstance(node_x, bool)
            or not isinstance(node_x, int | float)
            or isinstance(node_y, bool)
            or not isinstance(node_y, int | float)
            or not isfinite(float(node_x))
            or not isfinite(float(node_y))
        ):
            continue
        candidates.append(
            (hypot(float(node_x) - x, float(node_y) - y), _node_identity(node), node)
        )
    if not candidates:
        raise RoadGraphInvalid("road graph has no finite coordinate nodes")
    return min(candidates, key=lambda item: (item[0], item[1]))[2]


def _finite_coordinate(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise RoadGraphInvalid(f"{field} must be a finite number")
    parsed = float(value)
    if not isfinite(parsed):
        raise RoadGraphInvalid(f"{field} must be a finite number")
    return parsed


def compute_route(
    graph: RoadGraph,
    origin: Hashable,
    destination: Hashable,
    closed_edge_ids: tuple[str, ...] | list[str] | frozenset[str] | set[str],
) -> RouteResult:
    closures = _canonical_closures(closed_edge_ids)
    unknown = sorted(set(closures) - graph.edge_ids)
    if unknown:
        raise RoadGraphInvalid(f"unknown closed edge ID: {unknown[0]}")
    closure_hash = sha256(
        json.dumps(closures, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    cache_key = (graph.graph_version, closure_hash, origin, destination)
    cached = graph._route_cache.get(cache_key)
    if cached is not None:
        return cached

    if origin not in graph._graph or destination not in graph._graph:
        result = _unreachable(graph, closure_hash)
        graph._route_cache[cache_key] = result
        return result

    result = _shortest_route(
        graph,
        origin=origin,
        destination=destination,
        closed_edge_ids=frozenset(closures),
        closure_hash=closure_hash,
    )
    graph._route_cache[cache_key] = result
    return result


def _shortest_route(
    graph: RoadGraph,
    *,
    origin: Hashable,
    destination: Hashable,
    closed_edge_ids: frozenset[str],
    closure_hash: str,
) -> RouteResult:
    sequence = count()
    queue: list[tuple[float, int, tuple[str, ...], int, Hashable, float]] = [
        (0.0, 0, (), next(sequence), origin, 0.0)
    ]
    best: dict[Hashable, tuple[float, int, tuple[str, ...]]] = {origin: (0.0, 0, ())}

    while queue:
        travel_minutes, hops, path, _, node, distance_meters = heapq.heappop(queue)
        if best.get(node) != (travel_minutes, hops, path):
            continue
        if node == destination:
            return RouteResult(
                status=RouteStatus.REACHABLE,
                edge_ids=path,
                distance_meters=distance_meters,
                travel_minutes=travel_minutes,
                graph_version=graph.graph_version,
                closure_hash=closure_hash,
            )

        outgoing = sorted(
            graph._graph.out_edges(node, keys=True, data=True),
            key=lambda edge: edge[3]["edge_id"],
        )
        for _, neighbor, _, data in outgoing:
            edge_id = data["edge_id"]
            if edge_id in closed_edge_ids:
                continue
            candidate = (
                travel_minutes + data["travel_minutes"],
                hops + 1,
                (*path, edge_id),
            )
            if neighbor in best and best[neighbor] <= candidate:
                continue
            best[neighbor] = candidate
            heapq.heappush(
                queue,
                (
                    candidate[0],
                    candidate[1],
                    candidate[2],
                    next(sequence),
                    neighbor,
                    distance_meters + data["distance_meters"],
                ),
            )

    return _unreachable(graph, closure_hash)


def _unreachable(graph: RoadGraph, closure_hash: str) -> RouteResult:
    return RouteResult(
        status=RouteStatus.UNREACHABLE,
        edge_ids=(),
        distance_meters=0.0,
        travel_minutes=0.0,
        graph_version=graph.graph_version,
        closure_hash=closure_hash,
    )


def _validated_multidigraph(graph: nx.Graph) -> nx.MultiDiGraph:
    if not graph.is_directed():
        raise RoadGraphInvalid("road graph must be directed")
    validated: nx.MultiDiGraph = nx.MultiDiGraph()
    validated.add_nodes_from(graph.nodes(data=True))
    edge_ids: set[str] = set()
    edges = (
        graph.edges(keys=True, data=True)  # type: ignore[call-overload]
        if graph.is_multigraph()
        else (
            (origin, destination, 0, data)
            for origin, destination, data in graph.edges(data=True)
        )
    )
    for origin, destination, key, raw_data in edges:
        data = dict(raw_data)
        edge_id = data.get("edge_id")
        if not isinstance(edge_id, str) or not edge_id.strip():
            raise RoadGraphInvalid("edge_id must be a nonblank string")
        edge_id = edge_id.strip()
        if edge_id in edge_ids:
            raise RoadGraphInvalid(f"duplicate edge_id: {edge_id}")
        edge_ids.add(edge_id)
        data["edge_id"] = edge_id
        data["travel_minutes"] = _finite_nonnegative(
            data.get("travel_minutes"),
            f"edge {edge_id} travel_minutes",
        )
        data["distance_meters"] = _finite_nonnegative(
            data.get("distance_meters", data.get("length", 0.0)),
            f"edge {edge_id} distance_meters",
        )
        validated.add_edge(origin, destination, key=key, **data)
    return validated


def _finite_nonnegative(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise RoadGraphInvalid(f"{field} must be a finite nonnegative number")
    if isinstance(value, str) and not value.strip():
        raise RoadGraphInvalid(f"{field} must be a finite nonnegative number")
    try:
        parsed = float(value)
    except (OverflowError, ValueError):
        raise RoadGraphInvalid(f"{field} must be a finite nonnegative number") from None
    if not isfinite(parsed) or parsed < 0:
        raise RoadGraphInvalid(f"{field} must be a finite nonnegative number")
    return parsed


def _canonical_graph_payload(graph: nx.MultiDiGraph) -> bytes:
    edges = [
        {
            "origin": _node_identity(origin),
            "destination": _node_identity(destination),
            "key": _node_identity(key),
            "edge_id": data["edge_id"],
            "travel_minutes": data["travel_minutes"],
            "distance_meters": data["distance_meters"],
        }
        for origin, destination, key, data in graph.edges(keys=True, data=True)
    ]
    edges.sort(
        key=lambda edge: (
            edge["origin"],
            edge["destination"],
            edge["key"],
            edge["edge_id"],
        )
    )
    return json.dumps(
        {
            "nodes": sorted(_node_identity(node) for node in graph.nodes),
            "edges": edges,
        },
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _node_identity(value: object) -> str:
    return f"{type(value).__module__}.{type(value).__qualname__}:{value!r}"


def _canonical_closures(closed_edge_ids: object) -> tuple[str, ...]:
    if not isinstance(closed_edge_ids, tuple | list | set | frozenset):
        raise RoadGraphInvalid("closed_edge_ids must be a collection of edge IDs")
    closures: set[str] = set()
    for edge_id in closed_edge_ids:
        if not isinstance(edge_id, str) or not edge_id.strip():
            raise RoadGraphInvalid("closed edge IDs must be nonblank strings")
        closures.add(edge_id.strip())
    return tuple(sorted(closures))


def _read_graph_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as error:
        raise RoadGraphInvalid(f"cannot read road graph: {error}") from error


_LOAD_CACHE: dict[Path, RoadGraph] = {}
_LOAD_CACHE_LOCK = Lock()
_BUILD_JOURNAL_FILENAME = ".road-graph-build.json"
_JOURNAL_FIELDS = {
    "base_manifest_digest",
    "graph_digest",
    "graph_inode",
    "manifest",
    "output",
    "version",
}


def build_road_graph(
    *,
    bbox: tuple[float, float, float, float],
    output: Path,
    network_type: str = "drive",
    retriever: RoadGraphRetriever | None = None,
    clock: UtcClock | None = None,
) -> Path:
    """Build one immutable replay graph and atomically attach its metadata.

    The output directory must already be a replay package with a valid legacy
    or extended manifest. Preflight completes before the retriever is called.
    """
    output = Path(output)
    validated_bbox = _validated_build_bbox(bbox)
    normalized_network_type = _nonblank_build_value(
        network_type,
        "network_type",
    )
    retrieve = retriever or _retrieve_osm_graph
    now = clock or _utc_now

    try:
        if not output.name.endswith(".graphml.gz"):
            raise RoadGraphBuildError("output must end in .graphml.gz")
        with replay_package_writer(output.parent) as package:
            package_stat = os.fstat(package)
            _assert_package_identity(output.parent, package_stat)
            if _recover_publication(
                package=package,
                package_path=output.parent,
                package_stat=package_stat,
                output_name=output.name,
                bbox=validated_bbox,
            ):
                _assert_package_identity(output.parent, package_stat)
                return output
            manifest, base_manifest_content, base_manifest_digest = _preflight_build(
                package=package,
                output_name=output.name,
                bbox=validated_bbox,
            )
            retrieved = retrieve(validated_bbox, normalized_network_type)
            if not isinstance(retrieved, RetrievedRoadGraph):
                raise RoadGraphBuildError(
                    "road graph retriever returned an invalid result"
                )
            osmnx_version = _nonblank_build_value(
                retrieved.osmnx_version,
                "osmnx_version",
            )
            prepared = _prepare_retrieved_graph(retrieved.graph)
            graph_content = _graphml_gzip(prepared)
            graph_digest = sha256(graph_content).hexdigest()
            retrieved_at = now()
            if not isinstance(
                retrieved_at, datetime
            ) or retrieved_at.utcoffset() != timedelta(0):
                raise RoadGraphBuildError("retrieval timestamp must be UTC")
            metadata = RoadGraphMetadata(
                filename=output.name,
                retrieved_at=retrieved_at,
                bbox=validated_bbox,
                network_type=normalized_network_type,
                osmnx_version=osmnx_version,
                graph_digest=graph_digest,
                edge_count=prepared.number_of_edges(),
            )
            updated_manifest = manifest.with_road_graph(metadata)
            _assert_package_identity(output.parent, package_stat)
            _publish_graph_and_manifest(
                package=package,
                package_path=output.parent,
                package_stat=package_stat,
                output_name=output.name,
                graph_content=graph_content,
                manifest=updated_manifest,
                base_manifest_content=base_manifest_content,
                base_manifest_digest=base_manifest_digest,
            )
    except RoadGraphBuildError:
        raise
    except (OSError, ReplayManifestInvalid, RoadGraphInvalid) as error:
        raise RoadGraphBuildError(str(error)) from error
    except Exception as error:
        raise RoadGraphBuildError(f"road graph retrieval failed: {error}") from error
    return output


def _preflight_build(
    *,
    package: int,
    output_name: str,
    bbox: tuple[float, float, float, float],
) -> tuple[ReplayManifest, bytes, str]:
    if _entry_exists(package, output_name):
        raise RoadGraphBuildError("output road graph already exists")
    manifest, content = _manifest_snapshot(package)
    if manifest.region != bbox:
        raise RoadGraphBuildError(
            "road graph bbox must exactly match replay manifest region"
        )
    if manifest.road_graph is not None:
        raise RoadGraphBuildError("replay manifest already pins a road graph")
    return manifest, content, sha256(content).hexdigest()


def _assert_package_identity(path: Path, expected: os.stat_result) -> None:
    try:
        current = os.stat(path, follow_symlinks=False)
    except OSError as error:
        raise RoadGraphBuildError(
            "output directory changed during publication"
        ) from error
    if (
        not stat.S_ISDIR(current.st_mode)
        or current.st_dev != expected.st_dev
        or current.st_ino != expected.st_ino
    ):
        raise RoadGraphBuildError("output directory changed during publication")


def _entry_exists(directory: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return True


def _recover_publication(
    *,
    package: int,
    package_path: Path,
    package_stat: os.stat_result,
    output_name: str,
    bbox: tuple[float, float, float, float],
) -> bool:
    try:
        journal_descriptor = _open_regular_file(package, _BUILD_JOURNAL_FILENAME)
    except FileNotFoundError:
        return False
    try:
        journal_content = _read_descriptor(journal_descriptor)
        journal = _parse_publication_journal(journal_content)
        if journal.output_name != output_name:
            raise RoadGraphBuildError("road graph build journal targets another output")
        journal_manifest = _load_canonical_manifest(journal.manifest_content)
        metadata = journal_manifest.road_graph
        if (
            metadata is None
            or metadata.filename != output_name
            or metadata.graph_digest != journal.graph_digest
            or metadata.bbox != bbox
        ):
            raise RoadGraphBuildError(
                "road graph build journal metadata is inconsistent"
            )
        current_manifest, current_manifest_content = _manifest_snapshot(package)
        if current_manifest.region != bbox:
            raise RoadGraphBuildError(
                "road graph bbox must exactly match replay manifest region"
            )
        base_matches = (
            sha256(current_manifest_content).hexdigest() == journal.base_manifest_digest
            and current_manifest.road_graph is None
            and current_manifest.with_road_graph(metadata) == journal_manifest
        )

        try:
            graph_descriptor = _open_regular_file(package, output_name)
        except FileNotFoundError:
            if not base_matches:
                raise RoadGraphBuildError(
                    "road graph build journal has no owned output to recover"
                ) from None
            _retire_journal(package, journal_descriptor)
            return False
        try:
            graph_content = _read_descriptor(graph_descriptor)
            graph_stat = os.fstat(graph_descriptor)
            if (
                graph_stat.st_ino != journal.graph_inode
                or sha256(graph_content).hexdigest() != journal.graph_digest
            ):
                raise RoadGraphBuildError(
                    "road graph build journal does not own the existing output"
                )

            if base_matches:
                stage = _create_stage_directory(package)
                try:
                    os.close(
                        _write_bytes_at(
                            stage,
                            "manifest.next",
                            journal.manifest_content,
                        )
                    )
                    os.close(
                        _write_bytes_at(
                            stage,
                            "manifest.base",
                            current_manifest_content,
                        )
                    )
                    _fsync_directory(stage)
                    try:
                        _commit_manifest(
                            package=package,
                            package_path=package_path,
                            package_stat=package_stat,
                            output_name=output_name,
                            graph_descriptor=graph_descriptor,
                            graph_digest=journal.graph_digest,
                            stage=stage,
                            manifest_content=journal.manifest_content,
                            base_manifest_content=current_manifest_content,
                        )
                    except RoadGraphBuildError:
                        _retire_journal(package, journal_descriptor)
                        raise
                finally:
                    os.close(stage)
            elif current_manifest_content != journal.manifest_content:
                raise RoadGraphBuildError(
                    "road graph build journal manifest does not match base manifest"
                )
            _retire_journal(package, journal_descriptor)
            return True
        finally:
            os.close(graph_descriptor)
    finally:
        os.close(journal_descriptor)


def _manifest_snapshot(package: int) -> tuple[ReplayManifest, bytes]:
    content = _read_regular_file(package, "manifest.json")
    return _load_manifest(content), content


def _load_manifest(content: bytes) -> ReplayManifest:
    with tempfile.TemporaryDirectory(prefix="road-graph-manifest-check-") as directory:
        source = Path(directory) / "manifest.json"
        _write_path_bytes(source, content)
        return ReplayManifest.load(source)


def _load_canonical_manifest(content: bytes) -> ReplayManifest:
    try:
        manifest = _load_manifest(content)
    except ReplayManifestInvalid as error:
        raise RoadGraphBuildError(
            f"road graph build journal manifest is invalid: {error}"
        ) from error
    if _canonical_json(manifest.to_payload()) != content:
        raise RoadGraphBuildError("road graph build journal manifest is not canonical")
    return manifest


def _parse_publication_journal(content: bytes) -> _PublicationJournal:
    try:
        raw: object = json.loads(content)
    except (UnicodeDecodeError, ValueError) as error:
        raise RoadGraphBuildError("road graph build journal is invalid JSON") from error
    if not isinstance(raw, dict) or set(raw) != _JOURNAL_FIELDS:
        raise RoadGraphBuildError("road graph build journal has invalid fields")
    try:
        canonical = _canonical_json(raw)
    except (TypeError, ValueError) as error:
        raise RoadGraphBuildError("road graph build journal is invalid") from error
    if canonical != content:
        raise RoadGraphBuildError("road graph build journal is not canonical")
    if (
        not isinstance(raw["version"], int)
        or isinstance(raw["version"], bool)
        or raw["version"] != 1
    ):
        raise RoadGraphBuildError("road graph build journal has invalid version")
    output_name = raw["output"]
    manifest = raw["manifest"]
    if not isinstance(output_name, str) or not isinstance(manifest, str):
        raise RoadGraphBuildError("road graph build journal has invalid text fields")
    graph_digest = _journal_digest(raw["graph_digest"], "graph_digest")
    base_manifest_digest = _journal_digest(
        raw["base_manifest_digest"],
        "base_manifest_digest",
    )
    graph_inode = raw["graph_inode"]
    if (
        not isinstance(graph_inode, int)
        or isinstance(graph_inode, bool)
        or graph_inode < 0
    ):
        raise RoadGraphBuildError("road graph build journal has invalid graph_inode")
    return _PublicationJournal(
        output_name=output_name,
        graph_digest=graph_digest,
        graph_inode=graph_inode,
        base_manifest_digest=base_manifest_digest,
        manifest_content=manifest.encode("utf-8"),
    )


def _journal_digest(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise RoadGraphBuildError(f"road graph build journal has invalid {field}")
    return value


def _prepare_retrieved_graph(graph: nx.MultiDiGraph) -> nx.MultiDiGraph:
    if not isinstance(graph, nx.MultiDiGraph) or not graph.is_directed():
        raise RoadGraphBuildError("OSM road graph must be a directed MultiDiGraph")
    if graph.number_of_edges() == 0:
        raise RoadGraphBuildError("OSM road graph must contain at least one edge")
    prepared: nx.MultiDiGraph = nx.MultiDiGraph()
    prepared.graph.update(
        {key: graph.graph[key] for key in sorted(graph.graph) if isinstance(key, str)}
    )
    for node, data in sorted(
        graph.nodes(data=True),
        key=lambda item: _node_identity(item[0]),
    ):
        prepared.add_node(
            node,
            **{key: data[key] for key in sorted(data) if isinstance(key, str)},
        )
    edges = sorted(
        graph.edges(keys=True, data=True),
        key=lambda edge: (
            _node_identity(edge[0]),
            _node_identity(edge[1]),
            _node_identity(edge[2]),
        ),
    )
    edge_ids: set[str] = set()
    for origin, destination, key, raw_data in edges:
        distance_meters = _build_number(
            raw_data.get("length"),
            "OSM edge length",
        )
        travel_seconds = _build_number(
            raw_data.get("travel_time"),
            "OSM edge travel_time",
        )
        edge_id = _stable_osm_edge_id(origin, destination, key)
        if edge_id in edge_ids:
            raise RoadGraphBuildError(f"duplicate generated edge ID: {edge_id}")
        edge_ids.add(edge_id)
        data = {
            attribute: raw_data[attribute]
            for attribute in sorted(raw_data)
            if isinstance(attribute, str)
        }
        data.update(
            edge_id=edge_id,
            travel_minutes=travel_seconds / 60.0,
            distance_meters=distance_meters,
        )
        prepared.add_edge(origin, destination, key=key, **data)
    _validated_multidigraph(prepared)
    return prepared


def _stable_osm_edge_id(
    origin: object,
    destination: object,
    key: object,
) -> str:
    payload = json.dumps(
        [
            _node_identity(origin),
            _node_identity(destination),
            _node_identity(key),
        ],
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"osm-{sha256(payload).hexdigest()}"


def _graphml_gzip(graph: nx.MultiDiGraph) -> bytes:
    import osmnx as ox

    with tempfile.TemporaryDirectory(prefix="wildfireops-graphml-") as directory:
        graphml_path = Path(directory) / "roads.graphml"
        ox.io.save_graphml(graph, graphml_path)
        graphml = graphml_path.read_bytes()
    return gzip.compress(graphml, compresslevel=9, mtime=0)


def _publish_graph_and_manifest(
    *,
    package: int,
    package_path: Path,
    package_stat: os.stat_result,
    output_name: str,
    graph_content: bytes,
    manifest: ReplayManifest,
    base_manifest_content: bytes,
    base_manifest_digest: str,
) -> None:
    metadata = manifest.road_graph
    if metadata is None:
        raise RoadGraphBuildError("staged manifest has no road graph metadata")
    _validate_graph_content(graph_content, metadata.graph_version)
    manifest_content = _canonical_json(manifest.to_payload())
    stage = _create_stage_directory(package)
    graph_descriptor = -1
    journal_descriptor = -1
    try:
        graph_descriptor = _write_bytes_at(stage, "graph.stage", graph_content)
        graph_stat = os.fstat(graph_descriptor)
        os.close(_write_bytes_at(stage, "manifest.next", manifest_content))
        os.close(_write_bytes_at(stage, "manifest.base", base_manifest_content))
        journal_descriptor = _write_bytes_at(
            stage,
            "journal.stage",
            _canonical_json(
                {
                    "base_manifest_digest": base_manifest_digest,
                    "graph_digest": metadata.graph_digest,
                    "graph_inode": graph_stat.st_ino,
                    "manifest": manifest_content.decode("utf-8"),
                    "output": output_name,
                    "version": 1,
                }
            ),
        )
        _fsync_directory(stage)
        _assert_package_identity(package_path, package_stat)
        _, current_manifest_content = _manifest_snapshot(package)
        if current_manifest_content != base_manifest_content:
            raise RoadGraphBuildError(
                "replay manifest changed before road graph publication"
            )
        os.link(
            "journal.stage",
            _BUILD_JOURNAL_FILENAME,
            src_dir_fd=stage,
            dst_dir_fd=package,
            follow_symlinks=False,
        )
        _fsync_directory(package)
        try:
            os.link(
                "graph.stage",
                output_name,
                src_dir_fd=stage,
                dst_dir_fd=package,
                follow_symlinks=False,
            )
        except OSError:
            _retire_journal(package, journal_descriptor, stage)
            raise
        _fsync_directory(package)
        try:
            _commit_manifest(
                package=package,
                package_path=package_path,
                package_stat=package_stat,
                output_name=output_name,
                graph_descriptor=graph_descriptor,
                graph_digest=metadata.graph_digest,
                stage=stage,
                manifest_content=manifest_content,
                base_manifest_content=base_manifest_content,
            )
        except RoadGraphBuildError:
            _retire_journal(package, journal_descriptor, stage)
            raise
        _retire_journal(package, journal_descriptor, stage)
    finally:
        if journal_descriptor >= 0:
            os.close(journal_descriptor)
        if graph_descriptor >= 0:
            os.close(graph_descriptor)
        os.close(stage)


def _commit_manifest(
    *,
    package: int,
    package_path: Path,
    package_stat: os.stat_result,
    output_name: str,
    graph_descriptor: int,
    graph_digest: str,
    stage: int,
    manifest_content: bytes,
    base_manifest_content: bytes,
) -> None:
    _assert_package_identity(package_path, package_stat)
    _, current_manifest_content = _manifest_snapshot(package)
    if current_manifest_content != base_manifest_content:
        raise RoadGraphBuildError(
            "replay manifest changed before road graph publication"
        )
    if not _path_matches_open_file(
        package,
        output_name,
        graph_descriptor,
        graph_digest,
    ):
        raise RoadGraphBuildError("claimed road graph changed before manifest commit")

    _replace_file(
        "manifest.next",
        "manifest.json",
        source_directory=stage,
        destination_directory=package,
    )
    _fsync_directory(package)

    _, published_content = _manifest_snapshot(package)
    graph_matches = _path_matches_open_file(
        package,
        output_name,
        graph_descriptor,
        graph_digest,
    )
    try:
        _assert_package_identity(package_path, package_stat)
    except RoadGraphBuildError:
        package_matches = False
    else:
        package_matches = True
    if published_content == manifest_content and graph_matches and package_matches:
        return

    if published_content == manifest_content:
        _replace_file(
            "manifest.base",
            "manifest.json",
            source_directory=stage,
            destination_directory=package,
        )
        _fsync_directory(package)
        _, restored_content = _manifest_snapshot(package)
        if restored_content != base_manifest_content:
            raise RoadGraphBuildError("base manifest changed during rollback")
    if not graph_matches:
        raise RoadGraphBuildError("claimed road graph changed during manifest commit")
    if not package_matches:
        raise RoadGraphBuildError("output directory changed during publication")
    raise RoadGraphBuildError("replay manifest changed during publication")


def _validate_graph_content(content: bytes, expected_digest: str) -> None:
    with tempfile.TemporaryDirectory(prefix="road-graph-stage-check-") as directory:
        path = Path(directory) / "roads.graphml.gz"
        _write_path_bytes(path, content)
        if RoadGraph.load(path).graph_version != expected_digest:
            raise RoadGraphBuildError("staged road graph digest changed")


def _create_stage_directory(package: int) -> int:
    name = f".road-graph-publication-{uuid4().hex}"
    os.mkdir(name, 0o700, dir_fd=package)
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(name, flags, dir_fd=package)
    try:
        _fsync_directory(package)
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _write_bytes_at(directory: int, name: str, content: bytes) -> int:
    flags = (
        os.O_RDWR
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(name, flags, 0o600, dir_fd=directory)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _write_path_bytes(path: Path, content: bytes) -> None:
    with path.open("xb") as file:
        file.write(content)
        file.flush()
        os.fsync(file.fileno())


def _open_regular_file(directory: int, name: str) -> int:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(name, flags, dir_fd=directory)
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise RoadGraphBuildError(f"{name} must be a regular file")
    return descriptor


def _read_descriptor(descriptor: int) -> bytes:
    os.lseek(descriptor, 0, os.SEEK_SET)
    with os.fdopen(descriptor, "rb", closefd=False) as file:
        return file.read()


def _read_regular_file(directory: int, name: str) -> bytes:
    descriptor = _open_regular_file(directory, name)
    try:
        return _read_descriptor(descriptor)
    finally:
        os.close(descriptor)


def _path_matches_open_file(
    directory: int,
    name: str,
    expected_descriptor: int,
    expected_digest: str,
) -> bool:
    try:
        descriptor = _open_regular_file(directory, name)
    except (FileNotFoundError, OSError):
        return False
    try:
        expected = os.fstat(expected_descriptor)
        current = os.fstat(descriptor)
        return (
            current.st_dev == expected.st_dev
            and current.st_ino == expected.st_ino
            and sha256(_read_descriptor(descriptor)).hexdigest() == expected_digest
        )
    finally:
        os.close(descriptor)


def _retire_journal(
    package: int,
    journal_descriptor: int,
    stage: int | None = None,
) -> None:
    if stage is None:
        retirement_stage = _create_stage_directory(package)
        owned_stage = True
    else:
        retirement_stage = stage
        owned_stage = False
    target = f"retired-journal-{uuid4().hex}"
    try:
        os.rename(
            _BUILD_JOURNAL_FILENAME,
            target,
            src_dir_fd=package,
            dst_dir_fd=retirement_stage,
        )
        moved = os.stat(target, dir_fd=retirement_stage, follow_symlinks=False)
        expected = os.fstat(journal_descriptor)
        _fsync_directory(retirement_stage)
        _fsync_directory(package)
        if (
            not stat.S_ISREG(moved.st_mode)
            or moved.st_dev != expected.st_dev
            or moved.st_ino != expected.st_ino
        ):
            raise RoadGraphBuildError(
                "road graph build journal changed during retirement"
            )
    finally:
        if owned_stage:
            os.close(retirement_stage)


def _fsync_directory(directory: int) -> None:
    os.fsync(directory)


def _canonical_json(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _replace_file(
    source: str,
    destination: str,
    *,
    source_directory: int,
    destination_directory: int,
) -> None:
    os.replace(
        source,
        destination,
        src_dir_fd=source_directory,
        dst_dir_fd=destination_directory,
    )


def _retrieve_osm_graph(
    bbox: tuple[float, float, float, float],
    network_type: str,
) -> RetrievedRoadGraph:
    import osmnx as ox

    graph = ox.graph_from_bbox(bbox, network_type=network_type)
    graph = ox.add_edge_speeds(graph, fallback=40.0)
    graph = ox.add_edge_travel_times(graph)
    return RetrievedRoadGraph(graph=graph, osmnx_version=ox.__version__)


def _build_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise RoadGraphBuildError(f"{field} must be finite and nonnegative")
    try:
        parsed = float(value)
    except (OverflowError, ValueError):
        raise RoadGraphBuildError(f"{field} must be finite and nonnegative") from None
    if not isfinite(parsed) or parsed < 0:
        raise RoadGraphBuildError(f"{field} must be finite and nonnegative")
    return parsed


def _nonblank_build_value(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RoadGraphBuildError(f"{field} must be a nonblank string")
    return value.strip()


def _validated_build_bbox(
    bbox: object,
) -> tuple[float, float, float, float]:
    if (
        not isinstance(bbox, tuple)
        or len(bbox) != 4
        or any(isinstance(item, bool) for item in bbox)
    ):
        raise RoadGraphBuildError("bbox must contain four finite coordinates")
    try:
        west, south, east, north = (float(item) for item in bbox)
    except (OverflowError, TypeError, ValueError):
        raise RoadGraphBuildError("bbox must contain four finite coordinates") from None
    if not all(isfinite(item) for item in (west, south, east, north)):
        raise RoadGraphBuildError("bbox must contain four finite coordinates")
    if not -180 <= west < east <= 180 or not -90 <= south < north <= 90:
        raise RoadGraphBuildError("bbox must be an ordered WGS84 bounding box")
    return west, south, east, north


def _bbox_argument(value: str) -> tuple[float, float, float, float]:
    parts = value.split(",")
    try:
        bbox = tuple(float(part) for part in parts)
    except (OverflowError, ValueError):
        raise argparse.ArgumentTypeError(
            "bbox must contain west,south,east,north"
        ) from None
    if len(bbox) != 4:
        raise argparse.ArgumentTypeError("bbox must contain west,south,east,north")
    try:
        return _validated_build_bbox((bbox[0], bbox[1], bbox[2], bbox[3]))
    except RoadGraphBuildError as error:
        raise argparse.ArgumentTypeError(str(error)) from None


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build and version a replay road graph from OpenStreetMap."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument(
        "--bbox",
        required=True,
        type=_bbox_argument,
        metavar="WEST,SOUTH,EAST,NORTH",
    )
    build.add_argument(
        "--network-type",
        default="drive",
        choices=("all", "all_public", "bike", "drive", "drive_service", "walk"),
    )
    build.add_argument("--output", required=True, type=Path)
    return parser


def _utc_now() -> datetime:
    return datetime.now(UTC)


def main(
    argv: Sequence[str] | None = None,
    *,
    retriever: RoadGraphRetriever | None = None,
    clock: UtcClock | None = None,
) -> int:
    parser = _argument_parser()
    arguments = parser.parse_args(argv)
    if arguments.command != "build":
        parser.error("a road graph command is required")
    try:
        build_road_graph(
            bbox=arguments.bbox,
            output=arguments.output,
            network_type=arguments.network_type,
            retriever=retriever,
            clock=clock,
        )
    except RoadGraphBuildError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
