export const DRAWER_TABS = [
  { id: "plan", label: "Plan" },
  { id: "tasks", label: "Tasks" },
  { id: "evidence", label: "Evidence" },
  { id: "audit", label: "Audit" },
] as const;

export type DrawerTab = (typeof DRAWER_TABS)[number]["id"];
