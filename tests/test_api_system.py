def test_metrics_returns_envelope(client):
    r = client.get("/api/system/metrics")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "system"
    assert "data" in body and "cpu_percent" in body["data"]


def test_metrics_disk_is_list(client):
    r = client.get("/api/system/metrics")
    assert isinstance(r.json()["data"]["disk"], list)


def test_metrics_memory_shape(client):
    r = client.get("/api/system/metrics")
    mem = r.json()["data"]["memory"]
    for key in ("total", "used", "available", "percent"):
        assert key in mem


def test_stream_endpoint_registered(client):
    """Verify the SSE route is mounted. We don't actually invoke it in
    a sync test — TestClient reads the entire response which never ends
    for an infinite generator. Browser EventSource handles the live path
    in production."""
    routes = [r.path for r in client.app.routes]
    assert "/api/system/stream" in routes
