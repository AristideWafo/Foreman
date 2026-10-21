"""Liste des modèles autorisés (`connector.yaml`) et sonde `models.retrieve`."""

from decimal import Decimal
from pathlib import Path
from typing import Annotated

import anthropic
import httpx2
import yaml
from pydantic import BaseModel, ConfigDict, Field

from foreman.core.llm import LlmNotConfigured, LlmSettings
from foreman.core.pricing import ModelPrice
from foreman.integrations.anthropic.provider import ProviderFailed

CONNECTOR_FILE = Path(__file__).with_name("connector.yaml")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ModelEntry(_Strict):
    id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9.\-]{0,63}$")]
    label: str
    input_usd: Decimal
    output_usd: Decimal
    cache_read_usd: Decimal
    cache_write_usd: Decimal

    @property
    def price(self) -> ModelPrice:
        return ModelPrice(
            self.input_usd, self.output_usd, self.cache_read_usd, self.cache_write_usd
        )


class Connector(_Strict):
    version: Annotated[int, Field(strict=True)]
    probe: str
    models: Annotated[list[ModelEntry], Field(min_length=1)]


def load_connector(path: Path = CONNECTOR_FILE) -> Connector:
    return Connector.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def model_prices() -> dict[str, ModelPrice]:
    return {m.id: m.price for m in load_connector().models}


async def probe(settings: LlmSettings, http_client: httpx2.AsyncClient | None = None) -> bool:
    """`models.retrieve` sur le modèle choisi : vrai si la clé le voit. Aucun détail du SDK."""
    key, model = await settings.api_key(), await settings.model()
    if key is None or not model:
        raise LlmNotConfigured
    client = anthropic.AsyncAnthropic(api_key=key.get_secret_value(), http_client=http_client)
    del key
    try:
        await client.models.retrieve(model)
    except anthropic.APIError:
        raise ProviderFailed from None
    finally:
        if http_client is None:
            await client.close()
    return True
