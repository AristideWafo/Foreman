"""Client HTTP GitLab : base fixe gitlab.com, jeton relu à CHAQUE appel dans le magasin de secrets.

Le jeton ne quitte jamais ce module : ni exception, ni journal, ni URL. Les erreurs sont à message
fixe et code fermé (`AdapterDiagnostic.code`) ; le corps d'une réponse d'erreur n'est jamais repris.
Aucune redirection suivie (un jeton ne suit pas une redirection), délai 10 s, corps borné à 256 Kio.
"""

import json
from collections.abc import Mapping, Sequence
from typing import Final

import httpx2
from pydantic import JsonValue

from foreman.core.connector_state import CONNECTOR_TOKEN_KIND, connector_secret_id
from foreman.core.ports import AdapterDiagnostic, AdapterError, PermissionMissing
from foreman.core.secrets import SecretError, SecretStore

BASE_URL: Final = "https://gitlab.com/api/v4"
TIMEOUT_S: Final = 10.0
MAX_BODY_BYTES: Final = 256 * 1024
TOKEN_NAMES: Final = ("read", "write")

# Code fermé -> message fixe.
_MESSAGES: Final = {
    "not_found": "gitlab : ressource introuvable",
    "rate_limited": "gitlab : trop de requêtes",
    "gitlab_error": "gitlab : erreur du service",
    "bad_response": "gitlab : réponse invalide",
    "unavailable": "gitlab : service injoignable",
    "storage": "gitlab : jeton illisible",
    "unsupported": "gitlab : outil non fourni par ce connecteur",
}


def gitlab_error(code: str) -> AdapterError:
    return AdapterError(_MESSAGES[code], AdapterDiagnostic(code=code))


class GitLabClient:
    def __init__(
        self, secrets: SecretStore, *, transport: httpx2.AsyncBaseTransport | None = None
    ) -> None:
        self._secrets = secrets
        self._transport = transport

    async def get(
        self,
        path: str,
        params: Mapping[str, str | int] | None = None,
        *,
        tokens: Sequence[str] = TOKEN_NAMES,
    ) -> tuple[JsonValue, int | None]:
        """GET JSON avec le premier jeton présent parmi `tokens` ; renvoie (corps, suite)."""
        token = await self._token(tokens)
        body = bytearray()
        try:
            async with (
                httpx2.AsyncClient(
                    transport=self._transport, follow_redirects=False, timeout=TIMEOUT_S
                ) as http,
                http.stream(
                    "GET",
                    BASE_URL + path,
                    params=dict(params or {}),
                    headers={"PRIVATE-TOKEN": token, "Accept": "application/json"},
                ) as response,
            ):
                status = response.status_code
                if status in (401, 403):
                    raise PermissionMissing("gitlab", tokens[0])
                if status == 404:
                    raise gitlab_error("not_found")
                if status == 429:
                    raise gitlab_error("rate_limited")
                if status != 200:
                    raise gitlab_error("gitlab_error")
                async for chunk in response.aiter_bytes():
                    body += chunk
                    if len(body) > MAX_BODY_BYTES:
                        raise gitlab_error("bad_response")
                next_page = response.headers.get("x-next-page", "")
        except AdapterError:  # PermissionMissing comprise
            raise
        except Exception:  # httpx2 peut citer l'URL : rien de l'exception d'origine ne remonte
            raise gitlab_error("unavailable") from None
        try:
            data: JsonValue = json.loads(bytes(body))
        except ValueError:
            raise gitlab_error("bad_response") from None
        return data, int(next_page) if next_page.isdigit() else None

    async def _token(self, names: Sequence[str]) -> str:
        for name in names:
            try:
                secret = await self._secrets.get(
                    connector_secret_id("gitlab", name), CONNECTOR_TOKEN_KIND
                )
            except SecretError:
                raise gitlab_error("storage") from None
            if secret is not None:
                return secret.get_secret_value()
        raise PermissionMissing("gitlab", names[0])
