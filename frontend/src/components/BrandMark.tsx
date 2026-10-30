import foreman from "@/assets/logos/foreman.svg";
import foremanDark from "@/assets/logos/foreman-dark.svg";

/** Logo Foreman (décoratif) : encre en clair, version blanche en sombre. Le nom est affiché à côté, en texte. */
export function BrandMark({ className = "size-6" }: { className?: string }) {
  return (
    <>
      <img
        src={foreman}
        alt=""
        aria-hidden="true"
        className={`${className} shrink-0 dark:hidden`}
      />
      <img
        src={foremanDark}
        alt=""
        aria-hidden="true"
        className={`${className} hidden shrink-0 dark:block`}
      />
    </>
  );
}
