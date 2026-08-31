"""Team chat: post + poll history, attributed to the acting user."""
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _chat_store(tmp_path, monkeypatch):
    monkeypatch.setenv("CATALIST_CHAT_STORE_PATH", str(tmp_path / "chat.json"))


def test_post_and_list_message():
    r = client.post("/chat/messages", json={"body": "  hello team  "})
    assert r.status_code == 201, r.text
    msg = r.json()
    assert msg["body"] == "hello team"  # trimmed
    assert msg["username"] == "tester" and msg["full_name"] == "tester"
    assert msg["id"] >= 1

    listed = client.get("/chat/messages").json()
    assert [m["body"] for m in listed] == ["hello team"]


def test_empty_message_rejected():
    assert client.post("/chat/messages", json={"body": "   "}).status_code == 400


def test_after_cursor_returns_only_newer():
    a = client.post("/chat/messages", json={"body": "first"}).json()
    client.post("/chat/messages", json={"body": "second"}).json()
    newer = client.get(f"/chat/messages?after={a['id']}").json()
    assert [m["body"] for m in newer] == ["second"]


def test_history_is_chronological():
    for i in range(3):
        client.post("/chat/messages", json={"body": f"m{i}"})
    listed = client.get("/chat/messages").json()
    assert [m["body"] for m in listed] == ["m0", "m1", "m2"]
    assert [m["id"] for m in listed] == sorted(m["id"] for m in listed)
