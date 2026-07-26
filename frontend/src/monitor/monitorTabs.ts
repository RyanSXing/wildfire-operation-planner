export const MONITOR_TABS = [
  { id: "plan", label: "Plan" },
  { id: "resources", label: "Resources" },
  { id: "evidence", label: "Evidence" },
  { id: "audit", label: "Audit" },
] as const;

export type MonitorTab = (typeof MONITOR_TABS)[number]["id"];
