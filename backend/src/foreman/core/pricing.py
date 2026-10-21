"""Coût d'un appel modèle : jetons (`usage`) x tarif USD par million de jetons x taux fixe en EUR.

Le taux de change est DÉCLARÉ ici, fixe, volontairement : un budget en euros doit être reproductible
(pas de cours en direct). Le revoir à la main si l'écart devient significatif.
"""

from dataclasses import dataclass
from decimal import Decimal

USD_TO_EUR = Decimal("0.92")
_MILLION = Decimal(1_000_000)


@dataclass(frozen=True, slots=True)
class Usage:
    """Jetons consommés par un appel, tels que rapportés par le fournisseur."""

    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_tokens
            + self.cache_write_tokens
        )


@dataclass(frozen=True, slots=True)
class ModelPrice:
    """Tarif en USD par million de jetons."""

    input_usd: Decimal
    output_usd: Decimal
    cache_read_usd: Decimal = Decimal(0)
    cache_write_usd: Decimal = Decimal(0)


def cost_eur(usage: Usage, price: ModelPrice) -> Decimal:
    usd = (
        usage.input_tokens * price.input_usd
        + usage.output_tokens * price.output_usd
        + usage.cache_read_tokens * price.cache_read_usd
        + usage.cache_write_tokens * price.cache_write_usd
    ) / _MILLION
    return usd * USD_TO_EUR
