import { execFile } from "node:child_process";
import { connect } from "node:net";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

const run = promisify(execFile);
const projectRoot = fileURLToPath(new URL("../..", import.meta.url));
const replayPreview = fileURLToPath(
  new URL("../../scripts/replay-preview", import.meta.url),
);

const API_ORIGIN = process.env.WILDFIREOPS_API_ORIGIN ?? "http://127.0.0.1:8000";
const API_PORT = Number(new URL(API_ORIGIN).port || "80");

/**
 * `scripts/replay-preview` resets the replay Compose project *including its
 * volumes*. That is harmless on a machine with nothing running and destructive
 * on one where a preview — or a second worktree sharing the same Compose
 * project — is already using it.
 *
 * So the launcher only runs when nothing is listening on the API port at all,
 * i.e. when there is no environment to destroy. A port that is occupied but not
 * serving a healthy, seeded replay is reported rather than bulldozed.
 */
export default async function replayGlobalSetup(): Promise<void> {
  if (await isReplayReady()) {
    return;
  }
  if (await isPortOccupied(API_PORT)) {
    throw new Error(
      `${API_ORIGIN} is occupied but is not serving a seeded replay stack. ` +
        "Refusing to reset it, because that deletes the replay database. Stop " +
        "the owning process and run ./scripts/replay-preview yourself, or set " +
        "WILDFIREOPS_API_ORIGIN to a stack that is already running.",
    );
  }

  await run(replayPreview, [], { cwd: projectRoot });
  await waitFor("a seeded replay stack", async () => {
    if (!(await isReplayReady())) {
      throw new Error(`${API_ORIGIN} is not serving seeded incidents yet`);
    }
  });
}

async function isReplayReady(): Promise<boolean> {
  try {
    const health = await fetch(`${API_ORIGIN}/api/health`);
    if (!health.ok) {
      return false;
    }
    const response = await fetch(`${API_ORIGIN}/api/incidents`);
    const body: unknown = await response.json();
    return (
      response.ok &&
      !!body &&
      typeof body === "object" &&
      Array.isArray((body as { items?: unknown }).items) &&
      (body as { items: unknown[] }).items.length > 0
    );
  } catch {
    return false;
  }
}

function isPortOccupied(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const socket = connect({ host: "127.0.0.1", port });
    const settle = (occupied: boolean) => {
      socket.destroy();
      resolve(occupied);
    };
    socket.setTimeout(1_000);
    socket.once("connect", () => settle(true));
    socket.once("timeout", () => settle(false));
    socket.once("error", () => settle(false));
  });
}

async function waitFor(label: string, check: () => Promise<void>): Promise<void> {
  const deadline = Date.now() + 120_000;
  let failure: unknown;
  while (Date.now() < deadline) {
    try {
      await check();
      return;
    } catch (error) {
      failure = error;
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
  }
  throw new Error(`Timed out waiting for ${label}`, { cause: failure });
}
