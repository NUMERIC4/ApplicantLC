from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from backend.ai_service import ai_service
from backend.main import app


@pytest.fixture
def restore_ai_service_state():
    original_key = ai_service.api_key
    original_model = ai_service.default_model
    original_base_url = ai_service.base_url
    try:
        yield
    finally:
        ai_service.api_key = original_key
        ai_service.default_model = original_model
        ai_service.base_url = original_base_url


@pytest.mark.asyncio
async def test_missing_key_returns_controlled_smoke_error(restore_ai_service_state):
    ai_service.api_key = ""

    result = await ai_service.test_connection()

    assert result["success"] is False
    assert result["error"] == {
        "code": "missing_api_key",
        "message": "NVIDIA API key is not configured.",
    }
    assert result["response"] is None


@pytest.mark.asyncio
async def test_safe_status_never_returns_key_and_rejects_key_updates(restore_ai_service_state):
    secret_value = "must-never-appear-in-response"
    ai_service.api_key = secret_value

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        status_response = await client.get("/api/ai/config")
        rejected_update = await client.post(
            "/api/ai/config/update",
            json={"nvidia_api_key": secret_value},
        )

    assert status_response.status_code == 200
    payload = status_response.json()
    assert payload["configured"] is True
    assert payload["api_key_present"] is True
    assert secret_value not in status_response.text
    assert "nvidia_api_key" not in payload
    assert rejected_update.status_code == 422


@pytest.mark.asyncio
async def test_mocked_smoke_inference_returns_sanitized_response(monkeypatch, restore_ai_service_state):
    class FakeCompletions:
        async def create(self, **_kwargs):
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="ready"))],
                usage=SimpleNamespace(prompt_tokens=7, completion_tokens=1, total_tokens=8),
            )

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    ai_service.api_key = "test-key-not-sent"
    monkeypatch.setattr(ai_service, "_get_client", lambda: fake_client)

    result = await ai_service.test_connection()

    assert result["success"] is True
    assert result["provider"] == "nvidia"
    assert result["model"] == ai_service.default_model
    assert isinstance(result["latency_ms"], int)
    assert result["latency_ms"] >= 0
    assert result["response"] == "ready"
    assert result["usage"] == {"prompt_tokens": 7, "completion_tokens": 1, "total_tokens": 8}
    assert result["error"] is None


@pytest.mark.asyncio
async def test_mocked_provider_failure_is_controlled(monkeypatch, restore_ai_service_state):
    class FailingCompletions:
        async def create(self, **_kwargs):
            raise RuntimeError("internal provider details must not leak")

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FailingCompletions()))
    ai_service.api_key = "test-key-not-sent"
    monkeypatch.setattr(ai_service, "_get_client", lambda: fake_client)

    result = await ai_service.test_connection()

    assert result["success"] is False
    assert result["error"]["code"] == "provider_error"
    assert "internal provider details" not in result["error"]["message"]


@pytest.mark.asyncio
async def test_smoke_route_delegates_to_service(monkeypatch):
    expected = {
        "success": True,
        "provider": "nvidia",
        "model": "mock-model",
        "latency_ms": 1,
        "response": "ready",
        "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
        "error": None,
    }

    async def fake_test_connection():
        return expected

    monkeypatch.setattr(ai_service, "test_connection", fake_test_connection)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/ai/test-connection")

    assert response.status_code == 200
    assert response.json() == expected
