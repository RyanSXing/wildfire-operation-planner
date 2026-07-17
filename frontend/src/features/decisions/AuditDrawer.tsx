import { useEffect, useState } from "react";

import { useAuditEvent, useAuditEvents } from "../../api/hooks";
import type { AuditEvent, JsonObject, JsonValue } from "../../api/types";

export type AuditDrawerProps = { recommendationId: string };

export function AuditDrawer({ recommendationId }: AuditDrawerProps) {
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<{ eventId: string; recommendationId: string } | null>(null);
  const events = useAuditEvents(recommendationId, open);
  useEffect(() => setSelected(null), [recommendationId]);
  const selectedEventId = selected?.recommendationId === recommendationId ? selected.eventId : "";
  const event = useAuditEvent(selectedEventId, open && selectedEventId.length > 0);

  return (
    <details onToggle={(change) => setOpen(change.currentTarget.open)}>
      <summary>Audit history</summary>
      {!open ? null : events.isPending ? (
        <p role="status">Loading audit history…</p>
      ) : events.isError ? (
        <Failure message="Audit history could not be loaded." retry="Retry audit history" onRetry={() => void events.refetch()} />
      ) : events.data?.items.length === 0 ? (
        <p>No audit events are recorded for this recommendation.</p>
      ) : events.data ? (
        <>
          <ul aria-label="Audit events">
            {events.data.items.map((item) => (
              <li key={item.id}>
                <AuditRow event={item} onView={() => setSelected({ eventId: item.id, recommendationId })} />
              </li>
            ))}
          </ul>
          {selectedEventId ? <AuditDetail eventId={selectedEventId} query={event} /> : null}
        </>
      ) : null}
    </details>
  );
}

function AuditRow({ event, onView }: { event: AuditEvent; onView: () => void }) {
  return (
    <article>
      <dl>
        <dt>Actor</dt><dd>{event.actorId}</dd>
        <dt>Event type</dt><dd>{event.eventType}</dd>
        <dt>Occurred</dt><dd><time dateTime={event.occurredAt}>{event.occurredAt}</time></dd>
        <dt>Scenario version</dt><dd>{event.scenarioVersionId}</dd>
        <dt>Recommendation</dt><dd>{event.recommendationId}</dd>
        <dt>Incident snapshot</dt><dd>{event.incidentSnapshotId}</dd>
        <dt>Source versions</dt><dd><JsonText value={objectField(event.inputs, "sourceVersions")} /></dd>
        <dt>Algorithms</dt><dd><JsonText value={event.algorithms} /></dd>
        <dt>Before state</dt><dd><JsonText value={event.beforeState} /></dd>
        <dt>After state</dt><dd><JsonText value={event.afterState} /></dd>
        <dt>Note</dt><dd>{event.note || "Not recorded"}</dd>
      </dl>
      <button type="button" onClick={onView}>View details for {event.id}</button>
    </article>
  );
}

function AuditDetail({ eventId, query }: { eventId: string; query: ReturnType<typeof useAuditEvent> }) {
  if (query.isPending) {
    return <p role="status">Loading audit details…</p>;
  }
  if (query.isError) {
    return <Failure message="Audit details could not be loaded." retry="Retry audit details" onRetry={() => void query.refetch()} />;
  }
  if (!query.data || query.data.id !== eventId) {
    return null;
  }

  const event = query.data;
  const inputs = event.inputs;
  const after = event.afterState;
  return (
    <section aria-label="Audit provenance">
      <h6>Observed inputs</h6>
      <Provenance value={[
        ["Incident snapshot", event.incidentSnapshotId],
        ["Source versions", objectField(inputs, "sourceVersions")],
      ]} />
      <h6>Simulated context</h6>
      <Provenance value={[
        ["Scenario version", event.scenarioVersionId],
        ["Context", "This identifies the immutable simulated scenario."],
      ]} />
      <h6>Calculated evidence</h6>
      <Provenance value={[
        ["Algorithms", nonemptyObject(event.algorithms)],
        ["Staleness token", stringField(inputs, "stalenessToken")],
        ["Proposed data", nonemptyObject(event.beforeState)],
      ]} />
      <h6>Operator-entered decision</h6>
      <Provenance value={[
        ["Actor", event.actorId],
        ["Action", stringField(after, "action")],
        ["Note", stringField(after, "note")],
        ["Decision ID", stringField(after, "decisionId")],
        ["Final assignments", arrayField(after, "finalPairs")],
      ]} />
      <details>
        <summary>Complete audit JSON</summary>
        <pre className="decision-workspace__evidence">{JSON.stringify({ inputs: event.inputs, beforeState: event.beforeState, afterState: event.afterState }, null, 2)}</pre>
      </details>
    </section>
  );
}

function Provenance({ value }: { value: readonly (readonly [string, JsonValue | string | undefined])[] }) {
  return (
    <dl>
      {value.map(([label, item]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{item === undefined ? "Not recorded" : typeof item === "string" ? item || "Not recorded" : <JsonText value={item} />}</dd>
        </div>
      ))}
    </dl>
  );
}

function JsonText({ value }: { value: JsonValue | undefined }) {
  return <span>{value === undefined ? "Not recorded" : JSON.stringify(value)}</span>;
}

function objectField(object: JsonObject, key: string): JsonObject | undefined {
  const value = object[key];
  return value && typeof value === "object" && !Array.isArray(value) && Object.keys(value).length > 0
    ? value
    : undefined;
}

function stringField(object: JsonObject, key: string): string | undefined {
  const value = object[key];
  return typeof value === "string" && value.trim() ? value : undefined;
}

function arrayField(object: JsonObject, key: string): JsonValue[] | undefined {
  const value = object[key];
  return Array.isArray(value) ? value : undefined;
}

function nonemptyObject(value: JsonObject): JsonObject | undefined {
  return Object.keys(value).length > 0 ? value : undefined;
}

function Failure({ message, retry, onRetry }: { message: string; retry: string; onRetry: () => void }) {
  return <section role="alert"><p>{message}</p><button type="button" onClick={onRetry}>{retry}</button></section>;
}
