
import React, { useCallback, useEffect, useState } from "react";
import {
    X,
    Upload,
    Terminal,
    Cpu,
    Code2,
    Loader2,
    CheckCircle2,
    AlertCircle,
    Wand2,
    Settings2,
    Sparkles,
    ChevronDown,
    ChevronUp
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { CommandPaletteSelect } from "@/components/ui/command-palette-select";
import type {
    InfrastructureComputerFormData,
    InfrastructureSetupPayload,
    ParseInfrastructureResponse,
} from "@/types/aiida";
import { cn } from "@/lib/utils";
import {
    getInfrastructureCapabilities,
    getSshHosts,
    parseInfrastructure,
    setupInfrastructure,
    type SSHHostDetails,
} from "@/lib/api";
import { useQuery } from "@tanstack/react-query";

type QuickAddModalProps = {
    isOpen: boolean;
    onClose: () => void;
    onSuccess: () => void;
};

type InfrastructureParseData = ParseInfrastructureResponse["data"];
const SYNC_SSH_TRANSPORT = "core.ssh";
const ASYNC_SSH_TRANSPORT = "core.ssh_async";
const LOCAL_TRANSPORT = "core.local";
const KEY_POLICY_OPTIONS = ["RejectPolicy", "WarningPolicy", "AutoAddPolicy"] as const;
const DEFAULT_TRANSPORT_AUTH_FIELDS: Record<string, string[]> = {
    [LOCAL_TRANSPORT]: ["use_login_shell", "safe_interval"],
    [SYNC_SSH_TRANSPORT]: [
        "username",
        "port",
        "look_for_keys",
        "key_filename",
        "timeout",
        "allow_agent",
        "proxy_jump",
        "proxy_command",
        "compress",
        "gss_auth",
        "gss_kex",
        "gss_deleg_creds",
        "gss_host",
        "load_system_host_keys",
        "key_policy",
        "use_login_shell",
        "safe_interval",
    ],
    [ASYNC_SSH_TRANSPORT]: [
        "host",
        "max_io_allowed",
        "authentication_script",
        "backend",
        "use_login_shell",
        "safe_interval",
    ],
};

type NullableBoolean = boolean | null | undefined;

function nullableBooleanValue(value: NullableBoolean): string {
    if (value === true) {
        return "true";
    }
    if (value === false) {
        return "false";
    }
    return "";
}

function parseNullableBoolean(value: string): boolean | null {
    if (value === "true") {
        return true;
    }
    if (value === "false") {
        return false;
    }
    return null;
}

function parseNullableInt(value: string): number | null {
    if (!value.trim()) {
        return null;
    }
    const parsed = Number.parseInt(value, 10);
    return Number.isFinite(parsed) ? parsed : null;
}

function parseNullableFloat(value: string): number | null {
    if (!value.trim()) {
        return null;
    }
    const parsed = Number.parseFloat(value);
    return Number.isFinite(parsed) ? parsed : null;
}

const flatFieldClassName =
    "w-full border-0 border-b border-zinc-200 bg-transparent px-0 py-2 text-sm text-zinc-700 outline-none transition focus:border-blue-500 dark:border-zinc-800 dark:bg-transparent dark:text-zinc-200";

const flatMonoFieldClassName = `${flatFieldClassName} font-mono`;

function BooleanSelectField({
    label,
    value,
    onChange,
}: {
    label: string;
    value: NullableBoolean;
    onChange: (value: boolean | null) => void;
}) {
    return (
        <div className="space-y-1">
            <label className="text-[10px] uppercase font-bold text-zinc-400">{label}</label>
            <select
                value={nullableBooleanValue(value)}
                onChange={(event) => onChange(parseNullableBoolean(event.target.value))}
                className={flatFieldClassName}
            >
                <option value="">Use Default</option>
                <option value="true">Yes</option>
                <option value="false">No</option>
            </select>
        </div>
    );
}

function buildDefaultComputerConfig(
    recommendedTransport = SYNC_SSH_TRANSPORT,
): InfrastructureComputerFormData {
    const isAsyncTransport = recommendedTransport === ASYNC_SSH_TRANSPORT;
    return {
        label: "",
        hostname: "",
        user: "",
        username: "",
        description: "",
        transport_type: recommendedTransport,
        scheduler_type: "core.direct",
        shebang: "#!/bin/bash",
        work_dir: "/tmp/aiida",
        mpiprocs_per_machine: 1,
        mpirun_command: "mpirun -np {tot_num_mpiprocs}",
        default_memory_per_machine: null,
        use_double_quotes: false,
        prepend_text: "",
        append_text: "",
        port: null,
        look_for_keys: null,
        key_filename: "",
        timeout: null,
        allow_agent: null,
        proxy_command: "",
        proxy_jump: "",
        compress: null,
        gss_auth: null,
        gss_kex: null,
        gss_deleg_creds: null,
        gss_host: "",
        load_system_host_keys: null,
        key_policy: "",
        safe_interval: null,
        use_login_shell: true,
        host: "",
        max_io_allowed: null,
        authentication_script: "",
        backend: isAsyncTransport ? "asyncssh" : "",
    };
}

const DEFAULT_CODE_CONFIG: NonNullable<InfrastructureParseData["code"]> = {
    label: "",
    description: "",
    default_calc_job_plugin: "",
    remote_abspath: "",
    prepend_text: "",
    append_text: "",
};

function createEmptyParseResult(recommendedTransport = SYNC_SSH_TRANSPORT): InfrastructureParseData {
    return {
        type: "computer",
        preset_matched: false,
        preset_domain: "",
        computer: { ...buildDefaultComputerConfig(recommendedTransport) },
        code: { ...DEFAULT_CODE_CONFIG },
    };
}

function mergeParseResult(
    raw?: InfrastructureParseData | null,
    recommendedTransport = SYNC_SSH_TRANSPORT,
): InfrastructureParseData {
    const defaultComputerConfig = buildDefaultComputerConfig(recommendedTransport);
    return {
        type: raw?.type ?? "computer",
        preset_matched: Boolean(raw?.preset_matched),
        preset_domain: raw?.preset_domain ?? "",
        computer: {
            ...defaultComputerConfig,
            ...(raw?.computer ?? {}),
        },
        code: {
            ...DEFAULT_CODE_CONFIG,
            ...(raw?.code ?? {}),
        },
    };
}

export function QuickAddModal({ isOpen, onClose, onSuccess }: QuickAddModalProps) {
    const [pasteText, setPasteText] = useState("");
    const [isParsing, setIsParsing] = useState(false);
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [parseResult, setParseResult] = useState<InfrastructureParseData>(() => createEmptyParseResult());
    const [error, setError] = useState<string | null>(null);
    const [activeTab, setActiveTab] = useState<"paste" | "form">("paste");

    const [showAdvanced, setShowAdvanced] = useState(false);
    const [selectedSshHost, setSelectedSshHost] = useState<string>("");

    const capabilitiesQuery = useQuery({
        queryKey: ["infrastructure-capabilities"],
        queryFn: getInfrastructureCapabilities,
    });
    const capabilities = capabilitiesQuery.data;
    const recommendedTransport = capabilities?.recommended_transport || SYNC_SSH_TRANSPORT;
    const availableTransports = capabilities?.available_transports?.length
        ? capabilities.available_transports
        : [LOCAL_TRANSPORT, SYNC_SSH_TRANSPORT];

    const sshHostsQuery = useQuery({
        queryKey: ["ssh-hosts"],
        queryFn: getSshHosts,
    });
    const sshHosts = sshHostsQuery.data || [];

    useEffect(() => {
        if (!isOpen) {
            return;
        }
        setPasteText("");
        setIsParsing(false);
        setIsSubmitting(false);
        setError(null);
        setActiveTab("paste");
        setShowAdvanced(false);
        setSelectedSshHost("");
        setParseResult(createEmptyParseResult(recommendedTransport));
    }, [isOpen, recommendedTransport]);

    useEffect(() => {
        if (!isOpen || !capabilities) {
            return;
        }
        setParseResult((current) => {
            const computer = current.computer ?? {};
            const isPristine = !computer.label && !computer.hostname && !computer.username;
            if (!isPristine || (computer.transport_type && computer.transport_type !== SYNC_SSH_TRANSPORT)) {
                return current;
            }
            return mergeParseResult(current, recommendedTransport);
        });
    }, [capabilities, isOpen, recommendedTransport]);

    const updateComputer = useCallback((patch: Partial<InfrastructureComputerFormData>) => {
        setParseResult((current) => ({
            ...current,
            computer: {
                ...buildDefaultComputerConfig(recommendedTransport),
                ...(current.computer ?? {}),
                ...patch,
            },
        }));
    }, [recommendedTransport]);

    const updateCode = useCallback((patch: Partial<NonNullable<InfrastructureParseData["code"]>>) => {
        setParseResult((current) => ({
            ...current,
            code: {
                ...DEFAULT_CODE_CONFIG,
                ...(current.code ?? {}),
                ...patch,
            },
        }));
    }, []);

    const handleTransportChange = useCallback((nextTransport: string) => {
        setParseResult((current) => {
            const base = {
                ...buildDefaultComputerConfig(recommendedTransport),
                ...(current.computer ?? {}),
                transport_type: nextTransport,
            };

            if (nextTransport === ASYNC_SSH_TRANSPORT) {
                return {
                    ...current,
                    computer: {
                        ...base,
                        username: "",
                        port: null,
                        look_for_keys: null,
                        key_filename: "",
                        timeout: null,
                        allow_agent: null,
                        proxy_command: "",
                        proxy_jump: "",
                        compress: null,
                        gss_auth: null,
                        gss_kex: null,
                        gss_deleg_creds: null,
                        gss_host: "",
                        load_system_host_keys: null,
                        key_policy: "",
                        host: base.host || base.hostname || selectedSshHost || "",
                        backend: base.backend || "asyncssh",
                    },
                };
            }

            if (nextTransport === LOCAL_TRANSPORT) {
                return {
                    ...current,
                    computer: {
                        ...base,
                        username: "",
                        port: null,
                        look_for_keys: null,
                        key_filename: "",
                        timeout: null,
                        allow_agent: null,
                        proxy_command: "",
                        proxy_jump: "",
                        compress: null,
                        gss_auth: null,
                        gss_kex: null,
                        gss_deleg_creds: null,
                        gss_host: "",
                        load_system_host_keys: null,
                        key_policy: "",
                        host: "",
                        max_io_allowed: null,
                        authentication_script: "",
                        backend: "",
                    },
                };
            }

            return {
                ...current,
                computer: {
                    ...base,
                    host: "",
                    max_io_allowed: null,
                    authentication_script: "",
                    backend: "",
                },
            };
        });
    }, [recommendedTransport, selectedSshHost]);

    const handleParse = async () => {
        if (!pasteText.trim() && !selectedSshHost) return;
        setIsParsing(true);
        setError(null);
        try {
            const hostDetails = sshHosts.find(h => h.alias === selectedSshHost) || null;
            const textToParse = pasteText.trim() || `Configure computer for SSH host ${selectedSshHost}`;

            const response = await parseInfrastructure(textToParse, hostDetails);
            if (response.status === "success" && response.data) {
                setParseResult(mergeParseResult(response.data, recommendedTransport));
                setActiveTab("form");
            } else {
                setError("Failed to parse input. Please try again or fill manually.");
            }
        } catch (err: any) {
            setError(err.response?.data?.detail || "AI Parsing failed.");
        } finally {
            setIsParsing(false);
        }
    };

    const handleSubmit = async () => {
        if (!parseResult || !parseResult.computer) {
            setError("Computer configuration is missing.");
            return;
        }
        const transportType = parseResult.computer.transport_type || recommendedTransport;
        if (!availableTransports.includes(transportType)) {
            setError(
                `Transport ${transportType} is not available for aiida-core ${capabilities?.aiida_core_version || "this installation"}.`,
            );
            return;
        }
        if (transportType === ASYNC_SSH_TRANSPORT) {
            const unsupportedFields = [
                "username",
                "port",
                "look_for_keys",
                "key_filename",
                "timeout",
                "allow_agent",
                "proxy_command",
                "proxy_jump",
                "compress",
                "gss_auth",
                "gss_kex",
                "gss_deleg_creds",
                "gss_host",
                "load_system_host_keys",
                "key_policy",
            ]
                .filter((field) => {
                    const value = (parseResult.computer as Record<string, unknown>)[field];
                    return value !== null && value !== undefined && value !== "";
                });
            if (unsupportedFields.length > 0) {
                setError(
                    `core.ssh_async does not accept core.ssh-only fields: ${unsupportedFields.join(", ")}. Use host, backend, authentication script, and max I/O instead.`,
                );
                return;
            }
        }
        setIsSubmitting(true);
        setError(null);

        try {
            const payload: InfrastructureSetupPayload = {
                computer_label: parseResult.computer.label || "unknown_computer",
                hostname: parseResult.computer.hostname || "unknown_host",
                user: parseResult.computer.user || "",
                username: parseResult.computer.username || "",
                computer_description: parseResult.computer.description || "",
                transport_type: transportType,
                scheduler_type: parseResult.computer.scheduler_type || "core.direct",
                shebang: parseResult.computer.shebang || "#!/bin/bash",
                work_dir: parseResult.computer.work_dir || "/tmp/aiida",
                mpiprocs_per_machine: parseResult.computer.mpiprocs_per_machine || 1,
                mpirun_command: parseResult.computer.mpirun_command || "mpirun -np {tot_num_mpiprocs}",
                default_memory_per_machine: parseResult.computer.default_memory_per_machine ?? null,
                use_double_quotes: parseResult.computer.use_double_quotes === true,
                prepend_text: parseResult.computer.prepend_text || "",
                append_text: parseResult.computer.append_text || "",
                port: parseResult.computer.port ?? null,
                look_for_keys: parseResult.computer.look_for_keys ?? null,
                key_filename: parseResult.computer.key_filename || "",
                timeout: parseResult.computer.timeout ?? null,
                allow_agent: parseResult.computer.allow_agent ?? null,
                proxy_command: parseResult.computer.proxy_command || "",
                proxy_jump: parseResult.computer.proxy_jump || "",
                compress: parseResult.computer.compress ?? null,
                gss_auth: parseResult.computer.gss_auth ?? null,
                gss_kex: parseResult.computer.gss_kex ?? null,
                gss_deleg_creds: parseResult.computer.gss_deleg_creds ?? null,
                gss_host: parseResult.computer.gss_host || "",
                load_system_host_keys: parseResult.computer.load_system_host_keys ?? null,
                key_policy: parseResult.computer.key_policy || "",
                use_login_shell: parseResult.computer.use_login_shell !== false,
                safe_interval: parseResult.computer.safe_interval ?? null,
                host: parseResult.computer.host || "",
                max_io_allowed: parseResult.computer.max_io_allowed ?? null,
                authentication_script: parseResult.computer.authentication_script || "",
                backend: parseResult.computer.backend || "",
            };

            const code = parseResult.code;
            if (code && code.label && code.default_calc_job_plugin && code.remote_abspath) {
                payload.code_label = code.label;
                payload.code_description = code.description || "";
                payload.default_calc_job_plugin = code.default_calc_job_plugin;
                payload.remote_abspath = code.remote_abspath;
                payload.code_prepend_text = code.prepend_text || "";
                payload.code_append_text = code.append_text || "";
            }

            const response = await setupInfrastructure(payload);
            if (response.connection_status === "failed") {
                setError(`Setup partial via DB, but connection test failed: ${response.connection_error}`);
            } else {
                onSuccess();
                onClose();
            }
        } catch (err: any) {
            setError(err.response?.data?.detail || "Submission failed.");
        } finally {
            setIsSubmitting(false);
        }
    };


    const selectedTransport = parseResult.computer?.transport_type || recommendedTransport;
    const isAsyncTransport = selectedTransport === ASYNC_SSH_TRANSPORT;
    const isLocalTransport = selectedTransport === LOCAL_TRANSPORT;
    const selectedTransportAuthFields = new Set(
        capabilities?.transport_auth_fields?.[selectedTransport]
        ?? DEFAULT_TRANSPORT_AUTH_FIELDS[selectedTransport]
        ?? [],
    );
    const supportsSelectedAuthField = (field: string) => selectedTransportAuthFields.has(field);

    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm animate-in fade-in duration-200">
            <div className="bg-white dark:bg-zinc-950 shadow-2xl w-full max-w-4xl overflow-hidden flex flex-col max-h-[90vh]">
                <header className="px-6 py-5 border-b border-zinc-100 dark:border-zinc-900 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                        <div className="p-2 text-zinc-600 dark:text-zinc-400">
                            <Plus className="h-5 w-5 text-zinc-600 dark:text-zinc-400" />
                        </div>
                        <div>
                            <h2 className="text-xl font-semibold tracking-tight">Create Computer</h2>
                            <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">Parse an SSH snippet or review the form before saving.</p>
                        </div>
                    </div>
                    <Button variant="ghost" size="icon" onClick={onClose}>
                        <X className="h-5 w-5" />
                    </Button>
                </header>

                <div className="flex-1 overflow-y-auto p-6 space-y-6 [&_input]:border-0 [&_input]:border-b [&_input]:border-zinc-200 [&_input]:bg-transparent [&_input]:px-0 [&_input]:text-zinc-700 [&_input]:shadow-none [&_input]:outline-none [&_input]:focus:border-blue-500 dark:[&_input]:border-zinc-800 dark:[&_input]:bg-transparent dark:[&_input]:text-zinc-200 [&_select]:border-0 [&_select]:border-b [&_select]:border-zinc-200 [&_select]:bg-transparent [&_select]:px-0 [&_select]:text-zinc-700 [&_select]:outline-none [&_select]:focus:border-blue-500 dark:[&_select]:border-zinc-800 dark:[&_select]:bg-transparent dark:[&_select]:text-zinc-200 [&_textarea]:border-0 [&_textarea]:border-b [&_textarea]:border-zinc-200 [&_textarea]:bg-transparent [&_textarea]:px-0 [&_textarea]:text-zinc-700 [&_textarea]:outline-none [&_textarea]:focus:border-blue-500 dark:[&_textarea]:border-zinc-800 dark:[&_textarea]:bg-transparent dark:[&_textarea]:text-zinc-200">
                    <div className="flex gap-6 border-b border-zinc-100 pb-2 dark:border-zinc-800">
                        <button
                            onClick={() => setActiveTab("paste")}
                            className={cn(
                                "flex items-center justify-center gap-2 border-b py-2 text-sm font-medium transition-all",
                                activeTab === "paste" ? "border-blue-500 text-zinc-900 dark:text-zinc-100" : "border-transparent text-zinc-500"
                            )}
                        >
                            <Terminal className="h-4 w-4" />
                            Drop & Paste
                        </button>
                        <button
                            onClick={() => setActiveTab("form")}
                            className={cn(
                                "flex items-center justify-center gap-2 border-b py-2 text-sm font-medium transition-all",
                                activeTab === "form" ? "border-blue-500 text-zinc-900 dark:text-zinc-100" : "border-transparent text-zinc-500"
                            )}
                        >
                            <Settings2 className="h-4 w-4" />
                            Review Setup
                        </button>
                    </div>

                    {activeTab === "paste" ? (
                        <div className="space-y-4">
                            <div className="relative group">
                                <textarea
                                    value={pasteText}
                                    onChange={(e) => setPasteText(e.target.value)}
                                    placeholder="Paste an SSH command, YAML snippet, or describe your computer..."
                                    className="w-full h-48 border-0 border-b border-zinc-200 bg-transparent px-0 py-3 text-sm font-mono focus:border-blue-500 outline-none transition-all resize-none dark:border-zinc-800 dark:bg-transparent"
                                />
                                <div className="absolute top-4 right-4 text-zinc-400 group-hover:text-blue-500 transition-colors">
                                    <Upload className="h-5 w-5" />
                                </div>
                            </div>

                            <div className="flex flex-col gap-2">
                                <label className="text-xs font-semibold text-zinc-500 uppercase tracking-wider">
                                    Or Select Existing SSH Host
                                </label>
                                <CommandPaletteSelect
                                    value={selectedSshHost}
                                    options={[
                                        { value: "", label: "No SSH Host Selected" },
                                        ...sshHosts.map((host) => ({
                                            value: host.alias,
                                            label: host.alias,
                                            description: host.hostname || null,
                                            keywords: [host.hostname || ""],
                                        })),
                                    ]}
                                    ariaLabel="Select existing SSH host"
                                    searchable={sshHosts.length > 6}
                                    className="w-full"
                                    triggerClassName="flex w-full items-center justify-between rounded-lg px-2 py-2 text-sm"
                                    onChange={setSelectedSshHost}
                                />
                            </div>

                            <div className="border-t border-blue-100 pt-4 dark:border-blue-900/30 flex gap-3">
                                <Wand2 className="h-5 w-5 text-blue-500 shrink-0" />
                                <div className="space-y-1 text-sm text-blue-700 dark:text-blue-300">
                                    <p>
                                        Tip: paste exported computer YAML, scheduler snippets, or select an SSH host alias. Structured YAML is parsed locally before AI fallback.
                                    </p>
                                    <p className="text-xs">
                                        aiida-core: <span className="font-mono">{capabilities?.aiida_core_version || "detecting..."}</span>
                                        {" · "}
                                        transports: <span className="font-mono">{availableTransports.join(", ")}</span>
                                    </p>
                                </div>
                            </div>

                            <Button
                                onClick={handleParse}
                                className="w-full h-12 bg-zinc-900 dark:bg-zinc-100 hover:bg-zinc-800 dark:hover:bg-zinc-200 text-white dark:text-zinc-900 rounded-none font-semibold gap-2"
                                disabled={isParsing || (!pasteText.trim() && !selectedSshHost)}
                            >
                                {isParsing ? <Loader2 className="h-5 w-5 animate-spin" /> : <Wand2 className="h-5 w-5" />}
                                Analyze and Auto-fill
                            </Button>
                        </div>
                    ) : (
                        <div className="space-y-6 animate-in slide-in-from-right-2 duration-300">
                                <div className="space-y-6">
                                    {parseResult.preset_matched && (
                                        <div className="border-t border-emerald-200 pt-4 dark:border-emerald-900/30 animate-in fade-in zoom-in-95">
                                          <div className="flex gap-3">
                                            <Sparkles className="h-5 w-5 text-emerald-600 dark:text-emerald-400 shrink-0" />
                                            <div>
                                                <h4 className="text-sm font-semibold text-emerald-800 dark:text-emerald-300">Preset Applied Automatically</h4>
                                                <p className="text-sm text-emerald-700 dark:text-emerald-400 mt-1">
                                                    Identified domain <code className="font-mono text-xs bg-emerald-100 dark:bg-emerald-900/50 px-1 py-0.5 rounded">{parseResult.preset_domain}</code>. Known parameters have been pre-filled. Review execution details under Advanced Configuration if needed.
                                                </p>
                                            </div>
                                          </div>
                                        </div>
                                    )}
                                    {parseResult.computer && (
                                        <div className="space-y-5 border-t border-zinc-100 pt-5 dark:border-zinc-800">
                                            <div className="flex items-center gap-2 text-zinc-500">
                                                <Cpu className="h-4 w-4" />
                                                <span className="text-xs font-bold uppercase tracking-wider">Computer Setup</span>
                                            </div>
                                            <div className="space-y-5">
                                                <div className="space-y-3">
                                                    <div>
                                                        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-zinc-400">Identity</p>
                                                        <p className="mt-1 text-xs text-slate-500 dark:text-zinc-400">Core naming fields for the computer entry.</p>
                                                    </div>
                                                    <div className="grid grid-cols-2 gap-x-4 gap-y-5">
                                                        <div className="space-y-1.5">
                                                            <label className="text-[10px] uppercase font-bold text-zinc-400">Label</label>
                                                            <input
                                                                value={parseResult.computer.label || ""}
                                                                onChange={(e) => updateComputer({ label: e.target.value })}
                                                                className={flatFieldClassName}
                                                            />
                                                        </div>
                                                        <div className="space-y-1.5">
                                                            <label className="text-[10px] uppercase font-bold text-zinc-400">Description</label>
                                                            <input
                                                                value={parseResult.computer.description || ""}
                                                                onChange={(e) => updateComputer({ description: e.target.value })}
                                                                className="w-full bg-white dark:bg-zinc-800 border-none rounded-xl px-3.5 py-2.5 text-sm focus:ring-2 focus:ring-blue-100 outline-none transition-all"
                                                            />
                                                        </div>
                                                    </div>
                                                </div>

                                                <div className="space-y-3">
                                                    <div>
                                                        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-zinc-400">Technical</p>
                                                        <p className="mt-1 text-xs text-slate-500 dark:text-zinc-400">Connection mode, scheduler, and remote identity.</p>
                                                    </div>
                                                    <div className="grid grid-cols-2 gap-x-4 gap-y-5">
                                                        <div className="space-y-1.5">
                                                            <label className="text-[10px] uppercase font-bold text-zinc-400">Hostname</label>
                                                            <input
                                                                value={parseResult.computer.hostname || ""}
                                                                onChange={(e) => updateComputer({ hostname: e.target.value })}
                                                                className="w-full bg-white dark:bg-zinc-800 border-none rounded-xl px-3.5 py-2.5 text-sm focus:ring-2 focus:ring-blue-100 outline-none transition-all"
                                                            />
                                                        </div>
                                                        <div className="space-y-1.5">
                                                            <label className="text-[10px] uppercase font-bold text-zinc-400">Transport</label>
                                                            <select
                                                                value={selectedTransport}
                                                                onChange={(e) => handleTransportChange(e.target.value)}
                                                                className={flatMonoFieldClassName}
                                                            >
                                                                {availableTransports.map((transport) => (
                                                                    <option key={transport} value={transport}>{transport}</option>
                                                                ))}
                                                            </select>
                                                        </div>
                                                        <div className="space-y-1.5">
                                                            <label className="text-[10px] uppercase font-bold text-zinc-400">Scheduler</label>
                                                            <input
                                                                value={parseResult.computer.scheduler_type || ""}
                                                                onChange={(e) => updateComputer({ scheduler_type: e.target.value })}
                                                                className="w-full bg-white dark:bg-zinc-800 border-none rounded-xl px-3.5 py-2.5 text-sm font-mono focus:ring-2 focus:ring-blue-100 outline-none transition-all"
                                                            />
                                                        </div>
                                                        <div className="space-y-1.5">
                                                            <label className="text-[10px] uppercase font-bold text-zinc-400">User Email</label>
                                                            <input
                                                                value={parseResult.computer.user || ""}
                                                                onChange={(e) => updateComputer({ user: e.target.value })}
                                                                placeholder="Optional AiiDA user email"
                                                                className="w-full bg-white dark:bg-zinc-800 border-none rounded-xl px-3.5 py-2.5 text-sm focus:ring-2 focus:ring-blue-100 outline-none transition-all"
                                                            />
                                                        </div>
                                                        {isAsyncTransport ? (
                                                            <div className="space-y-1.5">
                                                                <label className="text-[10px] uppercase font-bold text-zinc-400">Host</label>
                                                                <input
                                                                    value={parseResult.computer.host || ""}
                                                                    onChange={(e) => updateComputer({ host: e.target.value })}
                                                                    placeholder="Host entry from ~/.ssh/config"
                                                                    className="w-full bg-white dark:bg-zinc-800 border-none rounded-xl px-3.5 py-2.5 text-sm font-mono focus:ring-2 focus:ring-blue-100 outline-none transition-all"
                                                                />
                                                            </div>
                                                        ) : !isLocalTransport ? (
                                                            <div className="space-y-1.5">
                                                                <label className="text-[10px] uppercase font-bold text-zinc-400">Username</label>
                                                                <input
                                                                    value={parseResult.computer.username || ""}
                                                                    onChange={(e) => updateComputer({ username: e.target.value })}
                                                                    className="w-full bg-white dark:bg-zinc-800 border-none rounded-xl px-3.5 py-2.5 text-sm focus:ring-2 focus:ring-blue-100 outline-none transition-all"
                                                                />
                                                            </div>
                                                        ) : (
                                                            <div className="col-span-2 border-t border-zinc-100 py-3 text-xs text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                                                                Local transport does not require remote SSH authentication fields.
                                                            </div>
                                                        )}
                                                    </div>
                                                </div>
                                            </div>

                                            {isAsyncTransport && (
                                                <div className="border-t border-amber-200 py-3 text-xs text-amber-800 dark:border-amber-900/40 dark:text-amber-300">
                                                    <span className="font-semibold">core.ssh_async</span> follows the AiiDA async SSH configure model: <code className="font-mono">Host</code> must match an entry in <code className="font-mono">~/.ssh/config</code>, and sync-only fields like <code className="font-mono">username</code>, <code className="font-mono">port</code>, or <code className="font-mono">proxy_jump</code> do not apply.
                                                </div>
                                            )}

                                            <button
                                                onClick={() => setShowAdvanced(!showAdvanced)}
                                                className="flex items-center gap-1 text-xs font-semibold text-blue-600 hover:text-blue-700 dark:text-blue-400 pt-1 transition-colors"
                                            >
                                                {showAdvanced ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                                                {showAdvanced ? "Hide Advanced Configuration" : "Show Advanced Configuration"}
                                            </button>

                                            {showAdvanced && (
                                                <div className="grid grid-cols-2 gap-x-4 gap-y-5 pt-4 border-t border-slate-200 dark:border-zinc-800 animate-in slide-in-from-top-2 duration-200">
                                                    <div className="col-span-2">
                                                        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-zinc-400">Execution</p>
                                                        <p className="mt-1 text-xs text-slate-500 dark:text-zinc-400">Working directory, MPI defaults, and runtime shell options.</p>
                                                    </div>
                                                    <div className="space-y-1.5 col-span-2">
                                                        <label className="text-[10px] uppercase font-bold text-zinc-400">Work Directory</label>
                                                        <input
                                                            value={parseResult.computer.work_dir || ""}
                                                            onChange={(e) => updateComputer({ work_dir: e.target.value })}
                                                            className="w-full bg-white dark:bg-zinc-800 border-none rounded-xl px-3.5 py-2.5 text-sm font-mono focus:ring-2 focus:ring-blue-100 outline-none transition-all"
                                                        />
                                                    </div>
                                                    <div className="space-y-1.5">
                                                        <label className="text-[10px] uppercase font-bold text-zinc-400">MPI Procs / Machine</label>
                                                        <input
                                                            type="number"
                                                            value={parseResult.computer.mpiprocs_per_machine || ""}
                                                            onChange={(e) => updateComputer({ mpiprocs_per_machine: parseInt(e.target.value, 10) || 1 })}
                                                            className="w-full bg-white dark:bg-zinc-800 border-none rounded-xl px-3.5 py-2.5 text-sm focus:ring-2 focus:ring-blue-100 outline-none transition-all"
                                                        />
                                                    </div>
                                                    <div className="space-y-1.5">
                                                        <label className="text-[10px] uppercase font-bold text-zinc-400">Default Memory / Machine (kB)</label>
                                                        <input
                                                            type="number"
                                                            value={parseResult.computer.default_memory_per_machine ?? ""}
                                                            onChange={(e) => updateComputer({ default_memory_per_machine: e.target.value ? parseInt(e.target.value, 10) || null : null })}
                                                            className="w-full bg-white dark:bg-zinc-800 border-none rounded-xl px-3.5 py-2.5 text-sm focus:ring-2 focus:ring-blue-100 outline-none transition-all"
                                                        />
                                                    </div>
                                                    <div className="space-y-1.5 col-span-2">
                                                        <label className="text-[10px] uppercase font-bold text-zinc-400">MPI Run Command</label>
                                                        <input
                                                            value={parseResult.computer.mpirun_command || ""}
                                                            onChange={(e) => updateComputer({ mpirun_command: e.target.value })}
                                                            className="w-full bg-white dark:bg-zinc-800 border-none rounded-xl px-3.5 py-2.5 text-sm font-mono focus:ring-2 focus:ring-blue-100 outline-none transition-all"
                                                        />
                                                    </div>
                                                    <div className="space-y-1">
                                                        <label className="text-[10px] uppercase font-bold text-zinc-400">Shebang</label>
                                                        <input value={parseResult.computer.shebang || ""} onChange={(e) => updateComputer({ shebang: e.target.value })} className="w-full bg-white dark:bg-zinc-800 border-none rounded-lg px-3 py-2 text-sm font-mono focus:ring-2 focus:ring-blue-100 outline-none transition-all text-zinc-600 dark:text-zinc-400" />
                                                    </div>
                                                    <div className="space-y-1">
                                                        <label className="text-[10px] uppercase font-bold text-zinc-400">Safe Interval</label>
                                                        <input type="number" step="0.1" value={parseResult.computer.safe_interval ?? ""} onChange={(e) => updateComputer({ safe_interval: parseNullableFloat(e.target.value) })} className="w-full bg-white dark:bg-zinc-800 border-none rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-100 outline-none transition-all text-zinc-600 dark:text-zinc-400" />
                                                    </div>
                                                    {isAsyncTransport ? (
                                                        <>
                                                            {supportsSelectedAuthField("max_io_allowed") && (
                                                                <div className="space-y-1">
                                                                    <label className="text-[10px] uppercase font-bold text-zinc-400">Max I/O Allowed</label>
                                                                    <input type="number" value={parseResult.computer.max_io_allowed ?? ""} onChange={(e) => updateComputer({ max_io_allowed: parseNullableInt(e.target.value) })} className="w-full bg-white dark:bg-zinc-800 border-none rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-100 outline-none transition-all text-zinc-600 dark:text-zinc-400" />
                                                                </div>
                                                            )}
                                                            {supportsSelectedAuthField("authentication_script") && (
                                                                <div className="space-y-1">
                                                                    <label className="text-[10px] uppercase font-bold text-zinc-400">Authentication Script</label>
                                                                    <input value={parseResult.computer.authentication_script || ""} onChange={(e) => updateComputer({ authentication_script: e.target.value })} className="w-full bg-white dark:bg-zinc-800 border-none rounded-lg px-3 py-2 text-sm font-mono focus:ring-2 focus:ring-blue-100 outline-none transition-all text-zinc-600 dark:text-zinc-400" />
                                                                </div>
                                                            )}
                                                            {supportsSelectedAuthField("backend") && (
                                                                <div className="space-y-1">
                                                                    <label className="text-[10px] uppercase font-bold text-zinc-400">Backend</label>
                                                                    <select value={parseResult.computer.backend || "asyncssh"} onChange={(e) => updateComputer({ backend: e.target.value })} className="w-full bg-white dark:bg-zinc-800 border-none rounded-lg px-3 py-2 text-sm font-mono focus:ring-2 focus:ring-blue-100 outline-none transition-all text-zinc-600 dark:text-zinc-400">
                                                                        <option value="asyncssh">asyncssh</option>
                                                                        <option value="openssh">openssh</option>
                                                                    </select>
                                                                </div>
                                                            )}
                                                        </>
                                                    ) : !isLocalTransport ? (
                                                        <>
                                                            {supportsSelectedAuthField("port") && (
                                                                <div className="space-y-1">
                                                                    <label className="text-[10px] uppercase font-bold text-zinc-400">Port</label>
                                                                    <input type="number" value={parseResult.computer.port ?? ""} onChange={(e) => updateComputer({ port: parseNullableInt(e.target.value) })} className="w-full bg-white dark:bg-zinc-800 border-none rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-100 outline-none transition-all text-zinc-600 dark:text-zinc-400" />
                                                                </div>
                                                            )}
                                                            {supportsSelectedAuthField("look_for_keys") && (
                                                                <BooleanSelectField label="Look For Keys" value={parseResult.computer.look_for_keys} onChange={(value) => updateComputer({ look_for_keys: value })} />
                                                            )}
                                                            {supportsSelectedAuthField("key_filename") && (
                                                                <div className="space-y-1">
                                                                    <label className="text-[10px] uppercase font-bold text-zinc-400">Key Filename</label>
                                                                    <input value={parseResult.computer.key_filename || ""} onChange={(e) => updateComputer({ key_filename: e.target.value })} className="w-full bg-white dark:bg-zinc-800 border-none rounded-lg px-3 py-2 text-sm font-mono focus:ring-2 focus:ring-blue-100 outline-none transition-all text-zinc-600 dark:text-zinc-400" />
                                                                </div>
                                                            )}
                                                            {supportsSelectedAuthField("timeout") && (
                                                                <div className="space-y-1">
                                                                    <label className="text-[10px] uppercase font-bold text-zinc-400">Timeout</label>
                                                                    <input type="number" value={parseResult.computer.timeout ?? ""} onChange={(e) => updateComputer({ timeout: parseNullableInt(e.target.value) })} className="w-full bg-white dark:bg-zinc-800 border-none rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-100 outline-none transition-all text-zinc-600 dark:text-zinc-400" />
                                                                </div>
                                                            )}
                                                            {supportsSelectedAuthField("allow_agent") && (
                                                                <BooleanSelectField label="Allow Agent" value={parseResult.computer.allow_agent} onChange={(value) => updateComputer({ allow_agent: value })} />
                                                            )}
                                                            {supportsSelectedAuthField("proxy_jump") && (
                                                                <div className="space-y-1">
                                                                    <label className="text-[10px] uppercase font-bold text-zinc-400">Proxy Jump</label>
                                                                    <input value={parseResult.computer.proxy_jump || ""} onChange={(e) => updateComputer({ proxy_jump: e.target.value })} className="w-full bg-white dark:bg-zinc-800 border-none rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-100 outline-none transition-all text-zinc-600 dark:text-zinc-400" />
                                                                </div>
                                                            )}
                                                            {supportsSelectedAuthField("proxy_command") && (
                                                                <div className="space-y-1">
                                                                    <label className="text-[10px] uppercase font-bold text-zinc-400">Proxy Command</label>
                                                                    <input value={parseResult.computer.proxy_command || ""} onChange={(e) => updateComputer({ proxy_command: e.target.value })} className="w-full bg-white dark:bg-zinc-800 border-none rounded-lg px-3 py-2 text-sm font-mono focus:ring-2 focus:ring-blue-100 outline-none transition-all text-zinc-600 dark:text-zinc-400" />
                                                                </div>
                                                            )}
                                                            {supportsSelectedAuthField("compress") && (
                                                                <BooleanSelectField label="Compress" value={parseResult.computer.compress} onChange={(value) => updateComputer({ compress: value })} />
                                                            )}
                                                            {supportsSelectedAuthField("gss_auth") && (
                                                                <BooleanSelectField label="GSS Auth" value={parseResult.computer.gss_auth} onChange={(value) => updateComputer({ gss_auth: value })} />
                                                            )}
                                                            {supportsSelectedAuthField("gss_kex") && (
                                                                <BooleanSelectField label="GSS KEX" value={parseResult.computer.gss_kex} onChange={(value) => updateComputer({ gss_kex: value })} />
                                                            )}
                                                            {supportsSelectedAuthField("gss_deleg_creds") && (
                                                                <BooleanSelectField label="GSS Deleg Creds" value={parseResult.computer.gss_deleg_creds} onChange={(value) => updateComputer({ gss_deleg_creds: value })} />
                                                            )}
                                                            {supportsSelectedAuthField("gss_host") && (
                                                                <div className="space-y-1">
                                                                    <label className="text-[10px] uppercase font-bold text-zinc-400">GSS Host</label>
                                                                    <input value={parseResult.computer.gss_host || ""} onChange={(e) => updateComputer({ gss_host: e.target.value })} className="w-full bg-white dark:bg-zinc-800 border-none rounded-lg px-3 py-2 text-sm font-mono focus:ring-2 focus:ring-blue-100 outline-none transition-all text-zinc-600 dark:text-zinc-400" />
                                                                </div>
                                                            )}
                                                            {supportsSelectedAuthField("load_system_host_keys") && (
                                                                <BooleanSelectField label="Load System Host Keys" value={parseResult.computer.load_system_host_keys} onChange={(value) => updateComputer({ load_system_host_keys: value })} />
                                                            )}
                                                            {supportsSelectedAuthField("key_policy") && (
                                                                <div className="space-y-1">
                                                                    <label className="text-[10px] uppercase font-bold text-zinc-400">Key Policy</label>
                                                                    <select value={parseResult.computer.key_policy || ""} onChange={(e) => updateComputer({ key_policy: e.target.value })} className="w-full bg-white dark:bg-zinc-800 border-none rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-100 outline-none transition-all text-zinc-600 dark:text-zinc-400">
                                                                        <option value="">Use Default</option>
                                                                        {KEY_POLICY_OPTIONS.map((option) => (
                                                                            <option key={option} value={option}>{option}</option>
                                                                        ))}
                                                                    </select>
                                                                </div>
                                                            )}
                                                        </>
                                                    ) : (
                                                        <div className="col-span-1 border-t border-dashed border-zinc-200 px-0 py-2 text-xs text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                                                            No additional transport-specific authentication fields are required for <code className="font-mono">core.local</code>.
                                                        </div>
                                                    )}
                                                    <button
                                                        type="button"
                                                        onClick={() => updateComputer({ use_double_quotes: !parseResult.computer?.use_double_quotes })}
                                                        className={cn(
                                                            "flex items-center justify-between border-b px-0 py-2 text-sm transition-colors",
                                                            parseResult.computer.use_double_quotes
                                                                ? "border-blue-500 text-blue-700 dark:border-blue-500 dark:text-blue-300"
                                                                : "border-zinc-200 text-zinc-600 dark:border-zinc-800 dark:text-zinc-300",
                                                        )}
                                                    >
                                                        <span className="text-[11px] font-semibold uppercase tracking-wider">Use Double Quotes</span>
                                                        <span>{parseResult.computer.use_double_quotes ? "Enabled" : "Disabled"}</span>
                                                    </button>
                                                    <button
                                                        type="button"
                                                        onClick={() => updateComputer({ use_login_shell: parseResult.computer?.use_login_shell === false })}
                                                        className={cn(
                                                            "flex items-center justify-between border-b px-0 py-2 text-sm transition-colors",
                                                            parseResult.computer.use_login_shell !== false
                                                                ? "border-zinc-200 text-zinc-700 dark:border-zinc-800 dark:text-zinc-200"
                                                                : "border-amber-200 text-amber-700 dark:border-amber-800 dark:text-amber-300",
                                                        )}
                                                    >
                                                        <span className="text-[11px] font-semibold uppercase tracking-wider">Use Login Shell</span>
                                                        <span>{parseResult.computer.use_login_shell !== false ? "Enabled" : "Disabled"}</span>
                                                    </button>
                                                    <div className="space-y-1 col-span-2">
                                                        <label className="text-[10px] uppercase font-bold text-zinc-400">Prepend Text</label>
                                                        <textarea value={parseResult.computer.prepend_text || ""} onChange={(e) => updateComputer({ prepend_text: e.target.value })} className={`${flatMonoFieldClassName} h-24 whitespace-pre`} />
                                                    </div>
                                                    <div className="space-y-1 col-span-2">
                                                        <label className="text-[10px] uppercase font-bold text-zinc-400">Append Text</label>
                                                        <textarea value={parseResult.computer.append_text || ""} onChange={(e) => updateComputer({ append_text: e.target.value })} className={`${flatMonoFieldClassName} h-24 whitespace-pre`} />
                                                    </div>
                                                </div>
                                            )}
                                        </div>
                                    )}

                                    {parseResult.code && Object.keys(parseResult.code).length > 0 && (
                                        <div className="space-y-4 border-t border-zinc-100 pt-5 dark:border-zinc-800">
                                            <div className="flex items-center gap-2 text-zinc-500">
                                                <Code2 className="h-4 w-4" />
                                                <span className="text-xs font-bold uppercase tracking-wider">Code Defaults</span>
                                            </div>
                                            <div className="grid grid-cols-2 gap-x-4 gap-y-5">
                                                <div className="space-y-1">
                                                    <label className="text-[10px] uppercase font-bold text-zinc-400">Target Plugin</label>
                                                    <input
                                                        value={parseResult.code.default_calc_job_plugin || ""}
                                                        onChange={(e) => updateCode({ default_calc_job_plugin: e.target.value })}
                                                        className={flatMonoFieldClassName}
                                                    />
                                                </div>
                                                <div className="space-y-1">
                                                    <label className="text-[10px] uppercase font-bold text-zinc-400">Code Label</label>
                                                    <input
                                                        value={parseResult.code.label || ""}
                                                        onChange={(e) => updateCode({ label: e.target.value })}
                                                        className={flatFieldClassName}
                                                        placeholder="e.g., pw"
                                                    />
                                                </div>
                                                <div className="col-span-2 space-y-1">
                                                    <label className="text-[10px] uppercase font-bold text-zinc-400">Remote Executable Path</label>
                                                    <input
                                                        value={parseResult.code.remote_abspath || ""}
                                                        onChange={(e) => updateCode({ remote_abspath: e.target.value })}
                                                        className={flatMonoFieldClassName}
                                                    />
                                                </div>
                                                <div className="col-span-2 space-y-1">
                                                    <label className="text-[10px] uppercase font-bold text-zinc-400">Code Prepend Text</label>
                                                    <textarea
                                                        value={parseResult.code.prepend_text || ""}
                                                        onChange={(e) => updateCode({ prepend_text: e.target.value })}
                                                        className={`${flatMonoFieldClassName} h-20`}
                                                    />
                                                </div>
                                                <div className="col-span-2 space-y-1">
                                                    <label className="text-[10px] uppercase font-bold text-zinc-400">Code Append Text</label>
                                                    <textarea
                                                        value={parseResult.code.append_text || ""}
                                                        onChange={(e) => updateCode({ append_text: e.target.value })}
                                                        className={`${flatMonoFieldClassName} h-20`}
                                                    />
                                                </div>
                                            </div>
                                        </div>
                                    )}
                                </div>
                        </div>
                    )}

                    {error && (
                        <div className="border-t border-rose-200 pt-3 flex gap-x-2 text-rose-600 dark:border-rose-900/30 dark:text-rose-400 text-sm">
                            <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
                            {error}
                        </div>
                    )}
                </div>

                <footer className="sticky bottom-0 px-6 py-4 border-t border-zinc-100 dark:border-zinc-900 bg-white/95 dark:bg-zinc-950/95 backdrop-blur flex items-center justify-end gap-3">
                    <Button variant="ghost" onClick={onClose} disabled={isSubmitting}>Cancel</Button>
                    <Button
                        disabled={!parseResult || isSubmitting}
                        onClick={handleSubmit}
                        className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-none px-6 gap-2"
                    >
                        {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                        Test Connection & Save
                    </Button>
                </footer>
            </div>
        </div>
    );
}

function Plus(props: any) {
    return (
        <svg
            {...props}
            xmlns="http://www.w3.org/2000/svg"
            width="24"
            height="24"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
        >
            <path d="M5 12h14" />
            <path d="M12 5v14" />
        </svg>
    );
}
