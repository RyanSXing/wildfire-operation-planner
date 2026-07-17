import { describe, expect, it } from "vitest";

import { IdempotencyIntent } from "./idempotency";

function intentWithKeys(...keys: string[]): IdempotencyIntent {
  let index = 0;
  return new IdempotencyIntent(() => keys[index++]);
}

describe("IdempotencyIntent", () => {
  it("reuses one key for an unchanged retry and replaces it for changed intent", () => {
    const intent = intentWithKeys("key-1", "key-2");
    const first = intent.begin("scenario:a");
    intent.settle(first, "retain");

    expect(intent.begin("scenario:a").key).toBe("key-1");
    expect(intent.begin("scenario:b").key).toBe("key-2");
  });

  it.each(["success", "terminal"] as const)(
    "consumes a key after %s settlement",
    () => {
      const intent = intentWithKeys("key-1", "key-2");
      const attempt = intent.begin("scenario:a");

      intent.settle(attempt, "consume");

      expect(intent.begin("scenario:a").key).toBe("key-2");
    },
  );

  it("ignores out-of-order settlement from an older attempt", () => {
    const intent = intentWithKeys("key-1", "key-2", "key-3");
    const oldAttempt = intent.begin("scenario:a");
    const currentAttempt = intent.begin("scenario:b");

    intent.settle(oldAttempt, "consume");
    intent.settle(currentAttempt, "retain");
    const retry = intent.begin("scenario:b");
    expect(retry.key).toBe("key-2");

    intent.settle(currentAttempt, "consume");
    intent.settle(retry, "consume");
    expect(intent.begin("scenario:b").key).toBe("key-3");
  });

  it("discards retained retry intent explicitly", () => {
    const intent = intentWithKeys("key-1", "key-2");
    const attempt = intent.begin("scenario:a");
    intent.settle(attempt, "retain");

    intent.discard();

    expect(intent.begin("scenario:a").key).toBe("key-2");
  });
});
