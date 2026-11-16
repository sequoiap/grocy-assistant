"""AI settings: a household default set by an admin, a personal override per user,
and which of the two a given person's receipts actually get."""

from fastapi.testclient import TestClient

from app.ai.base import AIError
from app.receipts.pipeline import parse_text

from .conftest import ALEX, SAM, jpeg_bytes, sign_in
from .receipts import samples
from .test_api_flow import wait_until_read

NO_AI = {"provider": "none", "model": None, "base_url": None, "mode": "fallback"}
PERSONAL, INSTANCE = "/api/settings/ai/personal", "/api/settings/ai/instance"


def household(client):
    """Alex (admin) on `client`, Sam (not an admin) on a second device."""
    sam = TestClient(client.app)
    sign_in(client, ALEX)
    sign_in(sam, SAM)
    return client, sam


def source(who) -> str:
    return who.get("/api/settings").json()["ai_source"]


def ai_available(who) -> bool:
    return who.post("/api/trips", json={}).json()["ai_available"]


def test_settings_for_admins_and_everyone_else(client, grocy):
    alex, sam = household(client)
    empty = {**NO_AI, "api_key_set": False}
    assert alex.get("/api/settings").json() == {
        "personal_ai": empty,
        "instance_ai": empty,
        "ai_source": "none",
    }
    # Everyone can read their settings; the household default is the admins' business.
    assert sam.get("/api/settings").json() == {
        "personal_ai": empty,
        "instance_ai": None,
        "ai_source": "none",
    }

    house = {
        "provider": "anthropic",
        "model": " claude-x ",
        "mode": "always",
        "api_key": "sk-house",
    }
    for call in (sam.put(INSTANCE, json=house), sam.post(f"{INSTANCE}/test")):
        assert call.status_code == 403 and isinstance(call.json()["detail"], str)
    assert source(sam) == "none"  # the refused update changed nothing

    r = alex.put(INSTANCE, json=house)
    assert r.status_code == 200 and "sk-house" not in r.text  # keys are never echoed
    assert r.json()["instance_ai"] == {
        "provider": "anthropic",
        "model": "claude-x",
        "base_url": None,
        "mode": "always",
        "api_key_set": True,
    }
    assert r.json()["ai_source"] == "instance"
    after = sam.get("/api/settings").json()
    assert after["instance_ai"] is None and after["ai_source"] == "instance"


def test_updates_are_partial_and_an_empty_key_clears_it(authed):
    authed.put(PERSONAL, json={"provider": "openai", "model": "gpt-x", "api_key": "sk-mine"})
    mine = authed.put(PERSONAL, json={"mode": "always"}).json()["personal_ai"]
    assert mine == {
        "provider": "openai",
        "model": "gpt-x",
        "base_url": None,
        "mode": "always",
        "api_key_set": True,
    }
    # A null key means "no change"; only an empty string clears it.
    mine = authed.put(PERSONAL, json={"model": "", "api_key": None}).json()["personal_ai"]
    assert (mine["model"], mine["api_key_set"]) == (None, True)
    mine = authed.put(PERSONAL, json={"api_key": ""}).json()["personal_ai"]
    assert (mine["provider"], mine["api_key_set"]) == ("openai", False)
    assert authed.put(PERSONAL, json={"provider": "gemini"}).status_code == 422


def test_personal_ai_beats_the_household_default_and_falls_back_to_it(client, grocy):
    alex, sam = household(client)
    assert (source(sam), ai_available(sam)) == ("none", False)

    alex.put(INSTANCE, json={"provider": "anthropic", "api_key": "sk-house"})
    assert (source(sam), ai_available(sam)) == ("instance", True)

    # A local model needs no key, just an address.
    sam.put(PERSONAL, json={"provider": "openai", "base_url": "http://ollama:11434/v1"})
    assert (source(sam), source(alex)) == ("personal", "instance")

    # A personal provider that can't work yet (no key) doesn't shadow the default.
    sam.put(PERSONAL, json={"provider": "anthropic"})
    assert source(sam) == "instance"
    sam.put(PERSONAL, json={"api_key": "sk-sam"})
    assert source(sam) == "personal"
    sam.put(PERSONAL, json={"provider": "none"})
    assert source(sam) == "instance"

    # With no household default either, there is no AI: OCR only.
    alex.put(INSTANCE, json={"api_key": ""})
    assert (source(sam), ai_available(sam), source(alex)) == ("none", False, "none")
    sam.put(PERSONAL, json={"provider": "anthropic"})  # Sam's key is still stored
    assert (source(sam), ai_available(sam), ai_available(alex)) == ("personal", True, False)


def test_a_receipt_is_read_with_the_uploaders_ai_settings(client, grocy, monkeypatch):
    alex, sam = household(client)
    alex.put(INSTANCE, json={"provider": "anthropic", "api_key": "sk-house", "mode": "fallback"})
    sam.put(PERSONAL, json={"provider": "openai", "api_key": "sk-sam", "mode": "always"})
    used: list[tuple[str, str]] = []

    class Provider:
        def __init__(self, cfg):
            self.cfg = cfg
            used.append(("built", cfg.api_key))

        async def extract_receipt(self, images, ocr_text=None):
            used.append(("read", self.cfg.api_key))
            raise AIError("no network in tests")

        async def match_lines(self, store_name, lines, candidates):
            return []

    monkeypatch.setattr("app.services.receipts.build_provider", Provider)
    monkeypatch.setattr(
        "app.services.receipts.parse_receipt_images", lambda paths: parse_text(samples.WALMART)
    )
    trip_id = alex.post("/api/trips", json={}).json()["id"]

    def upload(who):
        photo = [("files", ("r.jpg", jpeg_bytes(), "image/jpeg"))]
        assert who.post(f"/api/trips/{trip_id}/receipts", files=photo).status_code == 201
        return wait_until_read(who, trip_id)

    # Sam's own provider, in Sam's mode ("always": the AI reads every receipt).
    upload(sam)
    assert used == [("built", "sk-sam"), ("read", "sk-sam")]
    # Alex has no personal provider: the household's, which only steps in when OCR
    # is unsure, and this read was confident.
    used.clear()
    trip = upload(alex)
    assert used == [("built", "sk-house")]

    # Re-reading a receipt uses the settings of whoever asked for it.
    used.clear()
    receipt_id = trip["receipts"][0]["id"]
    assert sam.post(f"/api/receipts/{receipt_id}/reprocess", json={}).status_code == 200
    wait_until_read(sam, trip_id)
    assert used == [("built", "sk-sam"), ("read", "sk-sam")]


def test_ai_connection_tests(client, grocy, monkeypatch):
    alex, sam = household(client)
    assert sam.post(f"{PERSONAL}/test").json() == {
        "ok": False,
        "message": "You haven't set up an AI provider of your own",
    }
    assert alex.post(f"{INSTANCE}/test").json()["ok"] is False

    class Provider:
        def __init__(self, cfg):
            self.cfg = cfg

        async def ping(self):
            if self.cfg.api_key == "sk-bad":
                raise AIError("invalid key")
            return self.cfg.api_key

    monkeypatch.setattr("app.routers.settings.build_provider", Provider)
    alex.put(INSTANCE, json={"provider": "anthropic", "api_key": "sk-house"})
    sam.put(PERSONAL, json={"provider": "openai", "api_key": "sk-bad"})
    # Each endpoint tests the configuration it names, not whichever one is in use.
    assert alex.post(f"{INSTANCE}/test").json() == {
        "ok": True,
        "message": "AI provider responded (sk-house)",
    }
    assert alex.post(f"{PERSONAL}/test").json()["ok"] is False
    assert sam.post(f"{PERSONAL}/test").json() == {"ok": False, "message": "invalid key"}
