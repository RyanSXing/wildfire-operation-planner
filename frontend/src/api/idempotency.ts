export type IdempotencyAttempt = Readonly<{
  id: number;
  key: string;
}>;

type Settlement = "retain" | "consume";

export class IdempotencyIntent {
  private readonly createKey: () => string;
  private current:
    | { signature: string; key: string; attemptId: number | null }
    | undefined;
  private nextAttemptId = 0;

  constructor(createKey: () => string = () => crypto.randomUUID()) {
    this.createKey = createKey;
  }

  begin(signature: string): IdempotencyAttempt {
    const key =
      this.current?.signature === signature
        ? this.current.key
        : this.createKey();
    const id = ++this.nextAttemptId;
    this.current = { signature, key, attemptId: id };
    return { id, key };
  }

  settle(attempt: IdempotencyAttempt, settlement: Settlement): void {
    if (this.current?.attemptId !== attempt.id) {
      return;
    }
    if (settlement === "consume") {
      this.current = undefined;
    } else {
      this.current.attemptId = null;
    }
  }

  discard(): void {
    this.current = undefined;
  }
}
