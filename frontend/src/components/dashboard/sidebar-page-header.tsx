import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

type SidebarPageHeaderProps = {
  title: string;
  subtitle?: ReactNode;
  action?: ReactNode;
  className?: string;
};

export function SidebarPageHeader({
  title,
  subtitle,
  action,
  className,
}: SidebarPageHeaderProps) {
  return (
    <header
      className={cn(
        "flex min-h-[52px] items-start justify-between gap-3 border-b border-zinc-100 pb-3 dark:border-zinc-800/80",
        className,
      )}
    >
      <div className="min-w-0">
        <h2 className="text-sm font-semibold tracking-tight text-zinc-900 dark:text-zinc-100">
          {title}
        </h2>
        {subtitle ? (
          <div className="mt-1 truncate text-xs text-zinc-500 dark:text-zinc-400">
            {subtitle}
          </div>
        ) : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </header>
  );
}
