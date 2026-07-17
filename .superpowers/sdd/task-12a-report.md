# Task 12A implementation report

## Outcome

Task 12A bridges the separate ingestion-worker and API processes with
transactional PostgreSQL notifications. Committed ingestion updates reach every
API process through a dedicated listener and the existing SSE endpoint;
rolled-back updates remain invisible. Overflowed subscriber queues collapse to a
single local `resync-required` invalidation hint.

## Changed files

- `backend/src/wildfireops/persistence/notifications.py`
- `backend/src/wildfireops/ingestion/service.py`
- `backend/src/wildfireops/api/postgres_events.py`
- `backend/src/wildfireops/api/event_bus.py`
- `backend/src/wildfireops/main.py`
- `backend/tests/integration/ingestion/test_notifications.py`
- `backend/tests/unit/api/test_postgres_events.py`
- `backend/tests/unit/api/test_event_bus.py`
- `backend/tests/unit/persistence/test_notification_publisher.py`
- `backend/tests/unit/test_health.py`
- `.superpowers/sdd/task-12a-report.md`

## RED evidence

All database-backed commands used the required API-container test database URL.

1. Queue overflow, local resync, and queue-join accounting:

   ```text
   pytest -q tests/unit/api/test_event_bus.py \
     -k 'full_queue or resync or coalescing'
   FFF
   3 failed
   ```

   The old bus retained targeted events on overflow and rejected
   `resync-required` as an unsupported name.

2. PostgreSQL codec/listener relay before its module existed:

   ```text
   pytest -q tests/unit/api/test_postgres_events.py
   ModuleNotFoundError: No module named 'wildfireops.api.postgres_events'
   1 error during collection
   ```

3. Transaction-coupled ingestion notifications:

   ```text
   pytest -q tests/integration/ingestion/test_notifications.py
   FFF
   3 failed in 4.77s
   ```

   The listener received zero payloads where the success/processing-failure/
   fetch-failure contracts expected `3/1/1` respectively.

4. FastAPI lifespan ownership before the relay injection/startup seam existed:

   ```text
   pytest -q tests/unit/test_health.py -k lifespan
   FAILED test_lifespan_starts_listener_then_cancels_and_awaits_before_dispose
   TypeError: create_app() got an unexpected keyword argument 'event_relay'
   1 failed, 1 deselected
   ```

5. Final hardening regressions were written before their fixes:

   ```text
   pytest -q tests/unit/api/test_postgres_events.py \
     tests/unit/persistence/test_notifications.py \
     tests/unit/test_health.py
   4 failed, 14 passed
   ```

   These proved whitespace-only source names were accepted by both boundaries,
   retry failures had no sanitized warning seam, and an already-failed relay
   prevented engine disposal. The unit publisher module was subsequently renamed
   to `test_notification_publisher.py` to avoid a pytest basename collision with
   the integration module.

## GREEN evidence

- Initial notification/listener/EventBus/lifespan slice: `28 passed in 1.92s`.
- Hardening regression set: `18 passed in 1.31s`.
- Final focused ingestion, listener, EventBus/SSE, publisher, and lifespan suite:
  `107 passed in 9.51s`.
- Complete backend suite: `567 passed, 3 warnings in 21.55s`.
- Ruff format check: `113 files already formatted`.
- Ruff check: `All checks passed!`.
- Mypy: `Success: no issues found in 70 source files`.
- `git diff --check`: clean.

The three full-suite warnings are existing Python multiprocessing `fork()`
deprecation warnings from road-graph concurrency tests; Task 12A added no warning.

## Design choices

- The ingestion service remains the sole transaction owner. Its notification
  adapter only resolves returned snapshot IDs, executes parameter-bound
  `pg_notify` statements, and never commits.
- Successful runs resolve distinct incident IDs inside the same session, publish
  them in sorted UUID order, then publish the source-status hint. Failure-status
  transactions publish only their matching source hint.
- The API relay owns one dedicated asyncpg connection. It validates the exact
  frozen event envelopes, ignores malformed or oversized payloads, retries with
  a bounded delay, logs only a stable failure type, and emits a local resync only
  after `add_listener` succeeds.
- Lifespan cancellation awaits listener cleanup before engine disposal. Engine
  disposal also runs if an injected or defective relay has already failed, after
  which the relay error still propagates.
- Queue overflow replaces all queued targeted invalidations with one resync
  marker while adjusting unfinished-task accounting in place, so the queue stays
  bounded and `join()` never observes a false completion.

## Concerns

No Task 12A correctness concern remains. Notifications are intentionally
at-most-once cache-invalidation hints; clients reconcile through the existing
HTTP read APIs after reconnect or overflow rather than relying on durable replay.

## Review correction: recursion-safe notification decoding

Review found that a valid-size, deeply nested JSON notification could make the
JSON decoder raise `RecursionError`. That exception was outside the codec's
malformed-payload guard, so it could escape the asyncpg callback and allow the
event loop to log callback arguments containing the raw payload.

The regression uses a valid 7,999-byte nested JSON document and deterministically
exercises the decoder's platform-dependent recursion failure. Before the fix:

```text
pytest -q \
  tests/unit/api/test_postgres_events.py::test_notification_codec_ignores_deep_json_parser_recursion
FAILED test_notification_codec_ignores_deep_json_parser_recursion
RecursionError
1 failed in 0.19s
```

After adding `RecursionError` to the existing codec-boundary exception guard:

- Isolated regression: `1 passed in 0.16s`.
- Focused Task 12A suite: `108 passed in 9.67s`.
- Complete backend suite: `568 passed, 3 warnings in 21.60s`.
- Ruff format check: `113 files already formatted`.
- Ruff check: `All checks passed!`.
- Mypy: `Success: no issues found in 70 source files`.
- `git diff --check`: clean.

The three warnings remain the existing road-graph multiprocessing `fork()`
deprecation warnings.
