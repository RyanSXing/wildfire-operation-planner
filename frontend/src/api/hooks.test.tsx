import {
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { StrictMode, type PropsWithChildren, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BEAR_ID, REDWOOD_ID } from "../test/fixtures";
import { ApiClientError, apiClient } from "./client";
import {
  queryKeys,
  useCreateScenarioMutation,
  useCreateScenarioVersionMutation,
  useCreateDecisionMutation,
  useDecisionContext,
  useGenerateRecommendationMutation,
  useIncident,
  useIncidentEvents,
  useIncidentTimeline,
  useIncidents,
  useRoadEdges,
  useSourceStatus,
} from "./hooks";

const scenarioVersion = {
  id: "version-1",
  scenarioId: "scenario-1",
  incidentId: REDWOOD_ID,
  incidentSnapshotId: "snapshot-1",
  version: 1,
  graphVersion: "roads-v1",
  roadClosures: [],
  weatherOverrides: [],
  resourceOverrides: [],
};

const recommendation = {
  id: "recommendation-1",
  scenarioVersionId: "version-1",
  incidentSnapshotId: "snapshot-1",
  assignments: [],
  uncoveredDestinationIds: [],
  objectiveComponents: {
    travelCost: 0,
    uncoveredRiskPenalty: 0,
    objectiveValue: 0,
  },
  solverStatus: "OPTIMAL",
  runtimeMilliseconds: 1,
  graphVersion: "roads-v1",
  riskVersion: "risk-v1",
  algorithmVersion: "allocation-v1",
  inputVersion: "input-v1",
  sourceVersions: {},
  explanation: {},
  outcome: {
    scenarioRisk: {
      score: 10,
      algorithmVersion: "risk-v1",
      contributions: [],
    },
    weightedRiskCovered: 10,
    weightedRiskUncovered: 0,
    totalTravelMinutes: 0,
    unreachableDestinationIds: [],
    unavailableResourceIds: [],
  },
};

const createScenarioVariables = {
  incidentId: REDWOOD_ID,
  body: {
    graphVersion: "roads-v1",
    objective: "minimize-response-time",
    name: "Morning plan",
    algorithmConfigVersion: "scenario-v1",
  },
};

type EventListenerValue = EventListenerOrEventListenerObject;

class FakeEventSource {
  static readonly instances: FakeEventSource[] = [];

  readonly url: string;
  readonly listeners = new Map<string, Set<EventListenerValue>>();
  closed = false;

  readonly addEventListener = vi.fn(
    (type: string, listener: EventListenerValue) => {
      const listeners = this.listeners.get(type) ?? new Set<EventListenerValue>();
      listeners.add(listener);
      this.listeners.set(type, listeners);
    },
  );

  readonly removeEventListener = vi.fn(
    (type: string, listener: EventListenerValue) => {
      this.listeners.get(type)?.delete(listener);
    },
  );

  readonly close = vi.fn(() => {
    this.closed = true;
  });

  constructor(url: string | URL) {
    this.url = String(url);
    FakeEventSource.instances.push(this);
  }

  emit(type: string, payload?: unknown): void {
    const event =
      type === "open" || type === "error"
        ? new Event(type)
        : new MessageEvent(type, {
            data: typeof payload === "string" ? payload : JSON.stringify(payload),
          });

    for (const listener of this.listeners.get(type) ?? []) {
      if (typeof listener === "function") {
        listener.call(this, event);
      } else {
        listener.handleEvent(event);
      }
    }
  }

  listenerCount(type: string): number {
    return this.listeners.get(type)?.size ?? 0;
  }

  static liveInstances(): FakeEventSource[] {
    return FakeEventSource.instances.filter((instance) => !instance.closed);
  }

  static reset(): void {
    FakeEventSource.instances.length = 0;
  }
}

const queryClients = new Set<QueryClient>();

function createHarness(options: { strict?: boolean } = {}): {
  queryClient: QueryClient;
  wrapper: ({ children }: PropsWithChildren) => ReactNode;
} {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
    },
  });
  queryClients.add(queryClient);

  function wrapper({ children }: PropsWithChildren): ReactNode {
    const provider = (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    return options.strict ? <StrictMode>{provider}</StrictMode> : provider;
  }

  return { queryClient, wrapper };
}

function activeEventSource(): FakeEventSource {
  const instances = FakeEventSource.liveInstances();
  expect(instances).toHaveLength(1);
  return instances[0];
}

beforeEach(() => {
  FakeEventSource.reset();
  vi.stubGlobal("EventSource", FakeEventSource);
});

afterEach(() => {
  for (const queryClient of queryClients) {
    queryClient.clear();
  }
  queryClients.clear();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("incident read hooks", () => {
  it("uses the frozen query keys and returns authoritative HTTP data", async () => {
    const { queryClient, wrapper } = createHarness();

    const { result } = renderHook(
      () => ({
        incidents: useIncidents(),
        incident: useIncident(REDWOOD_ID),
        timeline: useIncidentTimeline(REDWOOD_ID),
        sources: useSourceStatus(),
      }),
      { wrapper },
    );

    await waitFor(() => {
      expect(result.current.incidents.isSuccess).toBe(true);
      expect(result.current.incident.isSuccess).toBe(true);
      expect(result.current.timeline.isSuccess).toBe(true);
      expect(result.current.sources.isSuccess).toBe(true);
    });

    expect(queryKeys.incidents.list()).toEqual(["incidents", "list"]);
    expect(queryKeys.incidents.detail(REDWOOD_ID)).toEqual([
      "incidents",
      "detail",
      REDWOOD_ID,
    ]);
    expect(queryKeys.incidents.timeline(REDWOOD_ID)).toEqual([
      "incidents",
      "timeline",
      REDWOOD_ID,
    ]);
    expect(queryKeys.sources.status()).toEqual(["sources", "status"]);
    expect(queryClient.getQueryData(queryKeys.incidents.list())).toEqual(
      result.current.incidents.data,
    );
    expect(result.current.incident.data?.id).toBe(REDWOOD_ID);
    expect(result.current.timeline.data?.items[0].snapshotVersion).toBe(1);
    expect(result.current.sources.data?.items.length).toBeGreaterThan(0);
  });
});

describe("planning read hooks", () => {
  it("uses deterministic keys and stays disabled without required scope", async () => {
    const contextRequest = vi.spyOn(apiClient, "getDecisionContext").mockResolvedValue({
      incidentId: REDWOOD_ID,
      defaultGraphVersion: "roads-v1",
      availableGraphs: [{ graphVersion: "roads-v1", edgeCount: 2 }],
    });
    const edgeRequest = vi.spyOn(apiClient, "listRoadEdges").mockResolvedValue({
      items: [],
      total: 0,
      missingEdgeIds: [],
    });
    const { wrapper } = createHarness();
    const { result, rerender } = renderHook(
      ({ incidentId, graphVersion }) => ({
        context: useDecisionContext(incidentId),
        edges: useRoadEdges(
          graphVersion,
          { q: "forest", edgeIds: ["edge-1"], limit: 200 },
        ),
      }),
      {
        wrapper,
        initialProps: { incidentId: "", graphVersion: "" },
      },
    );

    expect(result.current.context.fetchStatus).toBe("idle");
    expect(result.current.edges.fetchStatus).toBe("idle");
    expect(contextRequest).not.toHaveBeenCalled();
    expect(edgeRequest).not.toHaveBeenCalled();

    rerender({ incidentId: REDWOOD_ID, graphVersion: "roads-v1" });
    await waitFor(() => {
      expect(result.current.context.isSuccess).toBe(true);
      expect(result.current.edges.isSuccess).toBe(true);
    });

    expect(queryKeys.incidents.decisionContext(REDWOOD_ID)).toEqual([
      "incidents",
      "decision-context",
      REDWOOD_ID,
    ]);
    expect(
      queryKeys.roadGraphs.edges("roads-v1", {
        q: "forest",
        edgeIds: ["edge-1"],
        limit: 200,
      }),
    ).toEqual([
      "road-graphs",
      "edges",
      "roads-v1",
      "forest",
      ["edge-1"],
      200,
    ]);
    expect(contextRequest).toHaveBeenCalledWith(REDWOOD_ID, expect.any(AbortSignal));
    expect(edgeRequest).toHaveBeenCalledWith(
      "roads-v1",
      { q: "forest", edgeIds: ["edge-1"], limit: 200 },
      expect.any(AbortSignal),
    );
  });
});

describe("planning command hooks", () => {
  it("canonicalizes decision requests before signing and transport", async () => {
    const createDecision = vi
      .spyOn(apiClient, "createDecision")
      .mockResolvedValue({
        id: "decision-1",
        recommendationId: "recommendation-1",
        action: "edit" as const,
        note: "Operator note",
        actorId: "operator-1",
        assignments: [],
        createdAt: "2026-07-17T12:00:00Z",
      });
    const { wrapper } = createHarness();
    const { result } = renderHook(() => useCreateDecisionMutation(), {
      wrapper,
    });

    await act(async () => {
      await result.current.mutateAsync({
        recommendationId: "recommendation-1",
        body: {
          action: "edit",
          note: "  Operator note  ",
          editedAssignments: [
            { resourceId: "resource-2", destinationId: "asset-2" },
            { resourceId: "resource-1", destinationId: "asset-1" },
          ],
        },
      });
    });

    expect(createDecision).toHaveBeenCalledWith(
      "recommendation-1",
      {
        action: "edit",
        note: "Operator note",
        editedAssignments: [
          { resourceId: "resource-1", destinationId: "asset-1" },
          { resourceId: "resource-2", destinationId: "asset-2" },
        ],
      },
      expect.stringMatching(/\S/),
    );
  });

  it("reuses an unchanged decision key but discards it after reset", async () => {
    const failure = new ApiClientError("network_error", "hidden", {}, 0);
    const createDecision = vi
      .spyOn(apiClient, "createDecision")
      .mockRejectedValueOnce(failure)
      .mockResolvedValue({
        id: "decision-1",
        recommendationId: "recommendation-1",
        action: "approve" as const,
        note: "Proceed",
        actorId: "operator-1",
        assignments: [],
        createdAt: "2026-07-17T12:00:00Z",
      });
    const { wrapper } = createHarness();
    const { result } = renderHook(() => useCreateDecisionMutation(), {
      wrapper,
    });
    const variables = {
      recommendationId: "recommendation-1",
      body: { action: "approve" as const, note: "Proceed" },
    };

    await act(async () => {
      await expect(result.current.mutateAsync(variables)).rejects.toBe(failure);
      await result.current.mutateAsync(variables);
    });
    expect(createDecision.mock.calls[0][2]).toBe(createDecision.mock.calls[1][2]);

    act(() => result.current.reset());
    await act(async () => {
      await result.current.mutateAsync(variables);
    });
    expect(createDecision.mock.calls[1][2]).not.toBe(createDecision.mock.calls[2][2]);
  });

  it.each([
    { action: "reject" as const, note: "Proceed" },
    { action: "approve" as const, note: "Changed note" },
    {
      action: "edit" as const,
      note: "Proceed",
      editedAssignments: [{ resourceId: "resource-2", destinationId: "asset-2" }],
    },
  ])("uses a fresh key when a retry changes the decision", async (body) => {
    const createDecision = vi
      .spyOn(apiClient, "createDecision")
      .mockRejectedValueOnce(new ApiClientError("network_error", "hidden", {}, 0))
      .mockResolvedValue({
        id: "decision-1",
        recommendationId: "recommendation-1",
        action: body.action,
        note: body.note,
        actorId: "operator-1",
        assignments: [],
        createdAt: "2026-07-17T12:00:00Z",
      });
    const { wrapper } = createHarness();
    const { result } = renderHook(() => useCreateDecisionMutation(), { wrapper });

    await act(async () => {
      await expect(
        result.current.mutateAsync({
          recommendationId: "recommendation-1",
          body: { action: "approve", note: "Proceed" },
        }),
      ).rejects.toBeInstanceOf(ApiClientError);
      await result.current.mutateAsync({ recommendationId: "recommendation-1", body });
    });

    expect(createDecision.mock.calls[0][2]).not.toBe(createDecision.mock.calls[1][2]);
  });

  it("routes all three typed commands with nonblank caller-owned keys", async () => {
    const createScenario = vi
      .spyOn(apiClient, "createScenario")
      .mockResolvedValue(scenarioVersion);
    const createVersion = vi
      .spyOn(apiClient, "createScenarioVersion")
      .mockResolvedValue({ ...scenarioVersion, id: "version-2", version: 2 });
    const generate = vi
      .spyOn(apiClient, "generateRecommendation")
      .mockResolvedValue(recommendation);
    const { wrapper } = createHarness();
    const { result } = renderHook(
      () => ({
        createScenario: useCreateScenarioMutation(),
        createVersion: useCreateScenarioVersionMutation(),
        generate: useGenerateRecommendationMutation(),
      }),
      { wrapper },
    );

    await act(async () => {
      await result.current.createScenario.mutateAsync(createScenarioVariables);
      await result.current.createVersion.mutateAsync({
        scenarioId: "scenario-1",
        body: {
          roadClosures: [{ edgeId: "edge-1" }],
          weatherOverrides: [],
          resourceOverrides: [],
        },
      });
      await result.current.generate.mutateAsync({
        versionId: "version-2",
        body: { maxResponseMinutes: 30, maxSolverSeconds: 2 },
      });
    });

    expect(createScenario).toHaveBeenCalledWith(
      REDWOOD_ID,
      createScenarioVariables.body,
      expect.stringMatching(/\S/),
    );
    expect(createVersion).toHaveBeenCalledWith(
      "scenario-1",
      {
        roadClosures: [{ edgeId: "edge-1" }],
        weatherOverrides: [],
        resourceOverrides: [],
      },
      expect.stringMatching(/\S/),
    );
    expect(generate).toHaveBeenCalledWith(
      "version-2",
      { maxResponseMinutes: 30, maxSolverSeconds: 2 },
      expect.stringMatching(/\S/),
    );
  });

  it.each([
    new ApiClientError("network_error", "hidden", {}, 0),
    new ApiClientError("request_timeout", "hidden", {}, 408),
    new ApiClientError("rate_limited", "hidden", {}, 429),
    new ApiClientError("service_unavailable", "hidden", {}, 503),
  ])("reuses one key for an unchanged retryable failure", async (failure) => {
    const command = vi
      .spyOn(apiClient, "createScenario")
      .mockRejectedValueOnce(failure)
      .mockResolvedValueOnce(scenarioVersion);
    const { wrapper } = createHarness();
    const { result } = renderHook(() => useCreateScenarioMutation(), {
      wrapper,
    });

    await act(async () => {
      await expect(
        result.current.mutateAsync(createScenarioVariables),
      ).rejects.toBe(failure);
      await result.current.mutateAsync(createScenarioVariables);
    });

    expect(command.mock.calls[0][2]).toBe(command.mock.calls[1][2]);
  });

  it("replaces retry intent when scope or body changes", async () => {
    const command = vi
      .spyOn(apiClient, "createScenario")
      .mockRejectedValueOnce(
        new ApiClientError("network_error", "hidden", {}, 0),
      )
      .mockResolvedValueOnce(scenarioVersion);
    const { wrapper } = createHarness();
    const { result } = renderHook(() => useCreateScenarioMutation(), {
      wrapper,
    });

    await act(async () => {
      await expect(
        result.current.mutateAsync(createScenarioVariables),
      ).rejects.toBeInstanceOf(ApiClientError);
      await result.current.mutateAsync({
        ...createScenarioVariables,
        body: { ...createScenarioVariables.body, name: "Changed plan" },
      });
    });

    expect(command.mock.calls[0][2]).not.toBe(command.mock.calls[1][2]);
  });

  it.each([
    { first: "success" as const },
    {
      first: new ApiClientError("invalid_request", "hidden", {}, 400),
    },
  ])("consumes keys after success or terminal failure", async ({ first }) => {
    const command = vi.spyOn(apiClient, "createScenario");
    if (first === "success") {
      command.mockResolvedValueOnce(scenarioVersion);
    } else {
      command.mockRejectedValueOnce(first);
    }
    command.mockResolvedValueOnce(scenarioVersion);
    const { wrapper } = createHarness();
    const { result } = renderHook(() => useCreateScenarioMutation(), {
      wrapper,
    });

    await act(async () => {
      if (first === "success") {
        await result.current.mutateAsync(createScenarioVariables);
      } else {
        await expect(
          result.current.mutateAsync(createScenarioVariables),
        ).rejects.toBe(first);
      }
      await result.current.mutateAsync(createScenarioVariables);
    });

    expect(command.mock.calls[0][2]).not.toBe(command.mock.calls[1][2]);
  });

  it("reset discards retry intent and mutation error state", async () => {
    const failure = new ApiClientError("network_error", "hidden", {}, 0);
    const command = vi
      .spyOn(apiClient, "createScenario")
      .mockRejectedValueOnce(failure)
      .mockResolvedValueOnce(scenarioVersion);
    const { wrapper } = createHarness();
    const { result } = renderHook(() => useCreateScenarioMutation(), {
      wrapper,
    });

    await act(async () => {
      await expect(
        result.current.mutateAsync(createScenarioVariables),
      ).rejects.toBe(failure);
    });
    await waitFor(() => expect(result.current.isError).toBe(true));

    act(() => result.current.reset());
    await waitFor(() => expect(result.current.isError).toBe(false));
    await act(async () => {
      await result.current.mutateAsync(createScenarioVariables);
    });

    expect(command.mock.calls[0][2]).not.toBe(command.mock.calls[1][2]);
  });
});

describe("useIncidentEvents", () => {
  it("returns scoped immutable revisions while preserving first-open reconciliation", () => {
    const { wrapper } = createHarness();
    const { result } = renderHook(() => useIncidentEvents(), { wrapper });

    expect(result.current).toEqual({
      globalRevision: 0,
      incidentRevisions: {},
    });

    const initial = result.current;
    act(() => {
      activeEventSource().emit("open");
    });
    expect(result.current).toBe(initial);

    act(() => {
      activeEventSource().emit("incident-updated", { incidentId: REDWOOD_ID });
    });
    expect(result.current).toEqual({
      globalRevision: 0,
      incidentRevisions: { [REDWOOD_ID]: 1 },
    });
    expect(result.current).not.toBe(initial);

    const afterRedwood = result.current;
    act(() => {
      activeEventSource().emit("incident-updated", { incidentId: BEAR_ID });
    });
    expect(result.current).toEqual({
      globalRevision: 0,
      incidentRevisions: { [REDWOOD_ID]: 1, [BEAR_ID]: 1 },
    });
    expect(result.current.incidentRevisions).not.toBe(
      afterRedwood.incidentRevisions,
    );

    act(() => {
      activeEventSource().emit("open");
    });
    expect(result.current).toEqual({
      globalRevision: 1,
      incidentRevisions: { [REDWOOD_ID]: 1, [BEAR_ID]: 1 },
    });

    act(() => {
      activeEventSource().emit("resync-required", {});
    });
    expect(result.current).toEqual({
      globalRevision: 2,
      incidentRevisions: { [REDWOOD_ID]: 1, [BEAR_ID]: 1 },
    });
  });

  it("does not revise freshness for source events or malformed update payloads", () => {
    const { wrapper } = createHarness();
    const { result } = renderHook(() => useIncidentEvents(), { wrapper });
    const initial = result.current;

    act(() => {
      const eventSource = activeEventSource();
      eventSource.emit("source-status-updated", { sourceName: "nasa_firms" });
      eventSource.emit("incident-updated", "not-json");
      eventSource.emit("incident-updated", { incidentId: 42 });
      eventSource.emit("resync-required", { unexpected: true });
    });

    expect(result.current).toBe(initial);
  });

  it("owns exactly one relative EventSource connection and cleans up every listener", () => {
    const { wrapper } = createHarness();
    const { rerender, unmount } = renderHook(() => useIncidentEvents(), {
      wrapper,
    });

    const eventSource = activeEventSource();
    expect(eventSource.url).toBe("/api/events");
    expect(FakeEventSource.instances).toHaveLength(1);
    expect(eventSource.listenerCount("incident-updated")).toBe(1);
    expect(eventSource.listenerCount("source-status-updated")).toBe(1);
    expect(eventSource.listenerCount("open")).toBe(1);
    expect(eventSource.listenerCount("resync-required")).toBe(1);

    rerender();
    expect(FakeEventSource.instances).toHaveLength(1);

    unmount();
    expect(eventSource.close).toHaveBeenCalledOnce();
    expect(eventSource.removeEventListener).toHaveBeenCalledTimes(4);
    expect(eventSource.listenerCount("incident-updated")).toBe(0);
    expect(eventSource.listenerCount("source-status-updated")).toBe(0);
    expect(eventSource.listenerCount("open")).toBe(0);
    expect(eventSource.listenerCount("resync-required")).toBe(0);
    expect(FakeEventSource.liveInstances()).toHaveLength(0);
  });

  it("invalidates the list plus only the matching detail and timeline", () => {
    const { queryClient, wrapper } = createHarness();
    const invalidate = vi
      .spyOn(queryClient, "invalidateQueries")
      .mockResolvedValue(undefined);
    renderHook(() => useIncidentEvents(), { wrapper });

    act(() => {
      activeEventSource().emit("incident-updated", { incidentId: REDWOOD_ID });
    });

    expect(invalidate).toHaveBeenCalledTimes(3);
    expect(invalidate).toHaveBeenNthCalledWith(1, {
      queryKey: queryKeys.incidents.list(),
      refetchType: "active",
    });
    expect(invalidate).toHaveBeenNthCalledWith(2, {
      queryKey: queryKeys.incidents.detail(REDWOOD_ID),
      refetchType: "active",
    });
    expect(invalidate).toHaveBeenNthCalledWith(3, {
      queryKey: queryKeys.incidents.timeline(REDWOOD_ID),
      refetchType: "active",
    });
    const invalidatedKeys = invalidate.mock.calls.map(
      ([filters]) => filters?.queryKey,
    );
    expect(invalidatedKeys).not.toContainEqual(queryKeys.incidents.detail(BEAR_ID));
    expect(invalidatedKeys).not.toContainEqual(
      queryKeys.incidents.timeline(BEAR_ID),
    );
  });

  it("invalidates aggregate source status after a valid source event", () => {
    const { queryClient, wrapper } = createHarness();
    const invalidate = vi
      .spyOn(queryClient, "invalidateQueries")
      .mockResolvedValue(undefined);
    renderHook(() => useIncidentEvents(), { wrapper });

    act(() => {
      activeEventSource().emit("source-status-updated", {
        sourceName: "nasa_firms",
      });
    });

    expect(invalidate).toHaveBeenCalledOnce();
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: queryKeys.sources.status(),
      refetchType: "active",
    });
  });

  it.each(["open", "resync-required"])(
    "reconciles every active incident and source root on %s",
    (eventType) => {
      const { queryClient, wrapper } = createHarness();
      const invalidate = vi
        .spyOn(queryClient, "invalidateQueries")
        .mockResolvedValue(undefined);
      renderHook(() => useIncidentEvents(), { wrapper });

      act(() => {
        activeEventSource().emit(
          eventType,
          eventType === "resync-required" ? {} : undefined,
        );
      });

      expect(invalidate).toHaveBeenCalledTimes(2);
      expect(invalidate).toHaveBeenNthCalledWith(1, {
        queryKey: queryKeys.incidents.root,
        refetchType: "active",
      });
      expect(invalidate).toHaveBeenNthCalledWith(2, {
        queryKey: queryKeys.sources.root,
        refetchType: "active",
      });
    },
  );

  it("ignores malformed payloads and never installs a reconnect timer", () => {
    const { queryClient, wrapper } = createHarness();
    const invalidate = vi
      .spyOn(queryClient, "invalidateQueries")
      .mockResolvedValue(undefined);
    const setTimeoutSpy = vi.spyOn(globalThis, "setTimeout");
    renderHook(() => useIncidentEvents(), { wrapper });
    setTimeoutSpy.mockClear();

    act(() => {
      const eventSource = activeEventSource();
      eventSource.emit("incident-updated", "not-json");
      eventSource.emit("incident-updated", { incidentId: 42 });
      eventSource.emit("source-status-updated", {});
      eventSource.emit("error");
    });

    expect(invalidate).not.toHaveBeenCalled();
    expect(setTimeoutSpy).not.toHaveBeenCalled();
    expect(FakeEventSource.instances).toHaveLength(1);
    expect(FakeEventSource.liveInstances()).toHaveLength(1);
  });

  it("leaves one live connection under StrictMode and none after unmount", () => {
    const { wrapper } = createHarness({ strict: true });
    const { unmount } = renderHook(() => useIncidentEvents(), { wrapper });

    const live = FakeEventSource.liveInstances();
    expect(live).toHaveLength(1);
    expect(live[0].url).toBe("/api/events");
    expect(
      FakeEventSource.instances.filter((instance) => instance.closed),
    ).toHaveLength(FakeEventSource.instances.length - 1);

    unmount();
    expect(FakeEventSource.liveInstances()).toHaveLength(0);
  });
});
