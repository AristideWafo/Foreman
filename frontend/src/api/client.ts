import type { components, paths } from "./schema";

export type Project = components["schemas"]["Project"];
export type ErrorCode = components["schemas"]["ErrorResponse"]["error"];

type CreateProjectBody = NonNullable<
  paths["/api/projects"]["post"]["requestBody"]
>["content"]["application/json"];
type MessageAccepted =
  paths["/api/projects/{project_id}/messages"]["post"]["responses"][202]["content"]["application/json"];

type ApprovalBody = components["schemas"]["ApprovalRequest"];
type ApprovalAccepted = components["schemas"]["ApprovalAccepted"];
type ApprovalPending = components["schemas"]["ApprovalPending"];
type AdminApprovalBody = components["schemas"]["AdminApprovalRequest"];
type AdminApprovalResult = ApprovalAccepted | components["schemas"]["ApprovalRejected"];
export type Me = components["schemas"]["Me"];

type QuestionBody = components["schemas"]["QuestionAnswerRequest"];
type QuestionAccepted = components["schemas"]["QuestionAccepted"];

type Health = components["schemas"]["HealthResponse"];

const ERROR_CODES: readonly ErrorCode[] = [
  "not_found",
  "invalid_request",
  "method_not_allowed",
  "turn_in_progress",
  "capacity_exceeded",
  "internal_error",
  "not_implemented",
  "plan_hash_mismatch",
  "plan_not_approvable",
  "execution_in_progress",
  "question_closed",
  "unauthenticated",
  "forbidden",
  "policy_denied",
];

/** Erreur d'API : seuls le statut et le code opaque du contrat sont conservés. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: ErrorCode | null;

  constructor(status: number, code: ErrorCode | null) {
    super(`api_error_${status}`);
    this.status = status;
    this.code = code;
  }
}

async function readErrorCode(res: Response): Promise<ErrorCode | null> {
  try {
    const body: unknown = await res.json();
    if (typeof body === "object" && body !== null && "error" in body) {
      return ERROR_CODES.find((code) => code === body.error) ?? null;
    }
  } catch {
    // Corps absent ou illisible : le statut suffit.
  }
  return null;
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url, init);
  } catch {
    throw new ApiError(0, null);
  }
  if (!res.ok) throw new ApiError(res.status, await readErrorCode(res));
  return (await res.json()) as T;
}

function jsonPost(body: unknown): RequestInit {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

/** Mode de persistance annoncé par le serveur (`postgres`, `memory`), ou `null` s'il est absent. */
export async function getPersistence(): Promise<string | null> {
  const health = await request<Health>("/healthz");
  return health.persistence;
}

export function createProject(body: CreateProjectBody = { title: "" }): Promise<Project> {
  return request<Project>("/api/projects", jsonPost(body));
}

export function listProjects(): Promise<Project[]> {
  return request<Project[]>("/api/projects");
}

export function getProject(projectId: string): Promise<Project> {
  return request<Project>(`/api/projects/${encodeURIComponent(projectId)}`);
}

export function postMessage(projectId: string, text: string): Promise<MessageAccepted> {
  return request<MessageAccepted>(
    `/api/projects/${encodeURIComponent(projectId)}/messages`,
    jsonPost({ text }),
  );
}

/** Identité de l'appelant, lue côté serveur (le rôle ne vient jamais du front). */
export function getMe(): Promise<Me> {
  return request<Me>("/api/me");
}

/**
 * Valide un plan (201 à la création, 200 au rejeu idempotent, 202 si un administrateur doit encore approuver :
 * trois succès, le 202 se reconnaît à `status = "approval_required"`).
 */
export function approvePlan(
  projectId: string,
  planId: string,
  planHash: string,
): Promise<ApprovalAccepted | ApprovalPending> {
  const body: ApprovalBody = { plan_hash: planHash, decision: "approved" };
  return request<ApprovalAccepted | ApprovalPending>(
    `/api/projects/${encodeURIComponent(projectId)}/plans/${encodeURIComponent(planId)}/approvals`,
    jsonPost(body),
  );
}

/** Décision d'un administrateur (200 ou 201) : `ApprovalRejected` (`status = "rejected"`) ou `ApprovalAccepted` (`execution_id`). */
export function adminApprove(
  projectId: string,
  planId: string,
  planHash: string,
  decision: AdminApprovalBody["decision"],
): Promise<AdminApprovalResult> {
  const body: AdminApprovalBody = { plan_hash: planHash, decision };
  return request<AdminApprovalResult>(
    `/api/projects/${encodeURIComponent(projectId)}/plans/${encodeURIComponent(planId)}/admin-approvals`,
    jsonPost(body),
  );
}

/** Répond à une question de clarification (202) ou la reporte (200) : les deux sont des succès. */
export function answerQuestion(
  projectId: string,
  questionId: string,
  body: QuestionBody,
): Promise<QuestionAccepted> {
  return request<QuestionAccepted>(
    `/api/projects/${encodeURIComponent(projectId)}/questions/${encodeURIComponent(questionId)}`,
    jsonPost(body),
  );
}

export function eventsUrl(projectId: string): string {
  return `/api/projects/${encodeURIComponent(projectId)}/events`;
}

/** Message utilisateur en français, sans aucun détail technique. */
export function describeError(error: unknown): string {
  const code = error instanceof ApiError ? error.code : null;
  switch (code) {
    case "turn_in_progress":
      return "Une réponse est déjà en cours. Attendez qu'elle se termine avant d'envoyer un autre message.";
    case "invalid_request":
      return "Message invalide : il doit contenir entre 1 et 4 000 caractères.";
    case "capacity_exceeded":
      return "Le service est momentanément saturé. Réessayez dans un instant.";
    case "not_found":
      return "Projet introuvable.";
    default:
      return "Une erreur est survenue. Réessayez dans un instant.";
  }
}

/** Ce que le front fait après un refus d'approbation : réessayer, ou attendre la carte plan réémise. */
export interface ApprovalFailure {
  message: string;
  /** 409 et 404 : l'état a changé côté serveur, on attend la carte réémise plutôt que de deviner. */
  waitForCard: boolean;
}

/** Message utilisateur opaque pour l'approbation d'un plan. */
export function describeApprovalError(error: unknown): ApprovalFailure {
  const status = error instanceof ApiError ? error.status : 0;
  const code = error instanceof ApiError ? error.code : null;
  if (status === 501 || code === "not_implemented") {
    return { message: "La validation n'est pas encore disponible.", waitForCard: false };
  }
  if (status === 403 || code === "forbidden") {
    return { message: "Votre rôle ne permet pas cette décision.", waitForCard: false };
  }
  if (code === "execution_in_progress") {
    return { message: "Une exécution est déjà en cours pour ce plan.", waitForCard: true };
  }
  if (status === 409) {
    return {
      message: "Ce plan a changé ou ne peut plus être validé. La carte va être mise à jour.",
      waitForCard: true,
    };
  }
  if (status === 404) {
    return { message: "Ce plan est introuvable. La carte va être mise à jour.", waitForCard: true };
  }
  if (status === 422) {
    return { message: "Ce plan ne peut pas être validé en l'état.", waitForCard: false };
  }
  return { message: "La validation a échoué. Réessayez dans un instant.", waitForCard: false };
}

/** Ce que le front fait après un refus sur une question : réessayer, ou attendre la carte réémise. */
export interface QuestionFailure {
  message: string;
  /** `question_closed` et 404 : l'état a changé côté serveur, on attend la carte réémise. */
  waitForCard: boolean;
}

/** Message utilisateur opaque pour la réponse à une question (aucun détail technique). */
export function describeQuestionError(error: unknown): QuestionFailure {
  const status = error instanceof ApiError ? error.status : 0;
  const code = error instanceof ApiError ? error.code : null;
  if (status === 501 || code === "not_implemented") {
    return { message: "La réponse n'est pas encore disponible.", waitForCard: false };
  }
  if (code === "question_closed") {
    return {
      message: "Cette question n'est plus ouverte. La carte va être mise à jour.",
      waitForCard: true,
    };
  }
  if (code === "turn_in_progress") {
    return {
      message: "Une réponse est déjà en cours. Réessayez quand elle sera terminée.",
      waitForCard: false,
    };
  }
  if (status === 404) {
    return {
      message: "Cette question est introuvable. La carte va être mise à jour.",
      waitForCard: true,
    };
  }
  if (status === 422) {
    return { message: "Cette réponse n'est pas acceptée.", waitForCard: false };
  }
  return { message: "L'envoi a échoué. Réessayez dans un instant.", waitForCard: false };
}
