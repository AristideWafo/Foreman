import { useState } from "react";
import { describeAdminError, type InvitationCreated, type Role } from "../../api/client";
import { NativeSelect } from "@/components/NativeSelect";
import { ROLE_LABELS } from "@/components/UserRoleBadge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ConfirmDialog, type Confirmation } from "./ConfirmDialog";
import { ActionError, QueryStatus } from "./QueryStatus";
import {
  useAdminInvitations,
  useAdminTeams,
  useCreateInvitation,
  useRevokeInvitation,
} from "./useAdmin";

/** Lien d'invitation : montré une seule fois, le serveur n'en garde que le condensat. */
function InviteLink({ link, onClose }: { link: string; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  return (
    <Alert>
      <AlertTitle>Lien d'invitation</AlertTitle>
      <AlertDescription className="flex flex-col gap-2">
        <p>Copiez ce lien maintenant : il ne sera plus jamais affiché.</p>
        <div className="flex gap-2">
          <Input
            readOnly
            aria-label="Lien d'invitation"
            value={link}
            onFocus={(e) => e.target.select()}
          />
          <Button
            variant="outline"
            onClick={() => {
              void navigator.clipboard.writeText(link).then(() => setCopied(true));
            }}
          >
            {copied ? "Copié" : "Copier"}
          </Button>
          <Button variant="ghost" onClick={onClose}>
            Fermer
          </Button>
        </div>
      </AlertDescription>
    </Alert>
  );
}

export function InvitationsTab({ role }: { role: Role }) {
  const invitations = useAdminInvitations();
  const teams = useAdminTeams();
  const create = useCreateInvitation();
  const revoke = useRevokeInvitation();
  const [email, setEmail] = useState("");
  const [teamId, setTeamId] = useState("");
  const [inviteRole, setInviteRole] = useState<Role>("developer");
  const [created, setCreated] = useState<InvitationCreated | null>(null);
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const isOrgAdmin = role === "org_admin";
  const teamName = (id: string | null) =>
    id === null ? "Aucune" : (teams.data?.find((t) => t.id === id)?.name ?? "Équipe");

  return (
    <div className="flex flex-col gap-6">
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate(
            { email: email.trim(), role: inviteRole, team_id: teamId || null },
            {
              onSuccess: (result) => {
                setCreated(result);
                setEmail("");
              },
            },
          );
        }}
      >
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="invite-email">Adresse e-mail</Label>
          <Input
            id="invite-email"
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <div className="flex min-w-40 flex-col gap-1.5">
          <Label htmlFor="invite-team">Équipe</Label>
          <NativeSelect
            id="invite-team"
            required={!isOrgAdmin}
            value={teamId}
            onChange={(e) => {
              setTeamId(e.target.value);
              if (e.target.value) setInviteRole((r) => (r === "org_admin" ? "developer" : r));
            }}
          >
            <option value="">{isOrgAdmin ? "Aucune équipe" : "Choisir…"}</option>
            {(teams.data ?? []).map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </NativeSelect>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="invite-role">Rôle</Label>
          <NativeSelect
            id="invite-role"
            value={inviteRole}
            onChange={(e) => setInviteRole(e.target.value as Role)}
          >
            <option value="developer">{ROLE_LABELS.developer}</option>
            <option value="team_admin">{ROLE_LABELS.team_admin}</option>
            {isOrgAdmin && !teamId ? (
              <option value="org_admin">{ROLE_LABELS.org_admin}</option>
            ) : null}
          </NativeSelect>
        </div>
        <Button type="submit" disabled={create.isPending || !email.trim()}>
          {create.isPending ? "Création…" : "Inviter"}
        </Button>
      </form>
      <ActionError message={create.isError ? describeAdminError(create.error) : null} />
      <ActionError message={revoke.isError ? describeAdminError(revoke.error) : null} />
      {created ? <InviteLink link={created.link} onClose={() => setCreated(null)} /> : null}
      <QueryStatus
        isPending={invitations.isPending}
        isError={invitations.isError}
        empty={invitations.data?.length === 0}
        emptyText="Aucune invitation en attente."
      />
      {invitations.data?.length ? (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>E-mail</TableHead>
              <TableHead>Équipe</TableHead>
              <TableHead>Rôle</TableHead>
              <TableHead>Expire le</TableHead>
              <TableHead>
                <span className="sr-only">Actions</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {invitations.data.map((i) => (
              <TableRow key={i.id}>
                <TableCell>{i.email}</TableCell>
                <TableCell>{teamName(i.team_id)}</TableCell>
                <TableCell>{ROLE_LABELS[i.role]}</TableCell>
                <TableCell>{new Date(i.expires_at).toLocaleDateString("fr-FR")}</TableCell>
                <TableCell>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() =>
                      setConfirmation({
                        title: "Révoquer cette invitation ?",
                        description: `Le lien envoyé à ${i.email} ne fonctionnera plus.`,
                        confirmLabel: "Révoquer",
                        run: () => revoke.mutate(i.id),
                      })
                    }
                  >
                    Révoquer<span className="sr-only"> l'invitation de {i.email}</span>
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      ) : null}
      <ConfirmDialog confirmation={confirmation} onClose={() => setConfirmation(null)} />
    </div>
  );
}
