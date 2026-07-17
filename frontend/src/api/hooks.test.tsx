import {
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { StrictMode, type PropsWithChildren, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BEAR_ID, REDWOOD_ID } from "../test/fixtures";
import {
  queryKeys,
  useIncident,
  useIncidentEvents,
  useIncidentTimeline,
  useIncidents,
  useSourceStatus,
} from "./hooks";

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

describe("useIncidentEvents", () => {
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
        activeEventSource().emit(eventType);
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
