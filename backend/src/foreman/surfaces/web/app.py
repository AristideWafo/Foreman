from fastapi import FastAPI

from foreman.bootstrap.configure import Profile, configure


def create_app() -> FastAPI:
    app_state = configure(Profile.WEB)
    api = FastAPI(title="Foreman")

    @api.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "profile": app_state.profile.value}

    return api
