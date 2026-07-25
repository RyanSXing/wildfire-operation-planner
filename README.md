# WildfireOps

WildfireOps is a portfolio simulation. Do not use it for emergency or life-safety decisions.

## Local startup

With Docker running, start the PostGIS database, API, and frontend:

```bash
make dev
```

- Frontend: <http://localhost:5173>
- API: <http://localhost:8000> (health: <http://localhost:8000/api/health>)

Stop the local services with:

```bash
make down
```

## Park Fire replay preview

Run `./scripts/replay-preview` from anywhere in the repository. The launcher uses the dedicated `wildfireops-replay-preview` Compose project, deletes only that project's containers and volumes, and starts only `db`, `api`, and `frontend`; the live ingestion worker is excluded. The replay database is not published to the host.

The preview listens on <http://127.0.0.1:5173> and the API on <http://127.0.0.1:8000>. If either host port is already occupied, startup stops with an error and does not stop or reset the ordinary development Compose project. Stop the owning process explicitly, then rerun the launcher.

## Park Fire Decision Exercise

Run `./scripts/replay-preview`, then verify the backend contract:

`curl --fail http://127.0.0.1:8000/api/exercises/park-fire-decision`

The exercise combines pinned historical fire, weather, road, community, and
public-facility inputs with clearly labeled simulated resources, operational
tasks, disruptions, field reports, recommendations, and decisions. It is a
portfolio exercise and must not be used for emergency or life-safety decisions.

The backend exercise contract is available at
`GET /api/exercises/park-fire-decision`.

### Frontend routes

The exercise is the primary experience.

| Route      | Screen                                                     |
| ---------- | ---------------------------------------------------------- |
| `/`        | Park Fire decision exercise — the guided, task-based flow   |
| `/monitor` | Live Monitor — the original incident-scoped dashboard       |

The exercise walks an operator from the safety and provenance briefing through
objective selection, three checkpoints, the shelter field-report override, a
named approval with a written decision note, and finally the audit timeline,
debrief, and a read-only planning sandbox. Every screen reads from the exercise
API; nothing is mocked and no planning logic is duplicated in the browser.

Desktop-only by design: the workspace assumes a rail, a map, and a detail
drawer side by side.

### Verifying the frontend

```bash
cd frontend && npm run lint && npx tsc -b && npm test -- --run && npm run build
```

End-to-end, against a running replay stack:

```bash
cd frontend && npx playwright test e2e/park-fire-exercise.spec.ts
```

The Playwright global setup reuses an already-healthy replay stack and only
invokes `./scripts/replay-preview` when nothing is listening, so running the
suite does not destroy a preview you are already using. Set
`PLAYWRIGHT_BASE_URL` when the dev server is not on port 5173.
