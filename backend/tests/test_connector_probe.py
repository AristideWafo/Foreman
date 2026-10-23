"""Sondes de droits d'un connecteur (`Gateway.probe`) : rôle, statut `incomplete`, lecture seule."""

from dataclasses import replace
from uuid import UUID, uuid4

import pytest

from foreman.core.catalog import CatalogError, parse_connector
from foreman.core.gateway.errors import CallDenied, ProbeDenied
from foreman.core.gateway.pipeline import ToolGateway
from foreman.core.identity import Member
from foreman.core.ports import ProbeOutcome
from foreman.core.store import DEV_USER_ID
from foreman.infra.in_memory import InMemoryMemberStore
from test_gateway import ONE_GROUP, World, call_for, make_world, start

ADMIN_ID = uuid4()
SECRET_TOKEN = "glpat-" + "B" * 24


class NamedProber:
    """Faux connecteur : enregistre chaque sonde ; un droit listé dans `missing` échoue."""

    def __init__(self, missing: frozenset[str] = frozenset(), excess: frozenset[str] = frozenset()):
        self.token = SECRET_TOKEN  # détenu par l'adaptateur, jamais transmis à la gateway
        self.missing, self.excess = missing, excess
        self.calls: list[tuple[str, str, str]] = []
        self.writes = 0

    async def probe(self, token: str, name: str, call: str) -> ProbeOutcome:
        self.calls.append((token, name, call))
        if not call.startswith(("GET ", "HEAD ")):
            self.writes += 1
        return ProbeOutcome(ok=name not in self.missing, scopes=self.excess, observed={"usable": 1})


def world_with(prober: NamedProber) -> World:
    members = InMemoryMemberStore(
        [Member("dev", "developer", DEV_USER_ID), Member("root", "org_admin", ADMIN_ID)]
    )
    world = make_world(members=members)
    gateway = ToolGateway(
        catalog=world.catalog,
        stores=world.stores,
        adapters={
            "gitlab": world.gitlab,
            "server": world.server,
            "dns": world.gateway._adapters["dns"],
        },
        members=members,
        probers={"gitlab": prober},
    )
    return replace(world, gateway=gateway)


def audit_rows(world: World, actor: UUID) -> list[object]:
    return [e for e in world.state.audit if e.tool == "gitlab.probe" and e.actor == str(actor)]


async def test_only_an_org_admin_can_probe_and_the_refusal_is_audited() -> None:
    prober = NamedProber()
    world = world_with(prober)
    with pytest.raises(ProbeDenied) as denied:
        await world.gateway.probe("gitlab", DEV_USER_ID)
    assert denied.value.code == "forbidden"
    assert prober.calls == []
    assert [e.decision for e in audit_rows(world, DEV_USER_ID)] == ["denied"]  # type: ignore[attr-defined]


async def test_a_missing_right_makes_the_connector_incomplete_and_refuses_its_tool() -> None:
    prober = NamedProber(missing=frozenset({"jeton_ecriture_valide"}))
    world = world_with(prober)
    started = await start(world, ONE_GROUP)
    report = await world.gateway.probe("gitlab", ADMIN_ID)
    assert report.status == "incomplete"
    verdicts = {r.right: r.verdict for r in report.rights}
    assert verdicts == {"lire_groupes": "ok", "jeton_ecriture_valide": "missing"}
    with pytest.raises(CallDenied) as denied:
        await world.gateway.call(call_for(started))  # gitlab.create_group dépend du jeton write
    assert denied.value.code == "permission_missing"
    assert world.gitlab.calls == 0  # l'outil n'a pas atteint l'adaptateur


async def test_a_probe_never_writes_and_its_audit_row_holds_no_token() -> None:
    prober = NamedProber(excess=frozenset({"api"}))
    world = world_with(prober)
    report = await world.gateway.probe("gitlab", ADMIN_ID)
    assert report.status == "complete"  # un scope en trop est signalé, il ne bloque pas
    assert {r.right for r in report.rights if r.verdict == "excess"} == {"api"}
    assert prober.writes == 0 and len(prober.calls) == 2  # seulement les sondes déclarées, en GET
    (row,) = audit_rows(world, ADMIN_ID)
    assert (row.decision, row.tool_class) == ("executed", "read")  # type: ignore[attr-defined]
    assert SECRET_TOKEN not in repr(row)
    with pytest.raises(
        CatalogError
    ):  # une sonde d'écriture ne passe pas le chargement du catalogue
        parse_connector(
            b"connector: x\nversion: 1\ntokens: {w: {scopes: [s]}}\n"
            b"probes: [{name: p, token: w, call: 'POST /groups'}]\n",
            "x/connector.yaml",
        )
