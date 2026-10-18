import type { CSSProperties, ReactNode } from "react";
import {
  TraceCollapsible,
  TraceCollapsibleContent,
  TraceCollapsibleTrigger,
  TraceIcon,
  TraceLine,
  TraceTitle,
} from "@/components/ui/trace";

interface CollapsibleSectionProps {
  title: ReactNode;
  icon?: ReactNode;
  status?: "running" | "error" | "pending";
  defaultOpen?: boolean;
  /** Sans contenu, la ligne s'affiche seule, sans chevron. */
  children?: ReactNode;
  className?: string;
  style?: CSSProperties;
}

/** Ligne repliable (icône, titre, chevron) : brique commune des étapes, journaux et listes de la conversation. */
export function CollapsibleSection({
  title,
  icon,
  status,
  defaultOpen = true,
  children,
  className,
  style,
}: CollapsibleSectionProps) {
  const line = (
    <TraceLine status={status}>
      {icon ? <TraceIcon>{icon}</TraceIcon> : null}
      <TraceTitle>{title}</TraceTitle>
    </TraceLine>
  );
  if (!children) {
    return (
      <div className={className} style={style}>
        {line}
      </div>
    );
  }
  return (
    <TraceCollapsible defaultOpen={defaultOpen} className={className} style={style}>
      <TraceCollapsibleTrigger>{line}</TraceCollapsibleTrigger>
      <TraceCollapsibleContent>{children}</TraceCollapsibleContent>
    </TraceCollapsible>
  );
}
