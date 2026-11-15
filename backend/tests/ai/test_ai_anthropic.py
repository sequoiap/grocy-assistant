from __future__ import annotations

import json

import httpx2
import pytest
from conftest import GOOD_RECEIPT

from app.ai import AIConfig, AIError, build_provider
from app.ai.anthropic_provider import DEFAULT_MODEL, AnthropicProvider
from app.ai.base import MatchCandidate, MatchLine


def msg(text: str, stop: str = "end_turn", model: str = DEFAULT_MODEL) -> httpx2.Response:
    return httpx2.Response(
        200,
        json={
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": [{"type": "text", "text": text}],
            "stop_reason": stop,
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 10},
        },
    )


def err(status: int, kind: str, message: str = "boom") -> httpx2.Response:
    return httpx2.Response(
        status, json={"type": "error", "error": {"type": kind, "message": message}}
    )


def provider(http_client, **cfg) -> AnthropicProvider:
    return AnthropicProvider(
        AIConfig(provider="anthropic", api_key="sk-ant-test", **cfg),
        http_client=http_client,
        max_retries=0,
    )


async def test_extract_receipt_request_and_result(make_client, image, big_image):
    client, rec = make_client(msg(json.dumps(GOOD_RECEIPT)))
    p = provider(client)
    receipt = await p.extract_receipt([image, big_image], ocr_text="MILK 3.50")

    assert receipt.method == "ai" and receipt.store_key == "kroger"
    assert len(receipt.lines) == 3 and receipt.confidence > 0.9

    (req,) = rec.requests
    assert req.url.path == "/v1/messages" and req.headers["authorization"] == "Bearer sk-ant-test"
    body = rec.bodies()[0]
    assert body["model"] == "claude-opus-5-5"
    assert body["max_tokens"] >= 8000
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["output_config"]["format"]["schema"]["additionalProperties"] is False
    assert "temperature" not in body and "thinking" not in body
    blocks = body["messages"][0]["content"]
    images = [b for b in blocks if b["type"] == "image"]
    assert len(images) == 2
    assert all(i["source"]["media_type"] == "image/jpeg" for i in images)
    assert all(i["source"]["type"] == "base64" for i in images)
    text = " ".join(b["text"] for b in blocks if b["type"] == "text")
    assert "MILK 3.50" in text and "UNTRUSTED" in text
    assert "Photo 2 of 2" in text


async def test_model_override(make_client, image):
    client, rec = make_client(msg(json.dumps(GOOD_RECEIPT)))
    await provider(client, model="claude-sonnet-5-5").extract_receipt([image])
    assert rec.bodies()[0]["model"] == "claude-sonnet-5-5"


async def test_partial_output_is_tolerated(make_client, image):
    partial = {"items": [{"description": "MILK", "total_price": 3.5}, {"nope": 1}]}
    client, _ = make_client(msg(json.dumps(partial)))
    r = await provider(client).extract_receipt([image])
    assert [ln.description for ln in r.lines] == ["MILK"]
    assert r.warnings and r.confidence < 0.7


@pytest.mark.parametrize("text", ["I cannot read that.", "{broken", '{"foo": 1}'])
async def test_unparseable_output(make_client, image, text):
    client, _ = make_client(msg(text))
    with pytest.raises(AIError):
        await provider(client).extract_receipt([image])


async def test_refusal_and_truncation(make_client, image):
    client, _ = make_client(msg("", stop="refusal"))
    with pytest.raises(AIError, match="declined"):
        await provider(client).extract_receipt([image])
    client, _ = make_client(msg('{"items": [', stop="max_tokens"))
    with pytest.raises(AIError, match="ran out of room"):
        await provider(client).extract_receipt([image])


async def test_bad_image_and_no_images(make_client):
    from app.ai.base import ImageInput

    client, rec = make_client(msg("{}"))
    p = provider(client)
    with pytest.raises(AIError, match="could not be read"):
        await p.extract_receipt([ImageInput(b"junk", "image/jpeg")])
    with pytest.raises(AIError):
        await p.extract_receipt([])
    assert rec.requests == []


async def test_match_lines(make_client):
    reply = {
        "matches": [
            {"line_id": 1, "candidate_id": 10, "confidence": 0.95},
            {"line_id": 2, "candidate_id": 10, "confidence": 0.6},  # candidate reused
            {"line_id": 5, "candidate_id": 11, "confidence": 0.9},  # unknown line
        ]
    }
    client, rec = make_client(msg(json.dumps(reply)))
    lines = [MatchLine(1, "GV WHL MLK GAL", total_price=3.5), MatchLine(2, "OTHER")]
    cands = [MatchCandidate(10, "Great Value Whole Milk 1 Gallon", barcode="123")]
    got = await provider(client).match_lines("Walmart", lines, cands)
    assert [(m.line_id, m.candidate_id) for m in got] == [(1, 10)]
    body = rec.bodies()[0]
    sent = body["messages"][0]["content"]
    assert "GV WHL MLK GAL" in sent and "Great Value Whole Milk" in sent
    assert "123" not in sent  # barcodes are not sent
    assert "matches" in body["output_config"]["format"]["schema"]["properties"]


async def test_match_lines_empty_makes_no_request(make_client):
    client, rec = make_client(msg("{}"))
    p = provider(client)
    assert await p.match_lines(None, [], [MatchCandidate(1, "x")]) == []
    assert await p.match_lines(None, [MatchLine(1, "x")], []) == []
    assert rec.requests == []


async def test_ping(make_client):
    client, rec = make_client(msg("OK", model="claude-opus-5-5"))
    assert await provider(client).ping() == "claude-opus-5-5"
    assert rec.bodies()[0]["max_tokens"] <= 512


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (err(401, "authentication_error"), "API key was rejected"),
        (err(403, "permission_error"), "permission"),
        (err(404, "not_found_error", "model: nope"), "Model 'claude-opus-5-5' was not found"),
        (err(429, "rate_limit_error"), "rate limiting"),
        (err(529, "overloaded_error"), "temporarily unavailable"),
        (err(500, "api_error"), "temporarily unavailable"),
        (err(400, "invalid_request_error", "Your credit balance is too low"), "out of credit"),
        (err(400, "invalid_request_error", "bad thing"), "bad thing"),
        (httpx2.ReadTimeout("slow"), "took too long"),
        (httpx2.ConnectError("down"), "Could not reach"),
    ],
)
async def test_error_mapping(make_client, image, response, expected):
    for call in ("extract", "ping", "match"):
        client, _ = make_client(response)
        p = provider(client)
        with pytest.raises(AIError, match=expected) as ei:
            if call == "extract":
                await p.extract_receipt([image])
            elif call == "ping":
                await p.ping()
            else:
                await p.match_lines(None, [MatchLine(1, "a")], [MatchCandidate(1, "b")])
        assert "sk-ant-test" not in str(ei.value)


def test_construction_is_offline_and_validates():
    # No transport is injected: any network attempt here would fail or hang the test.
    p = build_provider(AIConfig(provider="anthropic", api_key="k"))
    assert p.name == "anthropic" and p.model == DEFAULT_MODEL
    assert build_provider(AIConfig(provider="anthropic", api_key="k", model="m")).model == "m"
    with pytest.raises(AIError, match="API key"):
        build_provider(AIConfig(provider="anthropic", api_key=" "))
