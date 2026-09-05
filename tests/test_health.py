from fastapi.testclient import TestClient

from app.main import app


def test_health_check_returns_service_metadata() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "DEV Placement OS",
        "environment": "development",
    }

