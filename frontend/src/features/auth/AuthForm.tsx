import type { ComponentProps, ReactNode } from "react";
import { BrandMark } from "@/components/BrandMark";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

/** Page plein cadre, hors barre latérale, pour les écrans sans session. */
export function AuthPage({
  title,
  error,
  submitLabel,
  busy,
  onSubmit,
  children,
}: {
  title: string;
  error: string | null;
  submitLabel: string;
  busy: boolean;
  onSubmit: () => void;
  children: ReactNode;
}) {
  return (
    <main className="flex min-h-svh items-center justify-center px-4 py-8">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <BrandMark className="mb-2 size-10" />
          <h1 className="text-lg font-semibold">{title}</h1>
        </CardHeader>
        <CardContent>
          <form
            className="flex flex-col gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              onSubmit();
            }}
          >
            {children}
            {error ? (
              <Alert variant="destructive">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            ) : null}
            <Button type="submit" disabled={busy}>
              {busy ? "Veuillez patienter…" : submitLabel}
            </Button>
          </form>
        </CardContent>
      </Card>
    </main>
  );
}

export function Field({
  label,
  id,
  ...props
}: { label: string; id: string } & ComponentProps<"input">) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <Input id={id} required {...props} />
    </div>
  );
}
