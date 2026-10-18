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

/** Approuve un plan (201 à la création, 200 au rejeu idempotent : les deux sont des succès). */
export function approvePlan(
  projectId: string,
  planId: string,
  planHash: string,
): Promise<ApprovalAccepted> {
  const body: ApprovalBody = { plan_hash: planHash, decision: "approved" };
  return request<ApprovalAccepted>(
    `/api/projects/${encodeURIComponent(projectId)}/plans/${encodeURIComponent(planId)}/approvals`,
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
