"""Контракт HTTP и сценарии диалога."""
from __future__ import annotations

import json
from uuid import uuid4

from ragkb.domain.entities import ANONYMOUS


def test_health_anonymous(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_unauthenticated_when_proxy_mode(indexed):
    from fastapi.testclient import TestClient

    from ragkb.app import create_app

    indexed.auth.mode = "proxy"
    with TestClient(create_app(indexed)) as client:
        res = client.get("/models")
    assert res.status_code == 401


def test_organization_and_bootstrap(client):
    org = client.get("/organization").json()
    assert org["id"] == "acme"
    sid = str(uuid4())
    boot = client.get("/bootstrap", params={"session_id": sid}).json()
    assert boot["session_id"] == sid
    assert boot["user"]["name"] == ANONYMOUS
    assert boot["user"]["is_admin"] is True
    assert boot["organization"]["id"] == "acme"
    assert boot["capabilities"]["history"] is True
    assert boot["capabilities"]["reindex"] is True


def test_create_conversation_then_message_stream(client):
    created = client.post("/organization/acme/chat_conversations").json()
    cid = created["conversation_id"]
    assert created["title"] == ""
    res = client.post(
        f"/organization/acme/chat_conversations/{cid}/messages",
        json={"question": "сколько дней отпуска?"},
    )
    assert res.status_code == 200
    lines = [json.loads(line) for line in res.text.strip().splitlines() if line]
    assert lines[0]["type"] == "token"
    assert lines[-1]["type"] == "done"
    assert lines[-1]["truncated"] is False
    assert "error" not in {e["type"] for e in lines}
    for source in lines[-1].get("sources", []):
        assert "text" in source, "источник несёт фрагмент текста"
    body = client.get(f"/organization/acme/chat_conversations/{cid}").json()
    roles = [m["role"] for m in body["messages"]]
    assert roles[:2] == ["user", "assistant"]


def test_foreign_org_is_404(client):
    assert client.get("/organization/other/chat_conversations").status_code == 404


def test_foreign_conversation_is_404(client):
    assert (
        client.get(f"/organization/acme/chat_conversations/{uuid4()}").status_code
        == 404
    )


def test_search(client):
    data = client.post("/search", json={"query": "отпуск", "top_k": 3}).json()
    assert data["results"]


def test_events(client):
    res = client.post(
        "/events",
        json={
            "session_id": str(uuid4()),
            "events": [{"name": "page_view", "props": {}}],
        },
    )
    assert res.json() == {"accepted": 1}


def test_models_static(client):
    models = client.get("/models").json()["models"]
    assert models[0]["is_default"] is True
