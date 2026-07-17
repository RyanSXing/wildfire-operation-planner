import { execFile } from "node:child_process";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

const run = promisify(execFile);
const projectRoot = fileURLToPath(new URL("../..", import.meta.url));
const compose = ["compose", "-f", "compose.yaml", "-f", "compose.replay.yaml"];

export default async function replayGlobalSetup(): Promise<void> {
  await dockerCompose("up", "-d", "db");
  await waitFor("database", async () => {
    await dockerCompose("exec", "-T", "db", "pg_isready", "-U", "wildfireops", "-d", "template1");
  });
  await dockerCompose("stop", "api", "frontend");
  await dockerCompose(
    "exec",
    "-T",
    "db",
    "psql",
    "-v",
    "ON_ERROR_STOP=1",
    "-U",
    "wildfireops",
    "-d",
    "template1",
    "-c",
    "DROP DATABASE IF EXISTS wildfireops WITH (FORCE);",
    "-c",
    "CREATE DATABASE wildfireops OWNER wildfireops TEMPLATE template_postgis;",
  );
  await dockerCompose("up", "-d", "--force-recreate", "db", "api", "frontend");
  await waitFor("replay API", async () => {
    const response = await fetch("http://127.0.0.1:8000/api/health");
    if (!response.ok) throw new Error(`health returned ${response.status}`);
  });
  await waitFor("seeded incidents", async () => {
    const response = await fetch("http://127.0.0.1:8000/api/incidents");
    const body: unknown = await response.json();
    if (
      !response.ok ||
      !body ||
      typeof body !== "object" ||
      !Array.isArray((body as { items?: unknown }).items) ||
      (body as { items: unknown[] }).items.length === 0
    ) {
      throw new Error("incidents are not ready");
    }
  });
}

async function dockerCompose(...args: string[]): Promise<void> {
  await run("docker", [...compose, ...args], { cwd: projectRoot });
}

async function waitFor(label: string, check: () => Promise<void>): Promise<void> {
  const deadline = Date.now() + 60_000;
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
