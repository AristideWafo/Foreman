import os
from collections.abc import AsyncIterator, MutableMapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from foreman.bootstrap.configure import App, Profile, configure
from foreman.config.env import DEFAULT_VERSION, ENV_STATIC_DIR, ENV_VERSION
from foreman.surfaces.web.api import create_router
from foreman.surfaces.web.errors import install_error_handlers
from foreman.surfaces.web.openapi import install_event_schema
from foreman.surfaces.web.tasks import TaskRegistry


class SpaStaticFiles(StaticFiles):
    """Fichiers statiques avec repli sur `index.html` pour les liens profonds de la SPA.

    Pas de repli pour `/api/...` (404 JSON opaque) ni pour un fichier absent (nom avec extension).
    """

    async def get_response(self, path: str, scope: MutableMapping[str, Any]) -> Response:
        # `/api/...` n'est jamais servi par la SPA, quelle que soit la méthode (sinon 405 sur POST).
        if path == "api" or path.startswith("api/"):
            raise StarletteHTTPException(status_code=404)
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            is_file = "." in Path(path).name
            if exc.status_code != 404 or is_file:
                raise
            return await super().get_response("index.html", scope)


def create_app(app_state: App | None = None) -> FastAPI:
    """`app_state` permet d'injecter des adaptateurs (tests) ; sinon profil web."""
    state = app_state or configure(Profile.WEB)
    tasks = TaskRegistry()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await state.lifecycle.start()  # migrations puis amorçage (profil web avec base)
        try:
            yield
        finally:
            await tasks.shutdown()
            await state.lifecycle.stop()

    api = FastAPI(title="Foreman", lifespan=lifespan)
    install_error_handlers(api)
    api.include_router(create_router(state, tasks))
    install_event_schema(api)

    @api.get("/healthz")
    async def healthz() -> dict[str, str]:
        version = os.environ.get(ENV_VERSION, "")[:32] or DEFAULT_VERSION
        return {"status": "ok", "profile": state.profile.value, "version": version}

    # Monté en dernier : les routes de l'API restent prioritaires sur la SPA.
    static_dir = os.environ.get(ENV_STATIC_DIR)
    if static_dir and Path(static_dir).is_dir():
        api.mount("/", SpaStaticFiles(directory=static_dir, html=True), name="spa")
    return api
