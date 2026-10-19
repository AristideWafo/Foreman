import { useMutation } from "@tanstack/react-query";
import { adminApprove, describeApprovalError } from "../../api/client";

/**
 * Décision d'un administrateur sur un plan. Le composant qui l'utilise est recréé (`key`) quand la carte
 * d'approbation change d'état : la tentative ne survit pas à une carte réémise.
 */
export function useAdminApproval(projectId: string, planId: string, planHash: string) {
  const mutation = useMutation({
    mutationFn: (decision: "approved" | "rejected") =>
      adminApprove(projectId, planId, planHash, decision),
  });
  const failure = mutation.isError ? describeApprovalError(mutation.error) : null;
  return {
    approve: () => mutation.mutate("approved"),
    reject: () => mutation.mutate("rejected"),
    pending: mutation.isPending,
    /** Succès : la carte réémise par le serveur (`approved` ou `rejected`) prend le relais. */
    sent: mutation.isSuccess,
    /** 409 / 404 : on attend la carte réémise au lieu de réessayer. */
    waitingForCard: failure?.waitForCard === true,
    errorMessage: failure?.message ?? null,
  };
}
