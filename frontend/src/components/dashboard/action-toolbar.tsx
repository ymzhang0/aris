import type { SpecializationAction, SpecializationSummary } from "@/types/aiida";
import { cn } from "@/lib/utils";

type ActionToolbarProps = {
  actions: SpecializationAction[];
  activeSpecializations: SpecializationSummary[];
  isBusy: boolean;
  onTriggerAction: (action: SpecializationAction) => void;
};

function chipClassName(action: SpecializationAction, disabled: boolean): string {
  const isQuantum = action.accent === "quantum";
  return cn(
    "inline-flex shrink-0 items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-all duration-200",
    disabled && "cursor-not-allowed opacity-45 hover:bg-inherit dark:hover:bg-inherit",
    !isQuantum &&
      "border-zinc-300/70 bg-zinc-50 text-zinc-700 hover:bg-zinc-100 dark:border-zinc-800 dark:bg-zinc-900/60 dark:text-zinc-300 dark:hover:bg-zinc-800/80",
    isQuantum &&
      "specialization-chip-glow border-emerald-300/80 bg-emerald-50/90 text-emerald-700 hover:bg-emerald-100 dark:border-emerald-800/70 dark:bg-emerald-950/35 dark:text-emerald-200 dark:hover:bg-emerald-900/50",
  );
}

export function ActionToolbar({
  actions,
  activeSpecializations,
  isBusy,
  onTriggerAction,
}: ActionToolbarProps) {
  if (actions.length === 0) {
    return null;
  }

  const activePluginLabels = activeSpecializations
    .filter((item) => item.active && item.variant === "specialized")
    .map((item) => item.label);

  return (
    <div>
      <div className="mb-3 flex items-center justify-between gap-3">
        <p className="text-sm font-medium text-zinc-800 dark:text-zinc-100">
          Capabilities
        </p>
        <p className="text-[10px] text-zinc-400 dark:text-zinc-500">
          {activePluginLabels.length > 0 ? `Active: ${activePluginLabels.join(", ")}` : "General actions"}
        </p>
      </div>
      <div className="minimal-scrollbar max-h-64 overflow-y-auto">
        <div className="flex flex-wrap gap-2">
          {actions.map((action) => {
            const disabled = isBusy || !action.enabled;
            return (
              <button
                key={`${action.specialization}-${action.id}`}
                type="button"
                className={chipClassName(action, disabled)}
                onClick={() => onTriggerAction(action)}
                disabled={disabled}
                title={action.disabled_reason || action.description || action.prompt}
              >
                {action.icon ? <span aria-hidden>{action.icon}</span> : null}
                <span className="whitespace-nowrap">{action.label}</span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
