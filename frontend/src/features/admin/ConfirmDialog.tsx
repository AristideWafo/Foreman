import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";

export interface Confirmation {
  title: string;
  description: string;
  confirmLabel: string;
  run: () => void;
}

/** Confirmation d'une action destructrice ou qui retire des droits. `null` : fermée. */
export function ConfirmDialog({
  confirmation,
  onClose,
}: {
  confirmation: Confirmation | null;
  onClose: () => void;
}) {
  return (
    <AlertDialog open={confirmation !== null} onOpenChange={(open) => !open && onClose()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{confirmation?.title}</AlertDialogTitle>
          <AlertDialogDescription>{confirmation?.description}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Annuler</AlertDialogCancel>
          <AlertDialogAction
            variant="destructive"
            onClick={() => {
              confirmation?.run();
              onClose();
            }}
          >
            {confirmation?.confirmLabel}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
