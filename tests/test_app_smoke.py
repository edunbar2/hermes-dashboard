def test_healthz_ok(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Hermes Dashboard" in r.text
