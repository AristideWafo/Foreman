import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from foreman.bootstrap.configure import Profile, configure
from foreman.config.env import ENV_STATIC_DIR


def create_app() -> FastAPI:
    app_state = configure(Profile.WEB)
    api = FastAPI(title="Foreman")

    @api.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "profile": app_state.profile.value}

    # Monté en dernier : les routes de l'API restent prioritaires sur la SPA.
    static_dir = os.environ.get(ENV_STATIC_DIR)
    if static_dir and Path(static_dir).is_dir():
        api.mount("/", StaticFiles(directory=static_dir, html=True), name="spa")
    return api
