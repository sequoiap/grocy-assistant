import httpx
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..ai import build_provider
from ..ai.base import AIConfig, AIError
from ..db import get_db
from ..deps import current_user, fresh_user, get_http, require_admin
from ..grocy.client import GrocyError
from ..models import User
from ..schemas import AISettingsIn, SettingsOut, TestResult
from ..services.accounts import grocy_for
from ..services.settings import (
    instance_ai_config,
    instance_ai_out,
    personal_ai_config,
    personal_ai_out,
    resolve_ai,
    update_instance_ai,
    update_personal_ai,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _settings_out(db: Session, user: User) -> SettingsOut:
    return SettingsOut(
        personal_ai=personal_ai_out(user),
        instance_ai=instance_ai_out(db) if user.is_admin else None,
        ai_source=resolve_ai(db, user).source,
    )


@router.get("", response_model=SettingsOut)
def read_settings(user: User = Depends(fresh_user), db: Session = Depends(get_db)):
    return _settings_out(db, user)


@router.put("/ai/personal", response_model=SettingsOut)
def update_personal(
    body: AISettingsIn, user: User = Depends(fresh_user), db: Session = Depends(get_db)
):
    """The signed-in user's own AI provider, used instead of the household default."""
    update_personal_ai(user, body)
    db.commit()
    return _settings_out(db, user)


@router.put("/ai/instance", response_model=SettingsOut)
def update_instance(
    body: AISettingsIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)
):
    """The household default, for everyone who hasn't set up a provider of their own."""
    update_instance_ai(db, body)
    db.commit()
    return _settings_out(db, admin)


async def _ping(cfg: AIConfig | None, missing: str) -> TestResult:
    if cfg is None:
        return TestResult(ok=False, message=missing)
    try:
        detail = await build_provider(cfg).ping()
    except AIError as exc:
        return TestResult(ok=False, message=str(exc))
    return TestResult(ok=True, message=f"AI provider responded ({detail})")


@router.post("/ai/personal/test", response_model=TestResult)
async def test_personal(user: User = Depends(current_user)):
    return await _ping(personal_ai_config(user), "You haven't set up an AI provider of your own")


@router.post("/ai/instance/test", response_model=TestResult)
async def test_instance(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return await _ping(instance_ai_config(db), "No household AI provider is set up")


@router.post("/grocy/test", response_model=TestResult)
async def test_grocy(
    user: User = Depends(current_user), http: httpx.AsyncClient = Depends(get_http)
):
    """Checks the signed-in user's stored key against Grocy."""
    client = grocy_for(user, http)
    try:
        info = await client.system_info()
        who = await client.current_user()
    except GrocyError as exc:
        if exc.status == 401:
            raise  # the key is dead: that is a sign-out, not a test result
        return TestResult(ok=False, message=exc.message)
    version = (info.get("grocy_version") or {}).get("Version", "?")
    name = who.get("display_name") or who.get("username") or "unknown user"
    return TestResult(ok=True, message=f"Connected to Grocy {version} as {name}")
