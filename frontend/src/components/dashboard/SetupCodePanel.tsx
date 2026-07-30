import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import {
  CheckCircle2,
  ChevronDown,
  Copy,
  FileCode,
  Info,
  Loader2,
  Plus,
  Settings2,
  Terminal,
  Wand2,
  X,
} from "lucide-react";
import { parse as parseYaml } from "yaml";

import { Button } from "@/components/ui/button";
import { CommandPaletteSelect } from "@/components/ui/command-palette-select";
import { cn } from "@/lib/utils";
import { frontendApi } from "@/api";

interface CodeDetailed {
  pk: number;
  label: string;
  description: string | null;
  default_calc_job_plugin: string;
  remote_abspath: string;
  prepend_text: string | null;
  append_text: string | null;
  with_mpi: boolean | null;
  use_double_quotes: boolean;
}

interface SetupCodePanelProps {
  computerLabel: string;
  onClose: () => void;
  onSuccess?: () => void;
}

type CodeFormState = {
  label: string;
  description: string;
  default_calc_job_plugin: string;
  remote_abspath: string;
  prepend_text: string;
  append_text: string;
  with_mpi: boolean | null;
  use_double_quotes: boolean;
};

const baseInputClassName =
  "w-full border-0 border-b border-slate-200 bg-transparent px-0 py-2.5 text-sm text-slate-700 outline-none transition focus:border-blue-500 dark:border-zinc-800 dark:bg-transparent dark:text-zinc-100 dark:focus:border-blue-500";

const baseTextareaClassName =
  `${baseInputClassName} min-h-[108px] resize-none font-mono text-[13px] leading-5`;

function createEmptyForm(): CodeFormState {
  return {
    label: "",
    description: "",
    default_calc_job_plugin: "",
    remote_abspath: "",
    prepend_text: "",
    append_text: "",
    with_mpi: true,
    use_double_quotes: false,
  };
}

function extractErrorMessage(detail: unknown): string | null {
  if (Array.isArray(detail)) {
    const firstItem = detail.find((item) => item && typeof item === "object") as
      | { msg?: unknown; loc?: unknown }
      | undefined;
    if (firstItem) {
      const location = Array.isArray(firstItem.loc) ? firstItem.loc.join(".") : "";
      const message = typeof firstItem.msg === "string" ? firstItem.msg.trim() : "";
      return [location, message].filter(Boolean).join(": ") || message || null;
    }
  }
  if (detail && typeof detail === "object") {
    const record = detail as { reason?: unknown; error?: unknown; message?: unknown };
    if (typeof record.reason === "string" && record.reason.trim()) {
      return record.reason.trim();
    }
    if (typeof record.error === "string" && record.error.trim()) {
      return record.error.trim();
    }
    if (typeof record.message === "string" && record.message.trim()) {
      return record.message.trim();
    }
  }
  return null;
}

function ToolButton({
  icon: Icon,
  label,
  active,
  disabled,
  onClick,
}: {
  icon: typeof Copy;
  label: string;
  active?: boolean;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "inline-flex h-9 items-center gap-2 border-b px-0 text-xs font-semibold transition disabled:cursor-not-allowed disabled:opacity-50",
        active
          ? "border-slate-900 text-slate-900 dark:border-slate-100 dark:text-slate-100"
          : "border-transparent text-slate-500 hover:text-slate-900 dark:text-zinc-300 dark:hover:text-zinc-100",
      )}
    >
      <Icon className="h-3.5 w-3.5" />
      {label}
    </button>
  );
}

function HintBadge({ text }: { text: string }) {
  return (
    <span className="group relative inline-flex">
      <span
        tabIndex={0}
        className="inline-flex h-4 w-4 items-center justify-center rounded-full bg-slate-200 text-slate-500 outline-none transition group-hover:bg-slate-300 group-focus-within:bg-slate-300 dark:bg-zinc-800 dark:text-zinc-400 dark:group-hover:bg-zinc-700 dark:group-focus-within:bg-zinc-700"
        aria-label={text}
      >
        <Info className="h-3 w-3" />
      </span>
      <span className="pointer-events-none absolute left-1/2 top-full z-20 mt-2 hidden w-56 -translate-x-1/2 rounded-xl bg-slate-900 px-3 py-2 text-[11px] font-medium leading-4 text-white shadow-xl group-hover:block group-focus-within:block dark:bg-zinc-100 dark:text-zinc-900">
        {text}
      </span>
    </span>
  );
}

function FieldLabel({
  label,
  required,
  hint,
}: {
  label: string;
  required?: boolean;
  hint?: string;
}) {
  return (
    <div className="mb-1.5 flex items-center gap-1.5">
      <label className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-zinc-400">
        {label}
        {required ? " *" : ""}
      </label>
      {hint ? <HintBadge text={hint} /> : null}
    </div>
  );
}

function FieldHint({ children }: { children: string }) {
  return <p className="mt-1.5 text-xs leading-5 text-slate-500 dark:text-zinc-400">{children}</p>;
}

function SectionBlock({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <section className="border-t border-slate-100 px-0 py-4 dark:border-zinc-800">
      <div className="mb-4 space-y-1">
        <h3 className="text-sm font-semibold text-slate-900 dark:text-zinc-100">{title}</h3>
        <p className="text-xs leading-5 text-slate-500 dark:text-zinc-400">{description}</p>
      </div>
      <div className="grid grid-cols-1 gap-x-4 gap-y-5 md:grid-cols-2">{children}</div>
    </section>
  );
}

function ToggleTile({
  label,
  description,
  value,
  onToggle,
}: {
  label: string;
  description: string;
  value: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className={cn(
        "flex items-start justify-between border-b px-0 py-3 text-left transition",
        value
          ? "border-blue-500 text-blue-700 dark:border-blue-500 dark:text-blue-200"
          : "border-slate-200 text-slate-600 hover:border-slate-300 dark:border-zinc-800 dark:text-zinc-300 dark:hover:border-zinc-700",
      )}
    >
      <div className="space-y-1">
        <p className="text-sm font-semibold">{label}</p>
        <p className="text-xs leading-5 opacity-80">{description}</p>
      </div>
      <span
        className={cn(
          "mt-0.5 inline-flex h-5 min-w-10 items-center border-b px-1 transition",
          value ? "justify-end border-blue-500" : "justify-start border-slate-200 dark:border-zinc-700",
        )}
      >
        <span className="h-3.5 w-3.5 rounded-full bg-current opacity-80" />
      </span>
    </button>
  );
}

export function SetupCodePanel({ computerLabel, onClose, onSuccess }: SetupCodePanelProps) {
  const [isLoading, setIsLoading] = useState(false);
  const [isFetchingTemplates, setIsFetchingTemplates] = useState(false);
  const [templates, setTemplates] = useState<CodeDetailed[]>([]);
  const [selectedTemplatePk, setSelectedTemplatePk] = useState("none");
  const [yamlInput, setYamlInput] = useState("");
  const [showYamlInput, setShowYamlInput] = useState(false);
  const [showTemplatePicker, setShowTemplatePicker] = useState(false);
  const [isAdvancedOpen, setIsAdvancedOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [formData, setFormData] = useState<CodeFormState>(createEmptyForm);

  useEffect(() => {
    if (!computerLabel) {
      return;
    }
    void fetchTemplates();
    setFormData(createEmptyForm());
    setSelectedTemplatePk("none");
    setYamlInput("");
    setShowYamlInput(false);
    setShowTemplatePicker(false);
    setIsAdvancedOpen(false);
    setError(null);
    setSuccess(null);
  }, [computerLabel]);

  const templateOptions = useMemo(
    () => [
      { value: "none", label: isFetchingTemplates ? "Loading templates..." : "Copy from existing code" },
      ...templates.map((template) => ({
        value: template.pk.toString(),
        label: template.label,
        description: template.default_calc_job_plugin,
        keywords: [template.default_calc_job_plugin, template.remote_abspath],
      })),
    ],
    [isFetchingTemplates, templates],
  );

  async function fetchTemplates() {
    setIsFetchingTemplates(true);
    try {
      const response = await frontendApi.get(`/infrastructure/computer/${computerLabel}/codes`);
      setTemplates(response.data);
    } catch (fetchError) {
      console.error("Failed to fetch templates:", fetchError);
    } finally {
      setIsFetchingTemplates(false);
    }
  }

  function handleTemplateChange(pk: string) {
    setSelectedTemplatePk(pk);
    if (pk === "none") {
      return;
    }

    const template = templates.find((item) => item.pk.toString() === pk);
    if (!template) {
      return;
    }

    setFormData({
      label: template.label,
      description: template.description || "",
      default_calc_job_plugin: template.default_calc_job_plugin,
      remote_abspath: template.remote_abspath,
      prepend_text: template.prepend_text || "",
      append_text: template.append_text || "",
      with_mpi: template.with_mpi,
      use_double_quotes: template.use_double_quotes,
    });
    setSuccess(`Applied template: ${template.label}`);
    setShowTemplatePicker(false);
    window.setTimeout(() => setSuccess(null), 2500);
  }

  function handleApplyYaml() {
    if (!yamlInput.trim()) {
      return;
    }

    try {
      const parsedValue = parseYaml(yamlInput);
      if (!parsedValue || typeof parsedValue !== "object" || Array.isArray(parsedValue)) {
        setError("The pasted YAML must be a flat object of code settings.");
        return;
      }
      const data = parsedValue as Record<string, unknown>;

      const nextFormData = { ...formData };
      let hasChanges = false;

      const applyValue = (
        key: string,
        targetField: keyof CodeFormState,
        type: "string" | "boolean" = "string",
      ) => {
        if (!Object.prototype.hasOwnProperty.call(data, key)) {
          return;
        }
        const rawValue = data[key];
        if (type === "boolean") {
          if (rawValue === null || rawValue === undefined) {
            nextFormData[targetField] = null as never;
            hasChanges = true;
            return;
          }
          const normalizedValue = String(rawValue).trim().toLowerCase();
          if (!normalizedValue || normalizedValue === "none") {
            nextFormData[targetField] = null as never;
            hasChanges = true;
            return;
          }
          nextFormData[targetField] = (normalizedValue === "true") as never;
        } else {
          if (rawValue === null || rawValue === undefined) {
            return;
          }
          nextFormData[targetField] = String(rawValue) as never;
        }
        hasChanges = true;
      };

      applyValue("label", "label");
      applyValue("description", "description");
      applyValue("default_calc_job_plugin", "default_calc_job_plugin");
      applyValue("input_plugin", "default_calc_job_plugin");
      applyValue("filepath_executable", "remote_abspath");
      applyValue("remote_abspath", "remote_abspath");
      applyValue("remote_abs_path", "remote_abspath");
      applyValue("prepend_text", "prepend_text");
      applyValue("append_text", "append_text");
      applyValue("with_mpi", "with_mpi", "boolean");
      applyValue("use_double_quotes", "use_double_quotes", "boolean");

      if (!hasChanges) {
        setError("No supported configuration keys were found in the pasted text.");
        return;
      }

      setFormData(nextFormData);
      setError(null);
      setShowYamlInput(false);
      setSuccess("Configuration imported.");
      window.setTimeout(() => setSuccess(null), 2500);
    } catch {
      setError("Failed to parse the pasted configuration. Please check the format.");
    }
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!formData.label || !formData.remote_abspath || !formData.default_calc_job_plugin) {
      setError("Please fill in Label, Plugin, and Executable Path before saving.");
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      await frontendApi.post("/infrastructure/setup-code", {
        ...formData,
        computer_label: computerLabel,
      });
      onSuccess?.();
      onClose();
    } catch (submitError: any) {
      const detail = submitError.response?.data?.detail;
      const detailMessage = extractErrorMessage(detail);
      const errorMessage =
        detailMessage || submitError.response?.data?.error || submitError.message || "Failed to setup code";
      setError(errorMessage);
      console.error("Setup code error:", submitError);
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <section className="flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden bg-white shadow-2xl dark:bg-zinc-950">
      <header className="border-b border-slate-200 px-6 py-6 dark:border-zinc-800">
        <div className="flex items-center justify-between gap-3">
          <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400 dark:text-zinc-500">
            Installed Code
          </p>
          <div className="flex items-center justify-end gap-2">
            <ToolButton
              icon={Copy}
              label="Template"
              active={showTemplatePicker}
              disabled={isFetchingTemplates}
              onClick={() => {
                setShowTemplatePicker((current) => !current);
                setShowYamlInput(false);
              }}
            />
            <ToolButton
              icon={FileCode}
              label="Import"
              active={showYamlInput}
              onClick={() => {
                setShowYamlInput((current) => !current);
                setShowTemplatePicker(false);
              }}
            />
            <Button variant="ghost" size="icon" className="h-9 w-9 rounded-none" onClick={onClose}>
              <X className="h-4 w-4" />
            </Button>
          </div>
        </div>

        <div className="mt-5 flex items-center gap-3">
          <div className="inline-flex h-10 w-10 shrink-0 items-center justify-center text-slate-700 dark:text-zinc-200">
            <Plus className="h-5 w-5" />
          </div>
          <h2 className="text-[28px] font-semibold leading-8 tracking-tight text-slate-950 dark:text-zinc-50">Setup Code</h2>
        </div>

        <div className="mt-3 w-full">
          <p className="w-full text-sm leading-6 text-slate-500 break-normal [word-break:normal] [overflow-wrap:normal] dark:text-zinc-400">
            Create an installed code on <span className="font-medium text-slate-700 dark:text-zinc-200">{computerLabel}</span>.
          </p>
        </div>

        {showTemplatePicker || showYamlInput ? (
          <div className="mt-5 grid gap-3 border-t border-slate-100 pt-4 dark:border-zinc-800">
            {showTemplatePicker ? (
              <div className="space-y-2">
                <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-zinc-400">
                  <Copy className="h-3.5 w-3.5" />
                  Import From Existing Code
                </div>
                <CommandPaletteSelect
                  value={selectedTemplatePk}
                  options={templateOptions}
                  disabled={isFetchingTemplates || templates.length === 0}
                  ariaLabel="Select code template"
                  searchable={templates.length > 5}
                  className="w-full"
                  triggerClassName="flex w-full items-center justify-between rounded-none px-0 py-2.5 text-sm"
                  onChange={handleTemplateChange}
                />
                <p className="text-xs text-slate-500 dark:text-zinc-400">
                  Reuse an existing code definition as a starting point, then adjust label or executable path as needed.
                </p>
              </div>
            ) : null}

            {showYamlInput ? (
              <div className="space-y-3">
                <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-zinc-400">
                  <FileCode className="h-3.5 w-3.5" />
                  Paste Configuration
                </div>
                <textarea
                  value={yamlInput}
                  onChange={(event) => setYamlInput(event.target.value)}
                  placeholder={"label: qe-750-ph\ndefault_calc_job_plugin: quantumespresso.ph\nfilepath_executable: /path/to/ph.x\nprepend_text: |\n  module load EasyBuild\n  module load Cray"}
                  className={`${baseTextareaClassName} min-h-[136px] bg-slate-950 px-3 py-3 text-slate-100 placeholder:text-slate-500 dark:border-zinc-700`}
                />
                <div className="flex items-center justify-end gap-2">
                  <Button variant="ghost" size="sm" className="h-9 rounded-none px-4" onClick={() => setShowYamlInput(false)}>
                    Close
                  </Button>
                  <Button size="sm" className="h-9 rounded-none px-4" onClick={handleApplyYaml}>
                    <Wand2 className="h-3.5 w-3.5" />
                    Apply Import
                  </Button>
                </div>
                <p className="text-xs text-slate-500 dark:text-zinc-400">
                  Supports standard YAML for code exports and pasted config snippets, including multi-line `prepend_text` and `append_text`.
                </p>
              </div>
            ) : null}
          </div>
        ) : null}
      </header>

      <form className="flex min-h-0 flex-1 flex-col" onSubmit={handleSubmit}>
        <div className="flex-1 overflow-y-auto px-6 py-5">
          <div className="space-y-5">
            <SectionBlock title="Identity" description="Give the code a clear label and optional context for your team.">
              <div>
                <FieldLabel
                  label="Label"
                  required
                  hint="The label must be unique on the selected computer. Pasted configs often need a fresh label."
                />
                <input
                  value={formData.label}
                  onChange={(event) => setFormData({ ...formData, label: event.target.value })}
                  className={baseInputClassName}
                  placeholder="e.g. qe-750-epw-v2"
                  required
                />
                <FieldHint>Use a short, searchable label that distinguishes versions or environments.</FieldHint>
              </div>

              <div className="md:col-span-1">
                <FieldLabel label="Description" hint="Optional notes shown alongside the code in AiiDA." />
                <input
                  value={formData.description}
                  onChange={(event) => setFormData({ ...formData, description: event.target.value })}
                  className={baseInputClassName}
                  placeholder="Optional context"
                />
              </div>
            </SectionBlock>

            <SectionBlock title="Technical" description="Bind this code to the computer, plugin, and executable location.">
              <div>
                <FieldLabel label="Computer" />
                <div className={`${baseInputClassName} flex items-center gap-2 text-slate-500 dark:text-zinc-400`}>
                  <Terminal className="h-4 w-4" />
                  <span>{computerLabel}</span>
                </div>
                <FieldHint>Installed codes are scoped to a single computer.</FieldHint>
              </div>

              <div>
                <FieldLabel
                  label="Input Plugin"
                  required
                  hint="For example `quantumespresso.pw` or `quantumespresso.epw`."
                />
                <input
                  value={formData.default_calc_job_plugin}
                  onChange={(event) => setFormData({ ...formData, default_calc_job_plugin: event.target.value })}
                  className={`${baseInputClassName} font-mono`}
                  placeholder="plugin.calcjob"
                  required
                />
              </div>

              <div className="md:col-span-2">
                <FieldLabel
                  label="Executable Path"
                  required
                  hint="Absolute path on the remote machine to the executable binary."
                />
                <input
                  value={formData.remote_abspath}
                  onChange={(event) => setFormData({ ...formData, remote_abspath: event.target.value })}
                  className={`${baseInputClassName} font-mono`}
                  placeholder="/path/to/executable"
                  required
                />
                <FieldHint>This panel creates `InstalledCode` entries. `store-in-db` code folders are intentionally left out here.</FieldHint>
              </div>
            </SectionBlock>

            <section className="overflow-hidden border-t border-slate-100 dark:border-zinc-800">
              <button
                type="button"
                onClick={() => setIsAdvancedOpen((current) => !current)}
                className="flex w-full items-center justify-between px-4 py-4 text-left"
              >
                <div>
                  <div className="flex items-center gap-2">
                    <Settings2 className="h-4 w-4 text-slate-500 dark:text-zinc-400" />
                    <h3 className="text-sm font-semibold text-slate-900 dark:text-zinc-100">Advanced Configuration</h3>
                  </div>
                  <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-zinc-400">
                    Optional execution behavior, quoting, and environment bootstrap commands.
                  </p>
                </div>
                <ChevronDown
                  className={cn(
                    "h-4 w-4 text-slate-500 transition-transform dark:text-zinc-400",
                    isAdvancedOpen && "rotate-180",
                  )}
                />
              </button>

              {isAdvancedOpen ? (
                <div className="border-t border-slate-200 px-0 py-4 dark:border-zinc-800">
                  <div className="grid grid-cols-1 gap-x-4 gap-y-5 md:grid-cols-2">
                    <ToggleTile
                      label="Use MPI"
                      description="Enable MPI execution for this installed code."
                      value={Boolean(formData.with_mpi)}
                      onToggle={() => setFormData({ ...formData, with_mpi: !Boolean(formData.with_mpi) })}
                    />
                    <ToggleTile
                      label="Double Quote Path"
                      description="Quote the executable path when commands are rendered."
                      value={formData.use_double_quotes}
                      onToggle={() => setFormData({ ...formData, use_double_quotes: !formData.use_double_quotes })}
                    />

                    <div className="md:col-span-2">
                      <FieldLabel label="Prepend Text" hint="Commands run before the executable, such as loading modules." />
                      <textarea
                        value={formData.prepend_text}
                        onChange={(event) => setFormData({ ...formData, prepend_text: event.target.value })}
                        className={baseTextareaClassName}
                        placeholder="module load qe/7.5"
                      />
                    </div>

                    <div className="md:col-span-2">
                      <FieldLabel label="Append Text" hint="Optional commands run after the executable completes." />
                      <textarea
                        value={formData.append_text}
                        onChange={(event) => setFormData({ ...formData, append_text: event.target.value })}
                        className={`${baseTextareaClassName} min-h-[92px]`}
                        placeholder="Optional cleanup"
                      />
                    </div>
                  </div>
                </div>
              ) : null}
            </section>

            {error ? (
              <div className="border-t border-rose-200 px-0 py-3 text-sm text-rose-700 dark:border-rose-900/50 dark:text-rose-300">
                {error}
              </div>
            ) : null}

            {success ? (
              <div className="border-t border-emerald-200 px-0 py-3 text-sm text-emerald-700 dark:border-emerald-900/50 dark:text-emerald-300">
                {success}
              </div>
            ) : null}
          </div>
        </div>

        <footer className="sticky bottom-0 flex items-center justify-end gap-3 border-t border-slate-200 bg-white/95 px-6 py-4 backdrop-blur dark:border-zinc-800 dark:bg-zinc-950/95">
          <Button variant="ghost" onClick={onClose} disabled={isLoading} className="rounded-none px-4">
            Cancel
          </Button>
          <Button type="submit" disabled={isLoading} className="rounded-none bg-blue-600 px-5 text-white hover:bg-blue-700">
            {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
            Save Code
          </Button>
        </footer>
      </form>
    </section>
  );
}
