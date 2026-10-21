import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  createInvitation,
  createTeam,
  disableUser,
  listAdminTeams,
  listAdminUsers,
  listIntegrations,
  listInvitations,
  removeMember,
  revokeCredentials,
  revokeInvitation,
  setAnthropicModel,
  setCredentials,
  setMemberRole,
  testIntegration,
  type MemberRole,
} from "../../api/client";

export function useAdminTeams() {
  return useQuery({ queryKey: ["admin", "teams"], queryFn: listAdminTeams, retry: false });
}
export function useAdminUsers() {
  return useQuery({ queryKey: ["admin", "users"], queryFn: listAdminUsers, retry: false });
}
export function useAdminInvitations() {
  return useQuery({ queryKey: ["admin", "invitations"], queryFn: listInvitations, retry: false });
}

/**
 * Mutation d'administration : recharge les listes d'administration, et `["me"]` (un changement de rôle,
 * ou de projets visibles, peut concerner l'appelant lui-même), et la liste des projets (équipes).
 */
function useAdminMutation<V, R>(fn: (v: V) => Promise<R>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: async () => {
      await Promise.all(
        [["admin"], ["me"], ["projects"]].map((queryKey) =>
          queryClient.invalidateQueries({ queryKey }),
        ),
      );
    },
  });
}

export const useCreateTeam = () => useAdminMutation(createTeam);
export const useCreateInvitation = () => useAdminMutation(createInvitation);
export const useRevokeInvitation = () => useAdminMutation(revokeInvitation);
export const useDisableUser = () => useAdminMutation(disableUser);
export const useRemoveMember = () =>
  useAdminMutation((v: { teamId: string; userId: string }) => removeMember(v.teamId, v.userId));
export const useSetMemberRole = () =>
  useAdminMutation((v: { teamId: string; userId: string; role: MemberRole }) =>
    setMemberRole(v.teamId, v.userId, v.role),
  );

export function useIntegrations() {
  return useQuery({ queryKey: ["admin", "integrations"], queryFn: listIntegrations, retry: false });
}

export const useRevokeCredentials = () => useAdminMutation(revokeCredentials);
export const useSetModel = () => useAdminMutation(setAnthropicModel);
/** Test : le résultat reste local à la ligne (pas d'invalidation, il ne change aucune donnée). */
export const useTestIntegration = () => useMutation({ mutationFn: testIntegration });

/**
 * Enregistrement du jeton, volontairement hors `useMutation` : le cache de mutations de TanStack Query
 * conserve les variables (donc le jeton). Ici, le jeton ne vit que le temps de l'appel.
 */
export function useSetCredentials() {
  const queryClient = useQueryClient();
  const [state, setState] = useState<{ pending: boolean; error: unknown }>({
    pending: false,
    error: null,
  });
  const save = async (v: { connector: string; token: string; name?: string }): Promise<boolean> => {
    setState({ pending: true, error: null });
    try {
      await setCredentials(v);
      await queryClient.invalidateQueries({ queryKey: ["admin", "integrations"] });
      setState({ pending: false, error: null });
      return true;
    } catch (error) {
      setState({ pending: false, error });
      return false;
    }
  };
  return { save, isPending: state.pending, error: state.error };
}
