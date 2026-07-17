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
