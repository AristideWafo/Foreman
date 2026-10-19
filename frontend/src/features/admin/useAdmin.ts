import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createInvitation,
  createTeam,
  disableUser,
  listAdminTeams,
  listAdminUsers,
  listInvitations,
  removeMember,
  revokeInvitation,
  setMemberRole,
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
