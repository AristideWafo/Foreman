import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from foreman.bootstrap.configure import Profile, configure
from foreman.config.env import ENV_STATIC_DIR
from foreman.surfaces.web.api import router
from foreman.surfaces.web.errors import install_error_handlers
from foreman.surfaces.web.openapi import install_event_schema


def create_app() -> FastAPI:
    app_state = configure(Profile.WEB)
    api = FastAPI(title="Foreman")
    install_error_handlers(api)
    api.include_router(router)
    install_event_schema(api)

    @api.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "profile": app_state.profile.value}

    # Monté en dernier : les routes de l'API restent prioritaires sur la SPA.
    static_dir = os.environ.get(ENV_STATIC_DIR)
    if static_dir and Path(static_dir).is_dir():
        api.mount("/", StaticFiles(directory=static_dir, html=True), name="spa")
    return api
