import type { components } from "./schema";

/** Enveloppe d'événement du flux SSE (union discriminée sur `type`). */
export type ProjectEvent = components["schemas"]["Event"];
export type PlanCardData = components["schemas"]["PlanCardData"];
export type ExecutionCardData = components["schemas"]["ExecutionCardData"];
/** Données d'une carte : union discriminée sur `kind` (`plan` ou `execution`, extensible). */
export type ClarificationCardData = components["schemas"]["ClarificationCardData"];
export type CardData = PlanCardData | ExecutionCardData | ClarificationCardData;
export type CardStep = components["schemas"]["CardStep"];
export type StepStatus = CardStep["status"];
export type PlanStatus = NonNullable<PlanCardData["status"]>;
export type ExecutionState = ExecutionCardData["state"];
export type ResourceRef = components["schemas"]["ResourceRef"];
