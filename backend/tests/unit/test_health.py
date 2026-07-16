from fastapi.testclient import TestClient

from wildfireops.main import create_app


def test_health_reports_service_name() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "wildfireops-api"}
