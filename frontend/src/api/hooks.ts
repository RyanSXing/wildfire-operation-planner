import { useEffect } from "react";
import { useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";
import { z } from "zod";

import { apiClient } from "./client";

const incidentRoot = ["incidents"] as const;
const sourceRoot = ["sources"] as const;

export const queryKeys = {
  incidents: {
    root: incidentRoot,
    list: () => [...incidentRoot, "list"] as const,
    detail: (incidentId: string) =>
      [...incidentRoot, "detail", incidentId] as const,
    timeline: (incidentId: string) =>
      [...incidentRoot, "timeline", incidentId] as const,
  },
  sources: {
    root: sourceRoot,
    status: () => [...sourceRoot, "status"] as const,
  },
} as const;

const incidentUpdatedSchema = z.object({
  incidentId: z.string().min(1),
});

const sourceStatusUpdatedSchema = z.object({
  sourceName: z.string().min(1),
});

export function useIncidents() {
  return useQuery({
    queryKey: queryKeys.incidents.list(),
    queryFn: ({ signal }) => apiClient.listIncidents(signal),
  });
}

export function useIncident(incidentId: string) {
  return useQuery({
    queryKey: queryKeys.incidents.detail(incidentId),
    queryFn: ({ signal }) => apiClient.getIncident(incidentId, signal),
    enabled: incidentId.length > 0,
  });
}

export function useIncidentTimeline(incidentId: string) {
  return useQuery({
    queryKey: queryKeys.incidents.timeline(incidentId),
    queryFn: ({ signal }) => apiClient.getIncidentTimeline(incidentId, signal),
    enabled: incidentId.length > 0,
  });
}

export function useSourceStatus() {
  return useQuery({
    queryKey: queryKeys.sources.status(),
    queryFn: ({ signal }) => apiClient.listSourceStatuses(signal),
  });
}

export function useIncidentEvents(): void {
  const queryClient = useQueryClient();

  useEffect(() => {
    const eventSource = new EventSource("/api/events");

    const invalidate = (queryKey: QueryKey): void => {
      void queryClient.invalidateQueries({ queryKey, refetchType: "active" });
    };

    const reconcile = (): void => {
      invalidate(queryKeys.incidents.root);
      invalidate(queryKeys.sources.root);
    };

    const handleIncidentUpdated = (event: Event): void => {
      const payload = parseEvent(event, incidentUpdatedSchema);
      if (!payload) {
        return;
      }

      invalidate(queryKeys.incidents.list());
      invalidate(queryKeys.incidents.detail(payload.incidentId));
      invalidate(queryKeys.incidents.timeline(payload.incidentId));
    };

    const handleSourceStatusUpdated = (event: Event): void => {
      const payload = parseEvent(event, sourceStatusUpdatedSchema);
      if (!payload) {
        return;
      }

      invalidate(queryKeys.sources.status());
    };

    eventSource.addEventListener("open", reconcile);
    eventSource.addEventListener("resync-required", reconcile);
    eventSource.addEventListener("incident-updated", handleIncidentUpdated);
    eventSource.addEventListener(
      "source-status-updated",
      handleSourceStatusUpdated,
    );

    return () => {
      eventSource.removeEventListener("open", reconcile);
      eventSource.removeEventListener("resync-required", reconcile);
      eventSource.removeEventListener("incident-updated", handleIncidentUpdated);
      eventSource.removeEventListener(
        "source-status-updated",
        handleSourceStatusUpdated,
      );
      eventSource.close();
    };
  }, [queryClient]);
}

function parseEvent<T>(event: Event, schema: z.ZodType<T>): T | undefined {
  if (!("data" in event) || typeof event.data !== "string") {
    return undefined;
  }

  try {
    const parsed = schema.safeParse(JSON.parse(event.data));
    return parsed.success ? parsed.data : undefined;
  } catch {
    return undefined;
  }
}
