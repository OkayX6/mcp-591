"""The swipe web app: JSON API under /api, the PWA from /static at /.

Run: `uvicorn --factory swipe591.app:from_env` (settings from the environment, see config.py).
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Literal

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from mcp_591.constants import PATTERNS, REGIONS, RENT_KINDS, SECTIONS_BY_REGION, SHAPES
from swipe591 import auth
from swipe591.directus import DirectusError
from swipe591.poller import query_for
from swipe591.store import DISLIKED, LIKED, Store

COOKIE = "swipe591_session"
STATIC = Path(__file__).parent / "static"


class Login(BaseModel):
    password: str


class Verdict(BaseModel):
    verdict: Literal["like", "superlike", "dislike"] | None
    note: str | None = None


class Search(BaseModel):
    name: str = Field(min_length=1)
    active: bool = True
    region: str
    section: str | None = None
    kind: str | None = None
    shape: str | None = None
    pattern: str | None = None
    price_min: int | None = Field(default=None, ge=0)
    price_max: int | None = Field(default=None, ge=0)
    keywords: str | None = None


def create_app(
    store: Store,
    *,
    password: str,
    session_secret: str,
    cookie_secure: bool = True,
    clock: Callable[[], float] = auth.now,
) -> FastAPI:
    app = FastAPI(title="591 Swipe", docs_url=None, redoc_url=None)
    limiter = auth.LoginRateLimiter()

    @app.exception_handler(DirectusError)
    @app.exception_handler(httpx.HTTPError)
    def storage_down(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"detail": f"Directus unavailable: {exc}"}, status_code=502)

    def signed_in(request: Request) -> None:
        if not auth.verify_session(session_secret, request.cookies.get(COOKIE), clock()):
            raise HTTPException(401, "Not signed in")

    def validated(search: Search) -> dict:
        data = search.model_dump()
        try:
            query_for(data)
        except ValueError as e:
            raise HTTPException(400, str(e))
        if data["price_min"] and data["price_max"] and data["price_min"] > data["price_max"]:
            raise HTTPException(400, "price_min is above price_max")
        return data

    @app.post("/api/login")
    def login(body: Login, response: Response) -> dict:
        if not limiter.allow(clock()):
            raise HTTPException(429, "Too many attempts, wait a minute")
        if not auth.password_matches(password, body.password):
            raise HTTPException(401, "Wrong password")
        response.set_cookie(
            COOKIE,
            auth.sign_session(session_secret, clock()),
            max_age=auth.SESSION_DAYS * 86400,
            httponly=True,
            secure=cookie_secure,
            samesite="strict",
        )
        return {"ok": True}

    @app.post("/api/logout")
    def logout(response: Response) -> dict:
        response.delete_cookie(COOKIE)
        return {"ok": True}

    api = Depends(signed_in)

    @app.get("/api/me", dependencies=[api])
    def me() -> dict:
        return {"ok": True}

    @app.get("/api/deck", dependencies=[api])
    def deck(limit: int = 20) -> list[dict]:
        return store.deck(min(max(limit, 1), 100))

    @app.get("/api/listings", dependencies=[api])
    def listings(verdict: Literal["liked", "disliked"]) -> list[dict]:
        return store.listings_with_verdict(LIKED if verdict == "liked" else DISLIKED)

    @app.get("/api/listings/{post_id}", dependencies=[api])
    def listing(post_id: int) -> dict:
        found = store.get_listing(post_id)
        if found is None:
            raise HTTPException(404, "No such listing")
        return found

    @app.put("/api/listings/{post_id}/verdict", dependencies=[api])
    def set_verdict(post_id: int, body: Verdict) -> dict:
        decided_at = datetime.fromtimestamp(clock(), UTC).isoformat() if body.verdict else None
        changes = {"verdict": body.verdict, "decided_at": decided_at}
        if body.note is not None:
            changes["note"] = body.note
        updated = store.set_verdict(post_id, changes)
        if updated is None:
            raise HTTPException(404, "No such listing")
        return updated

    @app.get("/api/searches", dependencies=[api])
    def searches() -> list[dict]:
        return store.list_searches()

    @app.post("/api/searches", dependencies=[api], status_code=201)
    def create_search(body: Search) -> dict:
        return store.create_search(validated(body))

    @app.put("/api/searches/{search_id}", dependencies=[api])
    def update_search(search_id: int, body: Search) -> dict:
        return store.update_search(search_id, validated(body))

    @app.delete("/api/searches/{search_id}", dependencies=[api], status_code=204)
    def delete_search(search_id: int) -> None:
        store.delete_search(search_id)

    @app.get("/api/options")
    def options() -> dict:
        """The choices of the search form (591's own Chinese names)."""
        return {
            "regions": [
                {"name": name, "sections": list(SECTIONS_BY_REGION.get(rid, {}).values())}
                for rid, name in REGIONS.items()
            ],
            "kinds": list(RENT_KINDS.values()),
            "shapes": list(SHAPES.values()),
            "patterns": list(PATTERNS.values()),
        }

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    app.mount("/", StaticFiles(directory=STATIC), name="static")
    return app


def from_env() -> FastAPI:
    from swipe591.config import Settings
    from swipe591.directus import DirectusStore

    settings = Settings.from_env()
    return create_app(
        DirectusStore(settings.directus_url, settings.directus_token),
        password=settings.password,
        session_secret=settings.session_secret,
        cookie_secure=settings.cookie_secure,
    )

