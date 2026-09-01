"""Voice → text endpoint (Groq Whisper), with the provider mocked."""
import httpx
import respx
from fastapi.testclient import TestClient

from app.main import app
from app.transcribe import GROQ_TRANSCRIBE_URL

client = TestClient(app)


@respx.mock
def test_transcribe_returns_text(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    route = respx.post(GROQ_TRANSCRIBE_URL).mock(
        return_value=httpx.Response(200, json={"text": "  shortlist this candidate  "})
    )
    resp = client.post("/transcribe", files={"file": ("a.webm", b"fakeaudio", "audio/webm")})
    assert resp.status_code == 200
    assert resp.json()["text"] == "shortlist this candidate"  # trimmed
    assert route.called


def test_transcribe_no_key_is_400(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    resp = client.post("/transcribe", files={"file": ("a.webm", b"x", "audio/webm")})
    assert resp.status_code == 400


@respx.mock
def test_transcribe_provider_error_is_502(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    respx.post(GROQ_TRANSCRIBE_URL).mock(return_value=httpx.Response(500, text="boom"))
    resp = client.post("/transcribe", files={"file": ("a.webm", b"x", "audio/webm")})
    assert resp.status_code == 502
