.PHONY: dev down test-backend test-frontend test

dev:
	docker compose up --build

down:
	docker compose down

test-backend:
	cd backend && uv run pytest

test-frontend:
	cd frontend && npm test -- --run

test: test-backend test-frontend
