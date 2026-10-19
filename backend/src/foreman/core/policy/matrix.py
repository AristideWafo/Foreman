"""Évaluation de la matrice de politique : fonction pure, sans entrée-sortie ni horloge.

La matrice (déjà validée par le chargeur du catalogue) décide ; la gateway applique. Le défaut est
le refus : sans règle qui s'applique, l'appel est refusé. Les exigences (`requires`) d'une règle
`allow_if` sont vérifiées par l'appelant, qui connaît l'état des approbations.
"""

from dataclasses import dataclass
from typing import Literal

from foreman.core.catalog import PolicyMatrix, Purpose, Reversibility, ToolClass
from foreman.core.events import Requirement

DenyReason = Literal["unknown_environment", "role_not_allowed", "level_too_low", "no_rule"]


@dataclass(frozen=True, slots=True)
class PolicyRequest:
    tool_class: ToolClass
    environment: str
    reversibility: Reversibility  # la réversibilité EFFECTIVE de l'appel (playbook résolu)
    role: str
    level: int  # niveau d'autonomie effectif : voir `effective_level`
    purpose: Purpose | None = None


@dataclass(frozen=True, slots=True)
class Allow:
    rule_id: str


@dataclass(frozen=True, slots=True)
class AllowIf:
    rule_id: str
    requires: tuple[Requirement, ...]


@dataclass(frozen=True, slots=True)
class Deny:
    reason: DenyReason
    rule_id: str | None = None  # la règle qui s'appliquait presque, utile à l'audit


Verdict = Allow | AllowIf | Deny


def effective_level(matrix: PolicyMatrix, environment: str, requested: int) -> int:
    """Niveau demandé, plafonné par l'environnement (0 si l'environnement est inconnu).

    `autonomy.org_ceiling` n'intervient pas ici : le staging peut dépasser le plafond de
    l'organisation par son propre `max_level` (voir la matrice).
    """
    config = matrix.autonomy.environments.get(environment)
    return 0 if config is None else min(requested, config.max_level)


def requirements(
    matrix: PolicyMatrix, verdict: Verdict, environment: str
) -> tuple[Requirement, ...]:
    """Exigences d'un verdict : règle, plus `admin_approved` si l'environnement l'exige.

    `Allow` et `Deny` n'en ont aucune. `never_autonomous` n'intervient pas ici : la règle porte
    déjà `admin_approved` (contrainte de validation du catalogue).
    """
    if not isinstance(verdict, AllowIf):
        return ()
    config = matrix.autonomy.environments.get(environment)
    if config is not None and config.admin_approval_required:
        return tuple(dict.fromkeys((*verdict.requires, "admin_approved")))
    return verdict.requires


def evaluate(matrix: PolicyMatrix, request: PolicyRequest) -> Verdict:
    """Première règle qui s'applique, dans l'ordre du fichier ; sinon refus."""
    if request.environment not in matrix.autonomy.environments:
        return Deny("unknown_environment")
    near_miss: Deny | None = None
    for rule in matrix.rules:
        match = rule.match
        if (
            match.tool_class != request.tool_class
            or (match.env is not None and request.environment not in match.env)
            or (
                match.reversibility is not None and request.reversibility not in match.reversibility
            )
            or (match.purpose is not None and request.purpose not in match.purpose)
        ):
            continue
        if rule.roles is not None and request.role not in rule.roles:
            near_miss = near_miss or Deny("role_not_allowed", rule.id)
            continue
        if rule.min_level is not None and request.level < rule.min_level:
            near_miss = near_miss or Deny("level_too_low", rule.id)
            continue
        if rule.decision == "allow":
            return Allow(rule.id)
        return AllowIf(rule.id, tuple(rule.requires))
    return near_miss or Deny("no_rule")
