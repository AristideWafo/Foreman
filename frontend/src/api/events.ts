import type { components } from "./schema";

/** Enveloppe d'événement du flux SSE (union discriminée sur `type`). */
export type ProjectEvent = components["schemas"]["Event"];
export type PlanCardData = components["schemas"]["PlanCardData"];
export type ExecutionCardData = components["schemas"]["ExecutionCardData"];
/** Données d'une carte : union discriminée sur `kind` (`plan` ou `execution`, extensible). */
export type CardData = PlanCardData | ExecutionCardData;
export type CardStep = components["schemas"]["CardStep"];
export type StepStatus = CardStep["status"];
