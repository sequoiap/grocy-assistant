import asyncio
import logging
from contextlib import asynccontextmanager, suppress

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import ConfigError, get_config
from .db import init_db, session_scope
from .errors import GROCY_UNREACHABLE, ApiError, account_invalid
from .grocy.client import GrocyError, GrocyUnreachable, grocy_timeout, shared_http_client
from .routers import auth, grocy_meta, settings, stock, trips
from .security import SESSION_COOKIE
from .services.accounts import check_active_keys, session_user, sign_out_everywhere
from .services.receipts import fail_interrupted

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
# One line per request to Grocy is too much now that keys are re-checked all day.
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger(__name__)


async def _watch_keys(app: FastAPI, every: float) -> None:
    """Sign people out soon after Grocy stops accepting their account."""
    while True:
        await asyncio.sleep(every)
        try:
            await check_active_keys(app.state.http)
        except Exception:
            log.exception("Re-checking Grocy keys failed; trying again in %ss", every)


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = get_config()
    init_db()
    fail_interrupted()
    app.state.http = shared_http_client(cfg.grocy_timeout_seconds)
    # Sign-in with a Grocy password runs on a client of its own, made per sign-in,
    # so its session cookie can never end up on the shared client (grocy/login.py).
    timeout = grocy_timeout(cfg.grocy_timeout_seconds)
    app.state.new_login_http = lambda: httpx.AsyncClient(timeout=timeout)
    watcher = None
    if cfg.key_check_seconds > 0:
        watcher = asyncio.create_task(_watch_keys(app, cfg.key_check_seconds))
    yield
    if watcher is not None:
        watcher.cancel()
        with suppress(asyncio.CancelledError):
            await watcher
    await app.state.http.aclose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Grocy Assistant",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )

    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError):
        return JSONResponse(exc.body(), status_code=exc.status)

    @app.exception_handler(GrocyError)
    async def grocy_error(request: Request, exc: GrocyError):
        """A Grocy call made for the signed-in user, with their stored key, failed."""
        if exc.status == 401:
            # The key is dead, so the Grocy account behind this session is gone (or
            # its key was revoked). The app session has nothing left to stand on.
            with session_scope() as db:
                user = session_user(db, request.cookies.get(SESSION_COOKIE))
                if user is not None:
                    sign_out_everywhere(db, user)
            response = JSONResponse(account_invalid().body(), status_code=401)
            response.delete_cookie(SESSION_COOKIE, path="/")
            return response
        if isinstance(exc, GrocyUnreachable):
            body = ApiError(
                503,
                "Grocy is unreachable right now. Your trip is saved; try again in a moment.",
                GROCY_UNREACHABLE,
            ).body()
            return JSONResponse(body, status_code=503)
        return JSONResponse({"detail": exc.message}, status_code=502)

    for router in (auth.router, settings.router, grocy_meta.router, trips.router, stock.router):
        app.include_router(router)

    @app.get("/api/health", include_in_schema=False)
    def health():
        return {"ok": True}

    static_dir = get_config().static_dir
    if (static_dir / "index.html").exists():
        if (static_dir / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            """Serve the PWA: real files as-is, everything else is a client-side route."""
            if path.startswith("api/"):
                raise HTTPException(404, "Not found")
            candidate = (static_dir / path).resolve()
            if path and candidate.is_file() and candidate.is_relative_to(static_dir.resolve()):
                headers = {}
                if path in ("sw.js", "registerSW.js", "manifest.webmanifest"):
                    headers["Cache-Control"] = "no-cache"
                return FileResponse(candidate, headers=headers)
            return FileResponse(static_dir / "index.html", headers={"Cache-Control": "no-cache"})

    return app


try:
    app = create_app()
except ConfigError as exc:
    # One readable line instead of a traceback, before the server starts listening.
    raise SystemExit(f"grocy-assistant can't start: {exc}") from None
