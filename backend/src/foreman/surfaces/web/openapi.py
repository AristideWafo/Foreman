"""Publie le schéma `Event` dans `components.schemas` (types générés côté front)."""

from typing import Any

from fastapi import FastAPI
from pydantic import TypeAdapter

from foreman.core.events import Event


def install_event_schema(app: FastAPI) -> None:
    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = FastAPI.openapi(app)
        event = TypeAdapter(Event).json_schema(ref_template="#/components/schemas/{model}")
        defs = event.pop("$defs", {})
        components = schema.setdefault("components", {}).setdefault("schemas", {})
        components.update(defs)
        components["Event"] = event
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi  # type: ignore[method-assign]
