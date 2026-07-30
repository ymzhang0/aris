import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import CodeMirror from "@uiw/react-codemirror";
import { vscodeDark, vscodeLight } from "@uiw/codemirror-theme-vscode";
import { EditorView } from "@codemirror/view";
import { AlertCircle, CheckCircle2, Loader2, Play, Save, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { executeChatProjectFile, fetchFileContent, saveChatProjectFile } from "@/api";
import { cn } from "@/lib/utils";

import type { WorkspaceExplorerFileSelection } from "./workspace-explorer-sidebar";

type CodeViewerProps = {
  file: WorkspaceExplorerFileSelection;
  theme: "light" | "dark";
  onClose: () => void;
};

type FeedbackTone = "idle" | "success" | "error" | "running";

function formatBreadcrumbs(path: string): string[] {
  return String(path || "")
    .replace(/\\/g, "/")
    .split("/")
    .filter(Boolean);
}

function buildEditorChromeTheme(theme: "light" | "dark") {
  const dark = theme === "dark";
  return EditorView.theme(
    {
      "&": {
        height: "100%",
        backgroundColor: dark ? "#1e1e1e" : "#f8fafc",
        color: dark ? "#d4d4d4" : "#0f172a",
      },
      ".cm-editor": {
        height: "100%",
      },
      ".cm-content": {
        caretColor: dark ? "#ffffff" : "#0f172a",
        fontFamily: "ui-monospace, SFMono-Regular, SF Mono, Menlo, Consolas, monospace",
        fontSize: "13px",
      },
      ".cm-cursor, .cm-dropCursor": {
        borderLeftColor: dark ? "#ffffff" : "#0f172a",
      },
      ".cm-activeLine": {
        backgroundColor: dark ? "rgba(255,255,255,0.04)" : "rgba(15,23,42,0.04)",
      },
      ".cm-selectionBackground, &.cm-focused .cm-selectionBackground, ::selection": {
        backgroundColor: dark ? "rgba(38, 79, 120, 0.8)" : "rgba(59, 130, 246, 0.22)",
      },
      ".cm-gutters": {
        backgroundColor: dark ? "#181818" : "#f1f5f9",
        color: dark ? "#858585" : "#64748b",
        borderRight: dark ? "1px solid #2b2b2b" : "1px solid #e2e8f0",
        minHeight: "100%",
      },
      ".cm-activeLineGutter": {
        backgroundColor: dark ? "#181818" : "#f1f5f9",
      },
      ".cm-scroller": {
        overflow: "auto",
        minHeight: "100%",
      },
    },
    { dark },
  );
}

export function CodeViewer({ file, theme, onClose }: CodeViewerProps) {
  const fileKey = `${file.projectId}:${file.relativePath}`;
  const [draftContent, setDraftContent] = useState("");
  const [savedContent, setSavedContent] = useState("");
  const [feedback, setFeedback] = useState<{ tone: FeedbackTone; message: string }>({
    tone: "idle",
    message: "Ready",
  });

  const contentQuery = useQuery({
    queryKey: ["project-file-content", file.projectId, file.relativePath],
    queryFn: () => fetchFileContent(file.projectId, file.relativePath),
    enabled: Boolean(file.projectId && file.relativePath),
    refetchOnWindowFocus: false,
  });

  useEffect(() => {
    if (!contentQuery.data) {
      return;
    }

    setDraftContent(contentQuery.data.content);
    setSavedContent(contentQuery.data.content);
    setFeedback({ tone: "idle", message: "Loaded from workspace" });
  }, [contentQuery.data, fileKey]);

  const saveMutation = useMutation({
    mutationFn: (content: string) =>
      saveChatProjectFile(file.projectId, {
        relative_path: file.relativePath,
        content,
        overwrite: true,
      }),
    onMutate: () => {
      setFeedback({ tone: "running", message: "Saving..." });
    },
    onSuccess: (_result, content) => {
      setSavedContent(content);
      setFeedback({ tone: "success", message: "Saved" });
    },
    onError: (error) => {
      setFeedback({
        tone: "error",
        message: error instanceof Error ? error.message : "Failed to save file",
      });
    },
  });

  const runMutation = useMutation({
    mutationFn: () => executeChatProjectFile(file.projectId, file.relativePath),
    onMutate: () => {
      setFeedback({ tone: "running", message: "Running..." });
    },
    onSuccess: (result) => {
      setFeedback({
        tone: result.status === "completed" ? "success" : "error",
        message: result.status === "completed" ? "Run completed" : "Run failed",
      });
    },
    onError: (error) => {
      setFeedback({
        tone: "error",
        message: error instanceof Error ? error.message : "Failed to execute file",
      });
    },
  });

  const isDirty = draftContent !== savedContent;
  const breadcrumbItems = useMemo(() => formatBreadcrumbs(file.path), [file.path]);
  const editorTheme = useMemo(() => buildEditorChromeTheme(theme), [theme]);

  const feedbackIcon =
    feedback.tone === "running" ? (
      <Loader2 className="h-3.5 w-3.5 animate-spin" />
    ) : feedback.tone === "success" ? (
      <CheckCircle2 className="h-3.5 w-3.5" />
    ) : feedback.tone === "error" ? (
      <AlertCircle className="h-3.5 w-3.5" />
    ) : null;

  return (
    <section className="absolute inset-0 flex min-h-0 flex-col overflow-hidden bg-white dark:bg-[#1e1e1e]">
      <header className="shrink-0 border-b border-slate-200/80 bg-white px-4 py-3 dark:border-[#313131] dark:bg-[#252526]">
        <div className="flex items-center justify-between gap-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-1 text-[11px] text-slate-500 dark:text-[#8c8c8c]">
              {breadcrumbItems.map((segment, index) => (
                <span key={`${segment}-${index}`} className="flex items-center gap-1">
                  {index > 0 ? <span className="text-slate-300 dark:text-[#5a5a5a]">/</span> : null}
                  <span className={cn(index === breadcrumbItems.length - 1 && "text-slate-800 dark:text-[#d4d4d4]")}>
                    {segment}
                  </span>
                </span>
              ))}
            </div>
            <p className="mt-1 truncate text-sm font-medium text-slate-900 dark:text-[#d4d4d4]">
              {file.relativePath}
            </p>
          </div>

          <div className="flex items-center gap-2">
            <span
              className={cn(
                "inline-flex max-w-52 items-center gap-1.5 truncate rounded-full px-2.5 py-1 text-[11px]",
                feedback.tone === "success" && "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
                feedback.tone === "error" && "bg-rose-500/10 text-rose-700 dark:text-rose-300",
                feedback.tone === "running" && "bg-amber-500/10 text-amber-700 dark:text-amber-300",
                feedback.tone === "idle" && "bg-slate-200/70 text-slate-600 dark:bg-white/5 dark:text-[#8c8c8c]",
              )}
            >
              {feedbackIcon}
              <span className="truncate">{feedback.message}</span>
            </span>

            <Button
              variant="outline"
              size="sm"
              className="rounded-md"
              onClick={() => {
                void runMutation.mutateAsync();
              }}
              disabled={runMutation.isPending}
            >
              {runMutation.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
              Run
            </Button>

            <Button
              variant="outline"
              size="sm"
              className="rounded-md"
              onClick={() => {
                void saveMutation.mutateAsync(draftContent);
              }}
              disabled={!isDirty || saveMutation.isPending}
            >
              {saveMutation.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
              Save
            </Button>

            <Button variant="ghost" size="sm" className="rounded-md" onClick={onClose}>
              <X className="h-3.5 w-3.5" />
              Close
            </Button>
          </div>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-hidden">
        {contentQuery.isPending ? (
          <div className="flex h-full items-center justify-center gap-2 text-sm text-slate-500 dark:text-slate-400">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading file content...
          </div>
        ) : contentQuery.isError ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 text-sm text-rose-600 dark:text-rose-300">
            <p>Failed to load file content.</p>
            <Button variant="outline" size="sm" onClick={() => void contentQuery.refetch()}>
              Retry
            </Button>
          </div>
        ) : (
          <div className="min-h-0 h-full overflow-hidden [&_.cm-editor]:h-full [&_.cm-focused]:outline-none [&_.cm-scroller]:font-mono">
            <CodeMirror
              className="h-full"
              value={draftContent}
              height="100%"
              theme={theme === "dark" ? vscodeDark : vscodeLight}
              basicSetup={{
                lineNumbers: true,
                highlightActiveLine: true,
                highlightActiveLineGutter: true,
                foldGutter: true,
              }}
              extensions={[editorTheme]}
              onChange={(value) => {
                setDraftContent(value);
                setFeedback({ tone: "idle", message: value === savedContent ? "Ready" : "Unsaved changes" });
              }}
            />
          </div>
        )}
      </div>
    </section>
  );
}
