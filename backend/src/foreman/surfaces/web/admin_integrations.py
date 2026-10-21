"""Routes `/api/admin/integrations` : jetons des connecteurs et clé du LLM (org_admin SEUL).

Le jeton est en écriture seule : il entre par `PUT .../credentials`, part chiffré dans le magasin
de secrets et n'en ressort jamais (ni réponse, ni journal, ni audit, ni message d'erreur). Le corps
de requête n'est jamais journalisé. Chaque changement écrit son audit dans la transaction de
`ConnectorStore`, sans le jeton. Les routes sont montées sur le routeur d'`admin_api` : mêmes
dépendances (session, CSRF, `Origin`), mêmes erreurs opaques.
"""

import logging
from collections.abc import Awaitable, Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import SecretStr

from foreman.bootstrap.configure import App
from foreman.bootstrap.llm import chosen_model, declared_models, probe_llm
from foreman.core.accounts import AdminScope
from foreman.core.catalog import ConnectorDefinition
from foreman.core.connector_state import ConnectorState, ConnectorStatus, ConnectorStore
from foreman.core.gateway.errors import CallFailed, ProbeDenied
from foreman.core.gateway.port import RightVerdict
from foreman.core.gateway.probe import ProbeLimiter
from foreman.core.identity import Principal
from foreman.core.llm import (
    LLM_KEY_ID,
    LLM_KEY_KIND,
    LLM_MODEL_ID,
    LLM_MODEL_KIND,
    LlmNotConfigured,
)
from foreman.core.secrets import SecretError
from foreman.core.store import StoreError
from foreman.surfaces.web.errors import ApiError
from foreman.surfaces.web.schemas import (
    IntegrationTestResult,
    IntegrationView,
    LlmView,
    ModelOption,
    RightView,
    SetCredentialRequest,
    SetModelRequest,
    TokenView,
)

log = logging.getLogger(__name__)

LLM = "anthropic"
LLM_TOKEN = "api_key"  # noqa: S105 - nom du jeton, pas une valeur
LLM_DECLARED = {LLM_TOKEN: ["models.retrieve"]}
CONNECTOR_TOKEN_KIND = "connector_token"  # noqa: S105 - type de secret, pas une valeur
_ABSENT = ConnectorState("incomplete", (), None)


def _secret_id(connector: str, token: str) -> str:
    return LLM_KEY_ID if connector == LLM else f"connector.{connector}.{token}"


def _kind(connector: str) -> str:
    return LLM_KEY_KIND if connector == LLM else CONNECTOR_TOKEN_KIND


@contextmanager
def _storage() -> Iterator[None]:
    """Panne de stockage ou de chiffrement : journal sans détail, erreur opaque."""
    try:
        yield
    except (StoreError, SecretError) as exc:
        log.warning("intégrations : stockage en échec (%s)", type(exc).__name__)
        raise ApiError(500, "internal_error") from None


def add_integration_routes(
    router: APIRouter,
    app: App,
    *,
    current_principal: Callable[..., Awaitable[Principal]],
    admin_scope: Callable[..., Awaitable[AdminScope]],
    org_only: Callable[[AdminScope], None],
    refusals: Callable[[], AbstractContextManager[None]],
) -> None:
    """Dépendances d'`admin_api` : session + CSRF, puis périmètre d'administration."""
    Caller = Annotated[Principal, Depends(current_principal)]
    Scope = Annotated[AdminScope, Depends(admin_scope)]
    limiter = ProbeLimiter()  # 10 par minute et par acteur, séparément pour `set` et `test`

    def store() -> ConnectorStore:
        if app.connectors is None:
            raise ApiError(404, "not_found")
        return app.connectors

    def definitions() -> dict[str, ConnectorDefinition]:
        return dict(app.catalog.connectors) if app.catalog is not None else {}

    def known(connector: str) -> None:
        """Inconnu ou « bientôt disponible » : 404 opaque (rien n'est configurable par l'API)."""
        if connector != LLM and (
            connector not in definitions() or definitions()[connector].availability != "available"
        ):
            raise ApiError(404, "not_found")

    def declared(connector: str) -> dict[str, list[str]]:
        if connector == LLM:
            return LLM_DECLARED
        return {k: list(v.scopes) for k, v in definitions()[connector].tokens.items()}

    def throttle(kind: Literal["set", "test"], actor: Principal) -> None:
        if not limiter.allow(f"{kind}:{actor.user_id}"):
            raise ApiError(429, "too_many_requests")

    def rights_of(state: ConnectorState) -> list[RightView]:
        return [RightView(token=r.token, right=r.right, verdict=r.verdict) for r in state.rights]

    async def view(connector: str, state: ConnectorState | None) -> IntegrationView:
        state = state or _ABSENT
        tokens: list[TokenView] = []
        for name, scopes in declared(connector).items():
            boundary = None if connector == LLM else definitions()[connector].tokens[name].boundary
            tokens.append(
                TokenView(
                    name=name,
                    scopes=scopes,
                    boundary=boundary,
                    configured=await app.secrets.exists(_secret_id(connector, name)),
                )
            )
        llm = None
        if connector == LLM:
            chosen = await chosen_model(app)
            models = [
                ModelOption(
                    id=m.id,
                    label=m.label,
                    input_usd=float(m.input_usd),
                    output_usd=float(m.output_usd),
                    cache_read_usd=float(m.cache_read_usd),
                    cache_write_usd=float(m.cache_write_usd),
                )
                for m in declared_models()
            ]
            llm = LlmView(models=models, model=chosen)
        return IntegrationView(
            connector=connector,
            kind="llm" if connector == LLM else "connector",
            status="unprobed" if state is _ABSENT else state.status,
            configured=all(t.configured for t in tokens),
            availability="available" if connector == LLM else definitions()[connector].availability,
            tokens=tokens,
            rights=rights_of(state),
            last_probe_at=state.last_probe_at,
            llm=llm,
        )

    @router.get("/integrations", response_model=list[IntegrationView], tags=["integrations"])
    async def list_integrations(scope: Scope) -> list[IntegrationView]:
        org_only(scope)
        with refusals(), _storage():
            states = await store().states()
            return [await view(c, states.get(c)) for c in [LLM, *sorted(definitions())]]

    @router.put("/integrations/{connector}/credentials", status_code=204, tags=["integrations"])
    async def set_credentials(
        connector: str,
        body: SetCredentialRequest,
        actor: Caller,
        scope: Scope,
    ) -> Response:
        """Jeton en écriture seule. Remet le statut à `incomplete` : relancer la sonde."""
        org_only(scope)
        known(connector)
        names = list(declared(connector))
        name = body.name or (names[0] if len(names) == 1 else None)
        value = body.token.get_secret_value()
        if name not in names or value != value.strip() or any(c.isspace() for c in value):
            raise ApiError(422, "invalid_request")
        throttle("set", actor)
        secret_id = _secret_id(connector, name)
        with refusals(), _storage():
            await app.secrets.put(
                secret_id, _kind(connector), SecretStr(value), created_by=str(actor.user_id)
            )
            try:
                await store().save_change(
                    connector,
                    declared(connector),
                    "credential.set",
                    {name: secret_id},
                    actor.user_id,
                )
            except StoreError:
                await app.secrets.delete(secret_id)  # pas de jeton actif sans trace d'audit
                raise
        return Response(status_code=204)

    @router.delete("/integrations/{connector}/credentials", status_code=204, tags=["integrations"])
    async def revoke_credentials(
        connector: str,
        actor: Caller,
        scope: Scope,
    ) -> Response:
        org_only(scope)
        known(connector)
        names = list(declared(connector))
        with refusals(), _storage():
            for name in names:
                await app.secrets.delete(_secret_id(connector, name))
            await store().save_change(
                connector,
                declared(connector),
                "credential.revoke",
                dict.fromkeys(names),
                actor.user_id,
            )
        return Response(status_code=204)

    @router.put("/integrations/anthropic/model", status_code=204, tags=["integrations"])
    async def set_model(
        body: SetModelRequest,
        actor: Caller,
        scope: Scope,
    ) -> Response:
        """Le modèle doit figurer dans la liste déclarée ; sinon 422 opaque."""
        org_only(scope)
        if body.model not in {m.id for m in declared_models()}:
            raise ApiError(422, "invalid_request")
        with refusals(), _storage():
            await app.secrets.put(
                LLM_MODEL_ID, LLM_MODEL_KIND, SecretStr(body.model), created_by=str(actor.user_id)
            )
            await store().save_change(LLM, LLM_DECLARED, "model.set", {}, actor.user_id)
        return Response(status_code=204)

    @router.post(
        "/integrations/{connector}/test",
        response_model=IntegrationTestResult,
        tags=["integrations"],
    )
    async def test_connector(
        connector: str,
        actor: Caller,
        scope: Scope,
    ) -> IntegrationTestResult:
        """Lance les sondes déclarées (lecture seule). Un échec de sonde rend `failed`, pas 5xx."""
        org_only(scope)
        known(connector)
        throttle("test", actor)
        rights: tuple[RightVerdict, ...] = ()
        status: Literal["ok", "incomplete", "failed"]
        with refusals(), _storage():
            if connector == LLM:
                try:
                    ok = await probe_llm(app)
                except LlmNotConfigured:
                    raise ApiError(422, "invalid_request") from None
                rights = (RightVerdict(LLM_TOKEN, "models.retrieve", "ok" if ok else "missing"),)
                status = "ok" if ok else "incomplete"
                saved: ConnectorStatus = "ok" if ok else "incomplete"
                await store().save_probe(LLM, LLM_DECLARED, saved, rights, actor.user_id)
            else:
                if app.gateway is None:
                    raise ApiError(404, "not_found")
                try:
                    report = await app.gateway.probe(connector, actor.user_id)
                except ProbeDenied as denied:
                    raise _denied(denied.code) from None
                except CallFailed:
                    return IntegrationTestResult(connector=connector, status="failed", rights=[])
                rights, status = (
                    report.rights,
                    "ok" if report.status == "complete" else "incomplete",
                )
        return IntegrationTestResult(
            connector=connector,
            status=status,
            rights=[RightView(token=r.token, right=r.right, verdict=r.verdict) for r in rights],
        )


def _denied(code: str) -> ApiError:
    return {
        "rate_limited": ApiError(429, "too_many_requests"),
        "forbidden": ApiError(403, "forbidden"),
        "unknown_connector": ApiError(404, "not_found"),
    }.get(code, ApiError(501, "not_implemented"))
