"""Faux DNS : lecture seule du wildcard du staging (géré en externe, jamais écrit)."""

from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import JsonValue

from foreman.core.ports import AdapterError, AdapterResult

DEFAULT_WILDCARD = "*.staging.example.org"
DEFAULT_POINTS_TO = "server-staging-1"


@dataclass(frozen=True, slots=True)
class SimulatedRecord:
    name: str
    type: str
    target: str


class SimulatedDns:
    """Seul `dns.list_records` existe : toute écriture est refusée, l'état ne change jamais."""

    def __init__(
        self, wildcard: str = DEFAULT_WILDCARD, points_to: str = DEFAULT_POINTS_TO
    ) -> None:
        self.records: tuple[SimulatedRecord, ...] = (SimulatedRecord(wildcard, "CNAME", points_to),)

    @classmethod
    def from_referentiel(cls, infra_staging: Mapping[str, JsonValue]) -> "SimulatedDns":
        """Construit le faux depuis les données du référentiel `infra-staging`."""
        dns = infra_staging.get("dns")
        if not isinstance(dns, dict):
            raise AdapterError("référentiel DNS invalide")
        wildcard, points_to = dns.get("wildcard"), dns.get("points_to")
        if not isinstance(wildcard, str) or not isinstance(points_to, str):
            raise AdapterError("référentiel DNS invalide")
        return cls(wildcard, points_to)

    async def execute(
        self, tool: str, params: Mapping[str, JsonValue], idempotency_key: str
    ) -> AdapterResult:
        if tool != "dns.list_records":
            raise AdapterError("outil non fourni par ce connecteur")
        records: list[JsonValue] = [
            {"name": r.name, "type": r.type, "target": r.target} for r in self.records
        ]
        return AdapterResult(
            output={"records": records}, logs=[f"{len(records)} enregistrement(s) listé(s)"]
        )
