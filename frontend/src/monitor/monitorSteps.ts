/** Progress the rail shows, derived from planning state. */
export type MonitorStep = {
  key: string;
  ordinal: number;
  title: string;
  note: string;
  state: "done" | "current" | "pending";
};

export const STEP_STATE_TEXT: Record<MonitorStep["state"], string> = {
  done: "Completed:",
  current: "Current step:",
  pending: "Not started:",
};

export function buildMonitorSteps({
  hasIncident,
  planned,
  recommended,
  decided,
}: {
  hasIncident: boolean;
  planned: boolean;
  recommended: boolean;
  decided: boolean;
}): MonitorStep[] {
  const state = (done: boolean, current: boolean): MonitorStep["state"] =>
    done ? "done" : current ? "current" : "pending";
  return [
    {
      key: "observe",
      ordinal: 1,
      title: "Observe",
      note: hasIncident ? "Incident selected" : "Pick an incident",
      state: state(hasIncident, !hasIncident),
    },
    {
      key: "plan",
      ordinal: 2,
      title: "Plan",
      note: planned ? "Baseline saved" : "No plan yet",
      state: state(planned, hasIncident && !planned),
    },
    {
      key: "recommend",
      ordinal: 3,
      title: "Recommend",
      note: recommended ? "Allocation ready" : "Not generated",
      state: state(recommended, planned && !recommended),
    },
    {
      key: "decide",
      ordinal: 4,
      title: "Decide",
      note: decided ? "Recorded" : "Needs your name and a reason",
      state: state(decided, recommended && !decided),
    },
  ];
}

