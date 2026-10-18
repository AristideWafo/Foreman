import { useMutation } from "@tanstack/react-query";
import { approvePlan, describeApprovalError } from "../../api/client";

/**
 * Validation d'un plan par le développeur. Le composant qui l'utilise est recréé (`key`) quand la carte
 * plan change : l'état d'une tentative ne survit donc pas à une carte réémise.
 */
export function usePlanApproval(projectId: string, planId: string, planHash: string) {
  const mutation = useMutation({ mutationFn: () => approvePlan(projectId, planId, planHash) });
  const failure = mutation.isError ? describeApprovalError(mutation.error) : null;
  return {
    approve: () => mutation.mutate(),
    pending: mutation.isPending,
    approved: mutation.isSuccess,
    /** 409 / 404 : on attend la carte plan réémise au lieu de réessayer. */
    waitingForCard: failure?.waitForCard === true,
    errorMessage: failure?.message ?? null,
  };
}
