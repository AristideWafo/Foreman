import { useMutation } from "@tanstack/react-query";
import { answerQuestion, describeQuestionError } from "../../api/client";

/**
 * Réponse ou report d'une question de clarification. Le composant qui l'utilise est recréé (`key`) quand
 * la question change d'état : la tentative ne survit donc pas à une carte réémise.
 */
export function useAnswerQuestion(projectId: string, questionId: string) {
  const mutation = useMutation({
    mutationFn: (body: Parameters<typeof answerQuestion>[2]) =>
      answerQuestion(projectId, questionId, body),
  });
  const failure = mutation.isError ? describeQuestionError(mutation.error) : null;
  return {
    answer: (value: string) => mutation.mutate({ decision: "answer", value }),
    defer: () => mutation.mutate({ decision: "defer" }),
    pending: mutation.isPending,
    /** Envoyée avec succès : la carte réémise par le serveur prend le relais. */
    sent: mutation.isSuccess,
    /** `question_closed` / 404 : on attend la carte réémise au lieu de réessayer. */
    waitingForCard: failure?.waitForCard === true,
    errorMessage: failure?.message ?? null,
  };
}
