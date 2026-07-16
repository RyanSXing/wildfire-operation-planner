"""Immutable versioned road graphs and closure-aware deterministic routing.

Loaded paths are immutable version locations and are parsed once per process.
Distance uses ``distance_meters``, then OSMnx ``length``; literal toy edges
without either field deliberately contribute zero meters.
"""

from __future__ import annotations

import argparse
import fcntl
import gzip
import heapq
import json
import os
import shutil
import stat
import tempfile
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from io import BytesIO
from itertools import count
from math import isfinite
from pathlib import Path
from threading import Lock
from typing import Hashable
from xml.etree.ElementTree import ParseError

import networkx as nx

from wildfireops.replay.manifest import (
    ReplayManifest,
    ReplayManifestInvalid,
    RoadGraphMetadata,
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
_BUILD_LOCK_FILENAME = ".road-graph-build.lock"
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
        manifest_path = _preflight_package(
            output=output,
            bbox=validated_bbox,
        )
        with _package_build_lock(output.parent):
            if _recover_publication(
                output=output,
                manifest_path=manifest_path,
                bbox=validated_bbox,
            ):
                return output
            manifest_path, manifest, base_manifest_digest = _preflight_build(
                output=output,
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
            _publish_graph_and_manifest(
                output=output,
                manifest_path=manifest_path,
                graph_content=graph_content,
                manifest=updated_manifest,
                base_manifest_digest=base_manifest_digest,
            )
    except RoadGraphBuildError:
        raise
    except (OSError, ReplayManifestInvalid, RoadGraphInvalid) as error:
        raise RoadGraphBuildError(str(error)) from error
    except Exception as error:
        raise RoadGraphBuildError(f"road graph retrieval failed: {error}") from error
    return output


def _preflight_package(
    *,
    output: Path,
    bbox: tuple[float, float, float, float],
) -> Path:
    if not output.name.endswith(".graphml.gz"):
        raise RoadGraphBuildError("output must end in .graphml.gz")
    parent = output.parent
    if parent.is_symlink() or not parent.is_dir():
        raise RoadGraphBuildError(
            "output directory must be an existing nonsymlink replay package"
        )
    manifest_path = parent / "manifest.json"
    try:
        manifest = ReplayManifest.load(manifest_path)
    except ReplayManifestInvalid as error:
        raise RoadGraphBuildError(str(error)) from error
    if manifest.region != bbox:
        raise RoadGraphBuildError(
            "road graph bbox must exactly match replay manifest region"
        )
    return manifest_path


def _preflight_build(
    *,
    output: Path,
    bbox: tuple[float, float, float, float],
) -> tuple[Path, ReplayManifest, str]:
    if output.is_symlink() or output.exists():
        raise RoadGraphBuildError("output road graph already exists")
    manifest_path = _preflight_package(output=output, bbox=bbox)
    manifest, content = _manifest_snapshot(manifest_path)
    if manifest.region != bbox:
        raise RoadGraphBuildError(
            "road graph bbox must exactly match replay manifest region"
        )
    if manifest.road_graph is not None:
        raise RoadGraphBuildError("replay manifest already pins a road graph")
    return manifest_path, manifest, sha256(content).hexdigest()


@contextmanager
def _package_build_lock(package: Path) -> Iterator[None]:
    lock_path = package / _BUILD_LOCK_FILENAME
    flags = (
        os.O_RDWR
        | os.O_CREAT
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(lock_path, flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise RoadGraphBuildError("road graph build lock must be a regular file")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def _recover_publication(
    *,
    output: Path,
    manifest_path: Path,
    bbox: tuple[float, float, float, float],
) -> bool:
    journal_path = output.parent / _BUILD_JOURNAL_FILENAME
    try:
        journal_content, journal_stat = _read_regular_file(journal_path)
    except FileNotFoundError:
        return False
    journal = _parse_publication_journal(journal_content)
    if journal.output_name != output.name:
        raise RoadGraphBuildError("road graph build journal targets another output")
    journal_manifest = _load_canonical_manifest(
        journal.manifest_content,
        output.parent,
    )
    metadata = journal_manifest.road_graph
    if (
        metadata is None
        or metadata.filename != output.name
        or metadata.graph_digest != journal.graph_digest
        or metadata.bbox != bbox
    ):
        raise RoadGraphBuildError("road graph build journal metadata is inconsistent")
    current_manifest, current_manifest_content = _manifest_snapshot(manifest_path)
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
        graph_content, graph_stat = _read_regular_file(output)
    except FileNotFoundError:
        if not base_matches:
            raise RoadGraphBuildError(
                "road graph build journal has no owned output to recover"
            ) from None
        _remove_journal(journal_path, journal_stat, output.parent)
        return False
    if (
        graph_stat.st_ino != journal.graph_inode
        or sha256(graph_content).hexdigest() != journal.graph_digest
    ):
        raise RoadGraphBuildError(
            "road graph build journal does not own the existing output"
        )

    if base_matches:
        with tempfile.TemporaryDirectory(
            prefix=".road-graph-recovery-",
            dir=output.parent,
        ) as directory:
            manifest_stage = Path(directory) / "manifest.json"
            _write_bytes(manifest_stage, journal.manifest_content)
            _replace_file(manifest_stage, manifest_path)
        _, published_content = _manifest_snapshot(manifest_path)
        if published_content != journal.manifest_content:
            raise RoadGraphBuildError("recovered replay manifest changed")
        _fsync_directory(output.parent)
    elif current_manifest_content != journal.manifest_content:
        raise RoadGraphBuildError(
            "road graph build journal manifest does not match base manifest"
        )
    _remove_journal(journal_path, journal_stat, output.parent)
    return True


def _manifest_snapshot(path: Path) -> tuple[ReplayManifest, bytes]:
    before, _ = _read_regular_file(path)
    manifest = ReplayManifest.load(path)
    after, _ = _read_regular_file(path)
    if after != before:
        raise RoadGraphBuildError("replay manifest changed during preflight")
    return manifest, before


def _load_canonical_manifest(content: bytes, package: Path) -> ReplayManifest:
    with tempfile.TemporaryDirectory(
        prefix=".road-graph-journal-check-",
        dir=package,
    ) as directory:
        temporary = Path(directory)
        source = temporary / "manifest.json"
        canonical = temporary / "canonical.json"
        _write_bytes(source, content)
        try:
            manifest = ReplayManifest.load(source)
            manifest.write_atomic(canonical)
        except ReplayManifestInvalid as error:
            raise RoadGraphBuildError(
                f"road graph build journal manifest is invalid: {error}"
            ) from error
        if canonical.read_bytes() != content:
            raise RoadGraphBuildError(
                "road graph build journal manifest is not canonical"
            )
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


def _remove_journal(
    path: Path,
    expected: os.stat_result,
    package: Path,
) -> None:
    if not _remove_owned_path(path, expected.st_dev, expected.st_ino):
        raise RoadGraphBuildError("road graph build journal changed during recovery")
    _fsync_directory(package)


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
    output: Path,
    manifest_path: Path,
    graph_content: bytes,
    manifest: ReplayManifest,
    base_manifest_digest: str,
) -> None:
    temporary = Path(
        tempfile.mkdtemp(
            prefix=f".{output.name}.tmp-",
            dir=output.parent,
        )
    )
    graph_stage = temporary / output.name
    manifest_stage = temporary / "manifest.json"
    journal_stage = temporary / _BUILD_JOURNAL_FILENAME
    journal_path = output.parent / _BUILD_JOURNAL_FILENAME
    try:
        _write_bytes(graph_stage, graph_content)
        loaded = RoadGraph.load(graph_stage)
        metadata = manifest.road_graph
        if metadata is None:
            raise RoadGraphBuildError("staged manifest has no road graph metadata")
        if loaded.graph_version != metadata.graph_version:
            raise RoadGraphBuildError("staged road graph digest changed")
        manifest.write_atomic(manifest_stage)
        ReplayManifest.load(manifest_stage)
        manifest_content, _ = _read_regular_file(manifest_stage)
        graph_stat = graph_stage.stat()
        _write_bytes(
            journal_stage,
            _canonical_json(
                {
                    "base_manifest_digest": base_manifest_digest,
                    "graph_digest": metadata.graph_digest,
                    "graph_inode": graph_stat.st_ino,
                    "manifest": manifest_content.decode("utf-8"),
                    "output": output.name,
                    "version": 1,
                }
            ),
        )
        _, current_manifest_content = _manifest_snapshot(manifest_path)
        if sha256(current_manifest_content).hexdigest() != base_manifest_digest:
            raise RoadGraphBuildError(
                "replay manifest changed before road graph publication"
            )
        os.link(journal_stage, journal_path, follow_symlinks=False)
        journal_stat = journal_stage.stat()
        _fsync_directory(output.parent)
        try:
            os.link(graph_stage, output, follow_symlinks=False)
        except OSError:
            _remove_journal(journal_path, journal_stat, output.parent)
            raise
        _fsync_directory(output.parent)
        try:
            _replace_file(manifest_stage, manifest_path)
            _fsync_directory(output.parent)
        except OSError:
            _, current_manifest_content = _manifest_snapshot(manifest_path)
            if sha256(current_manifest_content).hexdigest() == base_manifest_digest:
                if not _remove_owned_graph(
                    output,
                    graph_stat,
                    metadata.graph_digest,
                ):
                    raise RoadGraphBuildError(
                        "claimed road graph changed before rollback"
                    ) from None
                _remove_journal(journal_path, journal_stat, output.parent)
            raise
        _remove_journal(journal_path, journal_stat, output.parent)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def _write_bytes(path: Path, content: bytes) -> None:
    with path.open("xb") as file:
        file.write(content)
        file.flush()
        os.fsync(file.fileno())


def _read_regular_file(path: Path) -> tuple[bytes, os.stat_result]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            raise RoadGraphBuildError(f"{path.name} must be a regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as file:
            return file.read(), file_stat
    finally:
        os.close(descriptor)


def _remove_owned_graph(
    path: Path,
    expected: os.stat_result,
    expected_digest: str,
) -> bool:
    try:
        content, current = _read_regular_file(path)
    except (FileNotFoundError, OSError):
        return False
    if (
        current.st_dev != expected.st_dev
        or current.st_ino != expected.st_ino
        or sha256(content).hexdigest() != expected_digest
    ):
        return False
    return _remove_owned_path(path, expected.st_dev, expected.st_ino)


def _remove_owned_path(path: Path, device: int, inode: int) -> bool:
    try:
        current = path.lstat()
    except FileNotFoundError:
        return False
    if (
        not stat.S_ISREG(current.st_mode)
        or current.st_dev != device
        or current.st_ino != inode
    ):
        return False
    path.unlink()
    return True


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


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


def _replace_file(source: Path, destination: Path) -> None:
    os.replace(source, destination)


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
