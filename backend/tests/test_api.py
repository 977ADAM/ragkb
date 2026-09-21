"""Контракт HTTP и сценарии диалога."""
from __future__ import annotations

from uuid import uuid4



def test_health_anonymous(client):
    assert client.get("/health").json() == {"status": "ok"}




def test_organization_and_bootstrap(client):
    org = client.get("/api/v1/organization").json()
    assert org["id"] == "acme"
    sid = str(uuid4())
    boot = client.get("/api/v1/bootstrap", params={"session_id": sid}).json()
    assert boot["session_id"] == sid
    assert "user" not in boot
    assert "conversations" not in boot
    assert boot["organization"]["id"] == "acme"




def test_foreign_org_is_404(client):
    assert client.get("/api/v1/organization/other/chat_conversations").status_code == 404


def test_foreign_conversation_is_404(client):
    assert (
        client.get(f"/api/v1/organization/acme/chat_conversations/{uuid4()}").status_code
        == 404
    )


def test_search(client):
    data = client.post("/api/v1/search", json={"query": "отпуск", "top_k": 3}).json()
    assert data["results"]


def test_events(client):
    res = client.post(
        "/api/v1/events",
        json={
            "session_id": str(uuid4()),
            "events": [{"name": "page_view", "props": {}}],
        },
    )
    assert res.json() == {"accepted": 1}


def test_models_static(client):
    models = client.get("/api/v1/models").json()["models"]
    assert models[0]["is_default"] is True
