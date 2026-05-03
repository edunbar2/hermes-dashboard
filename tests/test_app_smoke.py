def test_healthz_ok(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Hermes Dashboard" in r.text
    # Confirm the panel skeleton + module entrypoint are present.
    assert 'data-panel="system"' in r.text
    assert 'data-panel="agents"' in r.text
    assert 'data-panel="kanban"' in r.text
    assert 'data-panel="chat"' in r.text
    assert "/static/app.js" in r.text


def test_static_assets_served(client):
    """Each panel module + the entrypoint + stylesheet must be reachable."""
    for path in [
        "/static/style.css",
        "/static/app.js",
        "/static/panels/system.js",
        "/static/panels/agents.js",
        "/static/panels/kanban.js",
        "/static/panels/chat.js",
    ]:
        r = client.get(path)
        assert r.status_code == 200, f"{path} → {r.status_code}"
        assert len(r.content) > 0

