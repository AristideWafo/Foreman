import { Link } from "react-router-dom";
import type { ComponentProps } from "react";
import { Button } from "@/components/ui/button";

type LinkButtonProps = Omit<ComponentProps<typeof Button>, "render" | "nativeButton"> & {
  to: string;
};

/** Bouton qui navigue (lien de routeur) : un seul endroit pour ce motif. */
export function LinkButton({ to, ...props }: LinkButtonProps) {
  return <Button nativeButton={false} render={<Link to={to} />} {...props} />;
}
