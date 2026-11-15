from __future__ import annotations

import json

import httpx2
import pytest
from conftest import GOOD_RECEIPT

from app.ai import AIConfig, AIError, build_provider
from app.ai.base import MatchCandidate, MatchLine
from app.ai.openai_provider import DEFAULT_MODEL, OpenAICompatProvider


def chat(content: str | None, finish: str = "stop", **message) -> httpx2.Response:
    return httpx2.Response(
        200,
        json={
            "id": "c1",
            "object": "chat.completion",
            "created": 0,
            "model": "served-model",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content, **message},
                    "finish_reason": finish,
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        },
    )


def err(status: int, message: str = "boom", code: str | None = None) -> httpx2.Response:
    return httpx2.Response(status, json={"error": {"message": message, "code": code}})


def provider(http_client, **cfg) -> OpenAICompatProvider:
    cfg.setdefault("api_key", "sk-test")
    return OpenAICompatProvider(
        AIConfig(provider="openai", **cfg), http_client=http_client, max_retries=0
    )


LOCAL = {"base_url": "http://localhost:11434/v1", "model": "qwen2.5vl", "api_key": None}


async def test_extract_openai_structured(make_client, image):
    client, rec = make_client(chat(json.dumps(GOOD_RECEIPT)))
    r = await provider(client).extract_receipt([image, image], ocr_text="hint text")
    assert r.method == "ai" and r.store_key == "kroger" and r.confidence > 0.9

    (req,) = rec.requests
    assert str(req.url) == "https://api.openai.com/v1/chat/completions"
    assert req.headers["authorization"] == "Bearer sk-test"
    body = rec.bodies()[0]
    assert body["model"] == DEFAULT_MODEL
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert "max_completion_tokens" in body and "max_tokens" not in body
    assert "temperature" not in body
    parts = body["messages"][1]["content"]
    urls = [p["image_url"]["url"] for p in parts if p["type"] == "image_url"]
    assert len(urls) == 2 and all(u.startswith("data:image/jpeg;base64,") for u in urls)
    text = " ".join(p["text"] for p in parts if p["type"] == "text")
    assert "hint text" in text and "UNTRUSTED" in text
    assert "JSON Schema" not in text  # schema only inlined when not enforced by the server


async def test_local_server_no_key_uses_placeholder(make_client, image):
    client, rec = make_client(chat(json.dumps(GOOD_RECEIPT)))
    await provider(client, **LOCAL).extract_receipt([image])
    req = rec.requests[0]
    assert str(req.url) == "http://localhost:11434/v1/chat/completions"
    assert req.headers["authorization"] == "Bearer not-needed"
    body = rec.bodies()[0]
    assert body["model"] == "qwen2.5vl" and body["max_tokens"] and body["temperature"] == 0
    assert "max_completion_tokens" not in body


async def test_fallback_to_json_object_when_schema_rejected(make_client, image):
    client, rec = make_client(
        err(400, "response_format of type json_schema is not supported"),
        chat(json.dumps(GOOD_RECEIPT)),
    )
    r = await provider(client, **LOCAL).extract_receipt([image])
    assert len(r.lines) == 3
    formats = [b.get("response_format", {}).get("type") for b in rec.bodies()]
    assert formats == ["json_schema", "json_object"]
    # JSON mode needs the schema spelled out in the prompt
    assert "JSON Schema" in json.dumps(rec.bodies()[1]["messages"])


async def test_fallback_chain_to_plain_with_fenced_json(make_client, image):
    fenced = "Here is the receipt:\n```json\n" + json.dumps(GOOD_RECEIPT) + "\n```"
    client, rec = make_client(err(400, "nope"), err(422, "still nope"), chat(fenced))
    r = await provider(client, **LOCAL).extract_receipt([image])
    assert len(r.lines) == 3
    formats = [b.get("response_format") for b in rec.bodies()]
    assert [f and f["type"] for f in formats] == ["json_schema", "json_object", None]


async def test_fallback_when_server_silently_ignores_format(make_client, image):
    # Ollama-style: 200 OK but prose in the first two attempts.
    client, rec = make_client(
        chat("I see a receipt with milk."),
        chat('{"unexpected": true}'),
        chat(json.dumps(GOOD_RECEIPT)),
    )
    r = await provider(client, **LOCAL).extract_receipt([image])
    assert len(r.lines) == 3 and len(rec.requests) == 3


async def test_all_modes_fail(make_client, image):
    client, rec = make_client(chat("no json at all"))
    with pytest.raises(AIError, match="could not be understood"):
        await provider(client, **LOCAL).extract_receipt([image])
    assert len(rec.requests) == 3
    client, rec = make_client(err(400, "bad"))
    with pytest.raises(AIError, match="rejected the request"):
        await provider(client, **LOCAL).extract_receipt([image])
    assert len(rec.requests) == 3


async def test_non_vision_model_is_reported_without_fallback_loop(make_client, image):
    client, rec = make_client(err(400, "This model does not support image input"))
    with pytest.raises(AIError, match="does not appear to accept images"):
        await provider(client, **LOCAL).extract_receipt([image])
    assert len(rec.requests) == 1


async def test_refusal_and_truncation(make_client, image):
    client, _ = make_client(chat(None, refusal="I can't help with that"))
    with pytest.raises(AIError, match="declined"):
        await provider(client).extract_receipt([image])
    client, _ = make_client(chat('{"items": [', finish="length"))
    with pytest.raises(AIError, match="ran out of room"):
        await provider(client).extract_receipt([image])


async def test_match_lines_validation(make_client):
    reply = {
        "matches": [
            {"line_id": 1, "candidate_id": 10, "confidence": 0.9},
            {"line_id": 1, "candidate_id": 11, "confidence": 0.8},  # line reused
            {"line_id": 2, "candidate_id": 99, "confidence": 0.9},  # unknown candidate
            {"line_id": 3, "candidate_id": 11, "confidence": 0.1},  # implausible
        ]
    }
    client, rec = make_client(chat(json.dumps(reply)))
    lines = [MatchLine(1, "GV WHL MLK GAL"), MatchLine(2, "X"), MatchLine(3, "Y")]
    cands = [MatchCandidate(10, "Great Value Whole Milk 1 Gallon"), MatchCandidate(11, "Z")]
    got = await provider(client).match_lines("Walmart", lines, cands)
    assert [(m.line_id, m.candidate_id) for m in got] == [(1, 10)]
    assert "untrusted" in rec.bodies()[0]["messages"][1]["content"]


async def test_match_lines_empty_makes_no_request(make_client):
    client, rec = make_client(chat("{}"))
    assert await provider(client).match_lines(None, [], []) == []
    assert rec.requests == []


async def test_ping(make_client):
    client, rec = make_client(chat("OK"))
    assert await provider(client).ping() == "served-model"
    assert "response_format" not in rec.bodies()[0]


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (err(401), "API key was rejected"),
        (err(403), "permission"),
        (err(404, "model not found"), "Model 'qwen2.5vl' was not found on this server"),
        (err(429), "rate limiting"),
        (err(429, "quota", code="insufficient_quota"), "out of credit"),
        (err(503), "temporarily unavailable"),
        (httpx2.ReadTimeout("slow"), "took too long"),
        (httpx2.ConnectError("down"), "Could not connect to the AI server at http://localhost"),
    ],
)
async def test_error_mapping(make_client, image, response, expected):
    for call in ("extract", "ping", "match"):
        client, _ = make_client(response)
        p = provider(client, **LOCAL)
        with pytest.raises(AIError, match=expected):
            if call == "extract":
                await p.extract_receipt([image])
            elif call == "ping":
                await p.ping()
            else:
                await p.match_lines(None, [MatchLine(1, "a")], [MatchCandidate(1, "b")])


def test_build_provider_openai_and_bad_config():
    p = build_provider(AIConfig(provider="openai", api_key="k"))
    assert p.name == "openai" and p.model == DEFAULT_MODEL
    p = build_provider(AIConfig(provider="OpenAI", **LOCAL))  # no key needed locally
    assert p.model == "qwen2.5vl"
    with pytest.raises(AIError, match="model name"):
        build_provider(AIConfig(provider="openai", base_url="http://localhost:11434/v1"))
    with pytest.raises(AIError, match="API key"):
        build_provider(AIConfig(provider="openai"))
    with pytest.raises(AIError, match="Unknown AI provider"):
        build_provider(AIConfig(provider="gemini", api_key="k"))
