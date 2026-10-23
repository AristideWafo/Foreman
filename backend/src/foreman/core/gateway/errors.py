"""Erreurs typées de la gateway. Le message est FIXE : aucun détail (paramètre, chemin, exception
d'adaptateur) ne sort. Le `code` est un identifiant stable, choisi dans une liste fermée."""

from typing import Literal

from foreman.core.events import ToolDiagnostic

DenialCode = Literal[
    "unknown_context",  # exécution, plan ou étape introuvable pour ce projet, exécution terminée
    "unknown_tool",
    "invalid_params",  # le schéma de l'outil refuse les paramètres
    "policy_denied",  # la matrice refuse (ou une exigence autre que l'admin n'est pas remplie)
    "approval_required",  # la règle exige `admin_approved` et aucun admin n'a approuvé ce plan
    "plan_not_approved",
    "plan_hash_mismatch",
    "call_differs_from_step",  # l'appel n'est pas celui de l'étape `seq` du plan approuvé
    "environment_mismatch",  # params.environment != environnement du plan
    "scope_violation",  # cible hors du registre du projet, parent hors racines/registre (GitLab : id non entier > 0)
    "budget_exceeded",
    "stale_lease",  # le bail n'est plus celui de l'appelant
    "step_not_ready",  # étape non réservée (`running`) ou étape antérieure non réussie
    "call_in_progress",  # le même appel est déjà en cours d'exécution
    "permission_missing",  # le connecteur de l'outil est `incomplete` (une sonde a échoué)
]
ProbeDenialCode = Literal["forbidden", "rate_limited", "unknown_connector", "probe_unavailable"]
FailureCode = Literal[
    "timeout",
    "permission_missing",
    "foreign_resource",
    "adapter_error",
    "adapter_defect",  # exception inattendue de l'adaptateur
    "invalid_output",  # sortie inutilisable (trop grande, identifiant de ressource absent)
    "storage_unavailable",
    "internal_error",  # toute autre exception : jamais de message
]

DENIED_MESSAGE = "appel refusé par la gateway"
FAILED_MESSAGE = "échec de l'appel"


class GatewayError(Exception):
    """Racine. `code` est la seule information transmise au moteur."""

    code: str

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class CallDenied(GatewayError):
    """L'appel a été refusé AVANT toute exécution (l'adaptateur n'a pas été appelé)."""

    def __init__(self, code: DenialCode) -> None:
        super().__init__(code, DENIED_MESSAGE)


class ProbeDenied(GatewayError):
    """`Gateway.probe` refusée avant toute sonde (rôle, limite, connecteur)."""

    def __init__(self, code: ProbeDenialCode) -> None:
        super().__init__(code, DENIED_MESSAGE)


class CallFailed(GatewayError):
    """L'appel était permis mais l'exécution a échoué ou sa sortie est inutilisable."""

    def __init__(
        self,
        code: FailureCode,
        diagnostic: ToolDiagnostic | None = None,
        raw_logs: tuple[str, ...] = (),
    ) -> None:
        super().__init__(code, FAILED_MESSAGE)
        self.diagnostic = diagnostic
        # Log brut de l'adaptateur : destiné à l'humain habilité seulement, jamais au modèle.
        self.raw_logs = raw_logs
