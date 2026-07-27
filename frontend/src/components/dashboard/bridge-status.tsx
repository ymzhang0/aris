import { type DragEvent, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Code2, Cpu, Loader2, PlugZap, Plus } from "lucide-react";

import {
  getBridgeProfiles,
  getBridgeResources,
  getBridgeStatus,
  switchBridgeProfile,
} from "@/lib/api";
import { CommandPaletteSelect } from "@/components/ui/command-palette-select";
import { useEnvironmentActions, useEnvironmentStore } from "@/store/EnvironmentStore";
import { cn } from "@/lib/utils";
import type { BridgeCodeResource, BridgeComputerResource, ResourceAttachment } from "@/types/aiida";
import { NewProfileDrawer } from "./new-profile-drawer";

const STATUS_POLL_INTERVAL_MS = 10_000;
const DETAILS_POLL_INTERVAL_MS = 5_000;
type HoveredDetail = "computers" | "codes" | "plugins" | null;
const RESOURCE_ATTACHMENT_DRAG_MIME = "application/x-aris-resource-attachment";

type HoveredResourceItem = {
  id: string;
  label: string;
  attachment: ResourceAttachment;
};

function formatComputerDetail(item: { label: string; hostname: string }): string {
  return `${item.label} (${item.hostname})`;
}

function formatCodeDetail(item: { label: string; default_plugin: string | null; computer_label: string | null }): string {
  const plugin = item.default_plugin ? ` \u2022 ${item.default_plugin}` : "";
  const computer = item.computer_label ? ` @ ${item.computer_label}` : "";
  return `${item.label}${plugin}${computer}`;
}

function toComputerAttachment(item: BridgeComputerResource): ResourceAttachment {
  const label = formatComputerDetail(item);
  const value = item.label?.trim() || item.hostname?.trim() || label;
  return {
    kind: "computer",
    value,
    label,
    plugin: null,
    computerLabel: item.label?.trim() || null,
    hostname: item.hostname?.trim() || null,
  };
}

function toCodeAttachment(item: BridgeCodeResource): ResourceAttachment {
  const codeLabel = item.label?.trim() || "code";
  const computerLabel = item.computer_label?.trim() || null;
  const value = computerLabel ? `${codeLabel}@${computerLabel}` : codeLabel;
  return {
    kind: "code",
    value,
    label: formatCodeDetail(item),
    plugin: item.default_plugin?.trim() || null,
    computerLabel,
    hostname: null,
  };
}

function toPluginAttachment(pluginName: string): ResourceAttachment {
  const value = pluginName.trim();
  return {
    kind: "plugin",
    value,
    label: value,
    plugin: value || null,
    computerLabel: null,
    hostname: null,
  };
}

function normalizeProfileName(value: string | null | undefined): string {
  const cleaned = String(value || "").trim();
  if (!cleaned || cleaned.toLowerCase() === "unknown") {
    return "";
  }
  return cleaned;
}

function normalizeEnvironmentComputers(
  items: Array<{ label?: string | null; hostname?: string | null; description?: string | null }>,
): BridgeComputerResource[] {
  return items
    .map((item) => ({
      label: String(item.label || "").trim(),
      hostname: String(item.hostname || "").trim(),
      description: typeof item.description === "string" && item.description.trim() ? item.description.trim() : null,
    }))
    .filter((item) => item.label || item.hostname);
}

function normalizeEnvironmentCodes(
  items: Array<{ label?: string | null; default_plugin?: string | null; computer_label?: string | null }>,
): BridgeCodeResource[] {
  return items
    .map((item) => ({
      label: String(item.label || "").trim(),
      default_plugin: typeof item.default_plugin === "string" && item.default_plugin.trim() ? item.default_plugin.trim() : null,
      computer_label: typeof item.computer_label === "string" && item.computer_label.trim() ? item.computer_label.trim() : null,
    }))
    .filter((item) => item.label);
}

interface BridgeStatusProps {
  onInfrastructureClick?: () => void;
  onSwitchProfileStart?: () => void;
  onSwitchProfileEnd?: () => void;
}

export function BridgeStatus({ onInfrastructureClick, onSwitchProfileStart, onSwitchProfileEnd }: BridgeStatusProps) {
  const queryClient = useQueryClient();
  const environmentState = useEnvironmentStore((state) => state);
  const { refreshInspection } = useEnvironmentActions();
  const [hoveredDetail, setHoveredDetail] = useState<HoveredDetail>(null);
  const [isNewProfileDrawerOpen, setIsNewProfileDrawerOpen] = useState(false);

  const statusQuery = useQuery({
    queryKey: ["aiida-bridge-status"],
    queryFn: getBridgeStatus,
    refetchInterval: STATUS_POLL_INTERVAL_MS,
    refetchOnWindowFocus: false,
    staleTime: 2_000,
  });

  const isOnline = (statusQuery.data?.status ?? "offline") === "online";

  const profilesQuery = useQuery({
    queryKey: ["aiida-bridge-profiles"],
    queryFn: getBridgeProfiles,
    enabled: isOnline,
    refetchInterval: isOnline ? DETAILS_POLL_INTERVAL_MS : false,
    refetchOnWindowFocus: false,
  });

  const resourcesQuery = useQuery({
    queryKey: ["aiida-bridge-resources"],
    queryFn: getBridgeResources,
    enabled: isOnline,
    refetchInterval: isOnline ? DETAILS_POLL_INTERVAL_MS : false,
    refetchOnWindowFocus: false,
  });

  const switchProfileMutation = useMutation({
    mutationFn: switchBridgeProfile,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["bootstrap"] }),
        queryClient.invalidateQueries({ queryKey: ["aiida-bridge-status"] }),
        queryClient.invalidateQueries({ queryKey: ["aiida-bridge-profiles"] }),
        queryClient.invalidateQueries({ queryKey: ["aiida-bridge-resources"] }),
        // Invalidate process and groups to get the new snapshot
        queryClient.invalidateQueries({ queryKey: ["processes"] }),
        queryClient.invalidateQueries({ queryKey: ["groups"] }),
        queryClient.invalidateQueries({ queryKey: ["aiida-infrastructure"] }),
        refreshInspection(),
      ]);
    },
    onSettled: () => {
      onSwitchProfileEnd?.();
    }
  });

  const status = statusQuery.data?.status ?? "offline";
  const isConnecting = statusQuery.isPending && !statusQuery.data;
  const isReconnecting = statusQuery.isError && Boolean(statusQuery.data) && status === "online";
  const statusLabel = isConnecting
    ? "Connecting…"
    : isReconnecting
      ? "Reconnecting…"
      : status === "online"
        ? "Ready"
        : "Unavailable";
  const environmentInspection = environmentState.inspection;
  const environmentReady = environmentState.inspectionStatus === "ready" && environmentInspection !== null;
  const environmentProfileName = normalizeProfileName(environmentInspection?.profile);
  const bridgeProfileName = normalizeProfileName(statusQuery.data?.profile) || normalizeProfileName(profilesQuery.data?.current_profile);
  const profileName = environmentState.useWorkerDefault
    ? (bridgeProfileName || environmentProfileName || "unknown")
    : (environmentProfileName || bridgeProfileName || "unknown");
  const pluginNames = environmentReady
    ? environmentState.availablePlugins
    : (statusQuery.data?.plugins ?? []);
  const resourceCounts = environmentReady
    ? {
        computers: environmentState.availableComputers.length,
        codes: environmentState.availableCodes.length,
        workchains: pluginNames.length,
      }
    : (statusQuery.data?.resources ?? { computers: 0, codes: 0, workchains: 0 });
  const computers = environmentReady
    ? normalizeEnvironmentComputers(environmentState.availableComputers)
    : (resourcesQuery.data?.computers ?? []);
  const codes = environmentReady
    ? normalizeEnvironmentCodes(environmentState.availableCodes)
    : (resourcesQuery.data?.codes ?? []);
  const profileOptions = environmentState.useWorkerDefault
    ? (profilesQuery.data?.profiles ?? [])
    : (environmentProfileName
        ? [{ name: environmentProfileName, is_default: true, is_active: true }]
        : []);
  const pluginCount = pluginNames.length || resourceCounts.workchains;
  const computerCount = computers.length || resourceCounts.computers;
  const codeCount = codes.length || resourceCounts.codes;
  const activeProfileName = profileName === "unknown" ? "" : profileName;
  const profilePills = useMemo(() => {
    if (profileOptions.length === 0) {
      return activeProfileName ? [{ name: activeProfileName }] : [];
    }
    if (activeProfileName && !profileOptions.some((profile) => profile.name === activeProfileName)) {
      return [{ name: activeProfileName }, ...profileOptions];
    }
    return profileOptions;
  }, [activeProfileName, profileOptions]);
  const profileSelectOptions = useMemo(
    () => profilePills.map((profile) => ({ value: profile.name, label: profile.name })),
    [profilePills],
  );
  const isProjectScopedProfile = !environmentState.useWorkerDefault;
  const isProfileSwitchDisabled = !isOnline || switchProfileMutation.isPending || profilePills.length === 0 || isProjectScopedProfile;

  const hoveredItems = useMemo(() => {
    if (hoveredDetail === "computers") {
      return computers.map((item) => {
        const attachment = toComputerAttachment(item);
        return {
          id: `computer:${attachment.value}`,
          label: attachment.label,
          attachment,
        } satisfies HoveredResourceItem;
      });
    }
    if (hoveredDetail === "codes") {
      return codes.map((item) => {
        const attachment = toCodeAttachment(item);
        return {
          id: `code:${attachment.value}`,
          label: attachment.label,
          attachment,
        } satisfies HoveredResourceItem;
      });
    }
    if (hoveredDetail === "plugins") {
      return pluginNames
        .filter((pluginName) => pluginName.trim())
        .map((pluginName) => {
          const attachment = toPluginAttachment(pluginName);
          return {
            id: `plugin:${attachment.value}`,
            label: attachment.label,
            attachment,
          } satisfies HoveredResourceItem;
        });
    }
    return [];
  }, [codes, computers, hoveredDetail, pluginNames]);

  const handleResourceDragStart = (event: DragEvent<HTMLDivElement>, attachment: ResourceAttachment) => {
    const cleanedValue = attachment.value.trim();
    if (!cleanedValue) {
      return;
    }
    event.dataTransfer.effectAllowed = "copy";
    event.dataTransfer.setData(RESOURCE_ATTACHMENT_DRAG_MIME, JSON.stringify(attachment));
    event.dataTransfer.setData("text/plain", cleanedValue);
  };

  return (
    <section className="relative z-40 min-h-0 overflow-visible border-b border-zinc-100 pb-4 dark:border-zinc-800/80">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <span className="relative flex h-2.5 w-2.5 items-center justify-center">
            <span
              className={cn(
                "absolute inline-flex h-4 w-4 rounded-full",
                isReconnecting
                  ? "animate-ping bg-amber-500/35"
                  : isOnline
                    ? "animate-ping bg-emerald-500/35"
                    : "animate-pulse bg-rose-500/35",
              )}
            />
            <span
              className={cn(
                "relative inline-flex h-2.5 w-2.5 rounded-full",
                isReconnecting
                  ? "bg-amber-500 shadow-[0_0_12px_rgba(245,158,11,0.75)]"
                  : isOnline
                    ? "bg-emerald-500 shadow-[0_0_12px_rgba(16,185,129,0.85)]"
                    : "bg-rose-500 shadow-[0_0_12px_rgba(239,68,68,0.8)]",
              )}
            />
          </span>

          <div className="min-w-0">
            <p className="text-[10px] font-semibold uppercase tracking-[0.17em] text-zinc-500 dark:text-zinc-400">
              Compute Environment
            </p>
            <div className="flex items-center gap-2 truncate text-sm font-medium text-zinc-800 dark:text-zinc-100">
              {statusLabel}
              {isOnline && (
                <button
                  onClick={onInfrastructureClick}
                  className="inline-flex items-center gap-1 text-[10px] font-medium text-zinc-500 transition-colors hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
                  title="View Infrastructure"
                >
                  <span className={cn("h-1.5 w-1.5 rounded-full", computerCount > 0 ? "bg-emerald-500" : "bg-rose-500")} />
                  {computerCount} Hosts
                </button>
              )}
            </div>
          </div>
        </div>

        <PlugZap
          className={cn(
            "h-4 w-4 shrink-0 transition-colors duration-200",
            isReconnecting ? "text-amber-500" : isOnline ? "text-emerald-500" : "text-rose-500",
          )}
        />
      </div>

      <div className="space-y-2 text-xs text-zinc-700 dark:text-zinc-200">
        <div className="flex items-center gap-2 border-b border-zinc-100 px-0 py-2 dark:border-zinc-800/80">
          <CommandPaletteSelect
            value={activeProfileName}
            options={profileSelectOptions}
            fallbackLabel={activeProfileName || "No profiles"}
            placeholder="No profiles"
            emptyLabel="No profiles"
            disabled={isProfileSwitchDisabled}
            label="Profile"
            ariaLabel="Select AiiDA profile"
            searchable={profileSelectOptions.length > 6}
            className="min-w-0 flex-1"
            triggerClassName="w-full justify-between rounded-none px-1.5 py-1 text-[12px]"
            onChange={(next) => {
              const cleanedNext = next.trim();
              if (!cleanedNext || cleanedNext === activeProfileName || switchProfileMutation.isPending || isProjectScopedProfile) {
                return;
              }
              onSwitchProfileStart?.();
              switchProfileMutation.mutate(cleanedNext);
            }}
          />
          <button
            onClick={() => setIsNewProfileDrawerOpen(true)}
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-none border-0 text-zinc-500 transition-colors enabled:hover:bg-transparent enabled:hover:text-zinc-900 disabled:cursor-not-allowed disabled:opacity-50 dark:text-zinc-400 dark:enabled:hover:bg-transparent dark:enabled:hover:text-zinc-200"
            title={isProjectScopedProfile ? "Profile management is available only in the managed compute environment" : "Create New Profile"}
            disabled={isProjectScopedProfile}
          >
            <Plus className="h-3.5 w-3.5" />
          </button>
          {isNewProfileDrawerOpen && (
            <NewProfileDrawer
              isOpen={isNewProfileDrawerOpen}
              onClose={() => setIsNewProfileDrawerOpen(false)}
              onSuccess={() => { }}
            />
          )}
          {switchProfileMutation.isPending ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin text-zinc-500 dark:text-zinc-300" />
          ) : null}
        </div>
        {isProjectScopedProfile ? (
          <p className="px-1 text-[11px] text-zinc-500 dark:text-zinc-400">
            Custom project runtimes expose the active profile as read-only. Switch back to the managed compute environment to manage profiles.
          </p>
        ) : null}

      </div>
      {isReconnecting ? (
        <p className="mt-2 inline-flex items-center gap-1.5 text-[11px] text-amber-600 dark:text-amber-300">
          <AlertTriangle className="h-3.5 w-3.5" />
          The latest health check was interrupted. Keeping the last confirmed online state.
        </p>
      ) : !isOnline && !isConnecting ? (
        <p className="mt-2 inline-flex items-center gap-1.5 text-[11px] text-rose-600 dark:text-rose-300">
          <AlertTriangle className="h-3.5 w-3.5" />
          The local compute runtime is unavailable. ARIS will keep retrying.
        </p>
      ) : null}
    </section>
  );
}
