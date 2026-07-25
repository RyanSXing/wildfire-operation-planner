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
`GET /api/exercises/park-fire-decision`. The current frontend remains the
separate, incident-scoped Live Monitor until the planned Claude Code rebuild
consumes the stable exercise responses.
