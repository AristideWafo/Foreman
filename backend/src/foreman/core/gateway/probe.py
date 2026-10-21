"""Sondes de droits d'un connecteur : `Gateway.probe`.

Seules les sondes DÉCLARÉES dans `connector.yaml` s'exécutent, en lecture seule (GET ou HEAD,
vérifié au chargement du catalogue). La gateway ne voit jamais un jeton : l'adaptateur le détient.
Le statut est persisté (`ConnectorStore`, table `connectors`) et relu au premier usage : un
connecteur `incomplete` le reste après un redémarrage. Sans store (tests, CLI), il reste en mémoire
du processus. Tant qu'un connecteur n'est pas sondé, ses outils restent permis.
shortcut: l'état est relu une fois par processus ; plusieurs conteneurs ne se voient qu'au
redémarrage, à revoir si on passe à plusieurs instances.
"""

import asyncio
import logging
import time
from collections import deque
from collections.abc import Callable, Mapping
from typing import Final, Literal, cast
from uuid import UUID

from foreman.core.catalog import Catalog, ConnectorDefinition, ToolDefinition
from foreman.core.connector_state import ConnectorStatus, ConnectorStore
from foreman.core.gateway.errors import CallFailed, FailureCode, ProbeDenialCode, ProbeDenied
from foreman.core.gateway.port import ProbeReport, RightVerdict
from foreman.core.gateway.redact import mask_text
from foreman.core.ports import ConnectorProber, MemberStore, PermissionMissing, ProbeOutcome
from foreman.core.store import MAX_AUDIT_DURATION_MS, AuditEntry, AuditLog

log = logging.getLogger(__name__)

PROBE_TIMEOUT_S: Final = 15.0
WINDOW_SECONDS: Final = 60.0
MAX_PROBES_PER_WINDOW: Final = 10
MAX_KEYS: Final = 1_000
MAX_NAME_AUDIT: Final = 100


class ProbeLimiter:
    """Au plus `MAX_PROBES_PER_WINDOW` sondes par acteur et par fenêtre (même forme que
    `FailureLimiter`). shortcut: par processus, à remplacer si plusieurs conteneurs."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}

    def allow(self, key: str) -> bool:
        """Compte la tentative ; faux (et rien n'est compté de plus) si la limite est atteinte."""
        now = self._clock()
        if key not in self._hits and len(self._hits) >= MAX_KEYS:
            self._hits.clear()  # saturée : la limite se réarme plutôt que la mémoire croître
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= now - WINDOW_SECONDS:
            hits.popleft()
        if len(hits) >= MAX_PROBES_PER_WINDOW:
            return False
        hits.append(now)
        return True


class ConnectorProbes:
    def __init__(
        self,
        *,
        catalog: Catalog,
        audit: AuditLog,
        members: MemberStore,
        probers: Mapping[str, ConnectorProber],
        clock: Callable[[], float] = time.monotonic,
        store: ConnectorStore | None = None,
    ) -> None:
        self._store = store
        self._loaded = store is None
        self._catalog = catalog
        self._audit = audit
        self._members = members
        self._probers = probers
        self._clock = clock
        self._limiter = ProbeLimiter(clock)
        self._missing: dict[str, frozenset[str]] = {}  # connecteur -> jetons dont un droit manque

    async def _load(self) -> None:
        if self._loaded or self._store is None:
            return
        for name, state in (await self._store.states()).items():
            self._missing.setdefault(
                name, frozenset(r.token for r in state.rights if r.verdict == "missing")
            )
        self._loaded = True

    async def blocks(self, tool: ToolDefinition) -> bool:
        """Vrai si un jeton requis par l'outil a un droit manquant (connecteur `incomplete`)."""
        await self._load()
        definition = self._catalog.connectors.get(tool.connector)
        if definition is None:
            return False
        needed = definition.tools_enabled_when.get(tool.tool, [])
        return bool(self._missing.get(tool.connector, frozenset()).intersection(needed))

    async def probe(self, connector: str, actor: UUID) -> ProbeReport:
        started = self._clock()
        name = f"{mask_text(connector)[:MAX_NAME_AUDIT]}.probe"
        denial: ProbeDenialCode | None = None
        failure: FailureCode = "internal_error"
        try:
            denial = await self._precheck(connector, actor)
            if denial is None:
                definition = self._catalog.connectors[connector]
                report = await self._run(definition)
                await self._write(actor, name, started, "executed", _report_json(report))
                if self._store is not None:
                    declared = {k: list(v.scopes) for k, v in definition.tokens.items()}
                    saved: ConnectorStatus = "ok" if report.status == "complete" else "incomplete"
                    await self._store.save_probe(connector, declared, saved, report.rights, actor)
                self._missing[connector] = frozenset(
                    r.token for r in report.rights if r.verdict == "missing"
                )
                return report
        except CallFailed as failed:
            failure = cast(FailureCode, failed.code)
        except Exception as exc:
            log.warning("sonde : exception inattendue (%s)", type(exc).__name__)
        # Levées HORS des `except` : aucune exception d'origine ne reste attachée.
        if denial is not None:
            await self._write(actor, name, started, "denied", {"code": denial}, swallow=True)
            raise ProbeDenied(denial)
        await self._write(actor, name, started, "error", {"code": failure}, swallow=True)
        raise CallFailed(failure)

    async def _precheck(self, connector: str, actor: UUID) -> ProbeDenialCode | None:
        if not self._limiter.allow(str(actor)):
            return "rate_limited"
        # `teams_of` est `None` pour un org_admin actif, relu à chaque appel (jamais mis en cache).
        if await self._members.teams_of(actor) is not None:
            return "forbidden"
        if connector not in self._catalog.connectors:
            return "unknown_connector"
        return None if connector in self._probers else "probe_unavailable"

    async def _run(self, definition: ConnectorDefinition) -> ProbeReport:
        prober = self._probers[definition.connector]
        rights: list[RightVerdict] = []
        seen: dict[str, set[str]] = {token: set() for token in definition.tokens}
        for probe in definition.probes:
            outcome = await _run_one(prober, probe.token, probe.name, probe.call)
            seen[probe.token] |= outcome.scopes
            rights.append(RightVerdict(probe.token, probe.name, "ok" if outcome.ok else "missing"))
        for token, declaration in definition.tokens.items():
            rights.extend(
                RightVerdict(token, scope, "excess")
                for scope in sorted(seen[token] - set(declaration.scopes))
            )
        incomplete = any(r.verdict == "missing" for r in rights)
        status: Literal["complete", "incomplete"] = "incomplete" if incomplete else "complete"
        return ProbeReport(definition.connector, status, tuple(rights))

    async def _write(
        self,
        actor: UUID,
        tool: str,
        started: float,
        decision: str,
        result: dict[str, object],
        *,
        swallow: bool = False,
    ) -> None:
        elapsed = int((self._clock() - started) * 1000)
        entry = AuditEntry(
            actor_kind="user",
            actor=str(actor),
            tool=tool,
            tool_class="read",
            decision=decision,
            result_redacted=result,
            duration_ms=min(max(elapsed, 0), MAX_AUDIT_DURATION_MS),
        )
        try:
            await self._audit.append(entry)
        except Exception as exc:
            log.warning("sonde : audit non écrit (%s)", type(exc).__name__)
            if not swallow:  # une sonde non auditée n'a pas eu lieu
                raise CallFailed("storage_unavailable") from None


async def _run_one(prober: ConnectorProber, token: str, name: str, call: str) -> ProbeOutcome:
    code: FailureCode
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_S):
            outcome = await prober.probe(token, name, call)
    except PermissionMissing:
        return ProbeOutcome(ok=False)
    except TimeoutError:
        code = "timeout"
    except Exception as exc:
        log.warning("sonde : défaut d'adaptateur (%s)", type(exc).__name__)
        code = "adapter_error"
    else:
        if isinstance(outcome, ProbeOutcome) and isinstance(outcome.ok, bool):
            scopes = frozenset(s for s in outcome.scopes if isinstance(s, str))
            return ProbeOutcome(outcome.ok, scopes)
        code = "invalid_output"
    raise CallFailed(code)


def _report_json(report: ProbeReport) -> dict[str, object]:
    return {
        "status": report.status,
        "rights": [
            {"token": r.token, "right": r.right, "verdict": r.verdict} for r in report.rights
        ],
    }
