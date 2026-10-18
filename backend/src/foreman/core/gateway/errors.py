"""Erreurs typées de la gateway. Le message est FIXE : aucun détail (paramètre, chemin, exception
d'adaptateur) ne sort. Le `code` est un identifiant stable, choisi dans une liste fermée."""

from typing import Literal

DenialCode = Literal[
    "unknown_context",  # exécution, plan ou étape introuvable pour ce projet, exécution terminée
    "unknown_tool",
    "invalid_params",  # le schéma de l'outil refuse les paramètres
    "policy_denied",  # la matrice refuse (ou une exigence n'est pas remplie)
    "plan_not_approved",
    "plan_hash_mismatch",
    "call_differs_from_step",  # l'appel n'est pas celui de l'étape `seq` du plan approuvé
    "environment_mismatch",  # params.environment != environnement du plan
    "scope_violation",  # parent ou cible hors du registre du projet et hors des racines
    "budget_exceeded",
]
FailureCode = Literal[
    "timeout",
    "permission_missing",
    "foreign_resource",
    "adapter_error",
    "adapter_defect",  # exception inattendue de l'adaptateur
    "invalid_output",  # sortie inutilisable (trop grande, identifiant de ressource absent)
    "storage_unavailable",
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


class CallFailed(GatewayError):
    """L'appel était permis mais l'exécution a échoué ou sa sortie est inutilisable."""

    def __init__(self, code: FailureCode) -> None:
        super().__init__(code, FAILED_MESSAGE)
