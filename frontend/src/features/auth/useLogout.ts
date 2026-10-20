import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { logout } from "../../api/client";

/** Ferme la session puis vide tout le cache : rien d'un utilisateur ne survit à la déconnexion. */
export function useLogout() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: logout,
    onSuccess: async () => {
      queryClient.clear();
      await navigate("/login", { replace: true });
    },
  });
}
