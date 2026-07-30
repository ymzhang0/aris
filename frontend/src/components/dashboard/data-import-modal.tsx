import { aiidaClient } from "@/api";

import React, { useState, useEffect, useMemo } from "react";
import {
    X,
    Upload,
    Loader2,
    CheckCircle2,
    AlertCircle,
    FileText,
    Database,
    Tag,
    AlignLeft,
    Search,
    ChevronDown,
    FileCode,
    Package
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { addNodesToGroup, createGroup } from "@/api";

type DataImportModalProps = {
    isOpen: boolean;
    onClose: () => void;
    onSuccess: (pk: number) => void;
    groupPk?: number;
    groupLabel?: string;
};

const DATA_TYPES = [
    { id: "StructureData", label: "Structure", description: "Crystal structures (.cif, .xyz, .poscar)", icon: Database },
    { id: "Dict", label: "Dictionary", description: "Key-value data (.json, .yaml)", icon: FileCode },
    { id: "ArrayData", label: "Array", description: "Tabular data (.csv)", icon: Database },
    { id: "KpointsData", label: "K-points", description: "Brillouin zone sampling (.json, .csv)", icon: Database },
    { id: "Archive", label: "AiiDA Archive", description: "Internal AiiDA export (.aiida)", icon: Package },
];

export function DataImportModal({ isOpen, onClose, onSuccess, groupPk, groupLabel }: DataImportModalProps) {
    const [dataType, setDataType] = useState("StructureData");
    const [sourceType, setSourceType] = useState<"file" | "raw_text">("file");
    const [file, setFile] = useState<File | null>(null);
    const [rawText, setRawText] = useState("");
    const [label, setLabel] = useState("");
    const [description, setDescription] = useState("");
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const [searchQuery, setSearchQuery] = useState("");
    const [isDropdownOpen, setIsDropdownOpen] = useState(false);

    const filteredTypes = useMemo(() => {
        return DATA_TYPES.filter(t =>
            t.label.toLowerCase().includes(searchQuery.toLowerCase()) ||
            t.description.toLowerCase().includes(searchQuery.toLowerCase())
        );
    }, [searchQuery]);

    const selectedType = DATA_TYPES.find(t => t.id === dataType) || DATA_TYPES[0];

    useEffect(() => {
        if (!isOpen) {
            setSearchQuery("");
            setIsDropdownOpen(false);
        }
    }, [isOpen]);

    const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        if (e.target.files && e.target.files[0]) {
            const selectedFile = e.target.files[0];
            setFile(selectedFile);

            // Auto-detect Archive type
            if (selectedFile.name.endsWith(".aiida")) {
                setDataType("Archive");
            }

            // Auto-fill label if empty
            if (!label) {
                setLabel(selectedFile.name.split('.')[0]);
            }
        }
    };

    const handleSubmit = async () => {
        if (sourceType === "file" && !file) {
            setError("Please select a file to import.");
            return;
        }
        if (sourceType === "raw_text" && !rawText) {
            setError("Please enter data text.");
            return;
        }

        setIsSubmitting(true);
        setError(null);

        try {
            const result = await aiidaClient.importData(dataType, file, label, description, sourceType, rawText);

            // If it's an archive, it doesn't return a single PK usually, or returns a success status
            if (dataType === "Archive") {
                onSuccess(0); // special value for refresh
                onClose();
                return;
            }

            // If groupPk is provided, add the node to the group
            const pk = (result as any).pk;
            if (pk) {
                if (groupPk) {
                    await addNodesToGroup(groupPk, [pk]);
                } else if (groupLabel) {
                    const groupResult = await createGroup(groupLabel);
                    if (groupResult.item) {
                        await addNodesToGroup(groupResult.item.pk, [pk]);
                    }
                }
                onSuccess(pk);
            } else {
                onSuccess(0);
            }

            onClose();
            // Reset state
            setFile(null);
            setRawText("");
            setLabel("");
            setDescription("");
        } catch (err: any) {
            setError(err.response?.data?.detail || "Import failed. Please check the format.");
        } finally {
            setIsSubmitting(false);
        }
    };

    if (!isOpen) return null;

    const showRawTextToggle = dataType === "Dict";

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm animate-in fade-in duration-200">
            <div className="bg-white dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-800 rounded-2xl shadow-2xl w-full max-w-lg overflow-hidden flex flex-col max-h-[90vh]">
                <header className="px-6 py-4 border-b border-zinc-100 dark:border-zinc-900 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                        <div className="p-2 bg-zinc-100 dark:bg-zinc-900 rounded-lg">
                            <Upload className="h-5 w-5 text-zinc-600 dark:text-zinc-400" />
                        </div>
                        <div>
                            <h2 className="text-xl font-semibold tracking-tight">Import Data</h2>
                            {groupLabel && (
                                <p className="text-xs text-zinc-500 font-medium truncate max-w-[200px]">
                                    Adding to group: <span className="text-blue-500">{groupLabel}</span>
                                </p>
                            )}
                        </div>
                    </div>
                    <Button variant="ghost" size="icon" onClick={onClose}>
                        <X className="h-5 w-5" />
                    </Button>
                </header>

                <div className="flex-1 overflow-y-auto p-6 space-y-6">
                    {/* Data Type Searchable Selection */}
                    <div className="space-y-2.5 relative">
                        <label className="text-xs font-bold text-zinc-400 uppercase tracking-wider flex items-center gap-2">
                            <Database className="h-3.5 w-3.5" />
                            Data Type
                        </label>
                        <div className="relative">
                            <button
                                onClick={() => setIsDropdownOpen(!isDropdownOpen)}
                                className="w-full flex items-center justify-between bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl px-4 py-3 text-sm focus:ring-2 focus:ring-blue-500/10 transition-all hover:bg-zinc-100 dark:hover:bg-zinc-800/60"
                            >
                                <div className="flex items-center gap-3">
                                    <selectedType.icon className="h-4 w-4 text-blue-500" />
                                    <div className="flex flex-col items-start lg:min-w-[120px]">
                                        <span className="font-semibold text-zinc-800 dark:text-zinc-200">{selectedType.label}</span>
                                        <span className="text-[10px] text-zinc-400 line-clamp-1">{selectedType.description}</span>
                                    </div>
                                </div>
                                <ChevronDown className={cn("h-4 w-4 text-zinc-400 transition-transform", isDropdownOpen && "rotate-180")} />
                            </button>

                            {isDropdownOpen && (
                                <div className="absolute top-full left-0 right-0 mt-2 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl shadow-xl z-10 overflow-hidden animate-in zoom-in-95 duration-100 origin-top">
                                    <div className="p-2 border-b border-zinc-100 dark:border-zinc-800">
                                        <div className="relative">
                                            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-zinc-400" />
                                            <input
                                                autoFocus
                                                placeholder="Search types..."
                                                value={searchQuery}
                                                onChange={(e) => setSearchQuery(e.target.value)}
                                                className="w-full bg-zinc-100 dark:bg-zinc-800/50 border-none rounded-lg pl-9 pr-3 py-2 text-xs focus:ring-0 outline-none"
                                            />
                                        </div>
                                    </div>
                                    <div className="max-h-60 overflow-y-auto p-1">
                                        {filteredTypes.map((type) => (
                                            <button
                                                key={type.id}
                                                onClick={() => {
                                                    setDataType(type.id);
                                                    setIsDropdownOpen(false);
                                                    if (type.id !== "Dict") setSourceType("file");
                                                }}
                                                className={cn(
                                                    "w-full flex flex-col items-start p-2.5 rounded-lg text-left transition-colors",
                                                    dataType === type.id
                                                        ? "bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400"
                                                        : "hover:bg-zinc-100 dark:hover:bg-zinc-800/60"
                                                )}
                                            >
                                                <span className="text-sm font-medium">{type.label}</span>
                                                <span className="text-[10px] text-zinc-400 line-clamp-1">{type.description}</span>
                                            </button>
                                        ))}
                                        {filteredTypes.length === 0 && (
                                            <div className="py-8 text-center text-xs text-zinc-400">No types found</div>
                                        )}
                                    </div>
                                </div>
                            )}
                        </div>
                    </div>

                    {/* Source Selection (Conditional) */}
                    {showRawTextToggle && (
                        <div className="flex p-1 bg-zinc-100 dark:bg-zinc-900 rounded-xl">
                            <button
                                onClick={() => setSourceType("file")}
                                className={cn(
                                    "flex-1 flex items-center justify-center gap-2 py-2 text-xs font-semibold rounded-lg transition-all",
                                    sourceType === "file"
                                        ? "bg-white dark:bg-zinc-800 shadow-sm text-zinc-800 dark:text-zinc-100"
                                        : "text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300"
                                )}
                            >
                                <FileText className="h-3.5 w-3.5" />
                                File Upload
                            </button>
                            <button
                                onClick={() => setSourceType("raw_text")}
                                className={cn(
                                    "flex-1 flex items-center justify-center gap-2 py-2 text-xs font-semibold rounded-lg transition-all",
                                    sourceType === "raw_text"
                                        ? "bg-white dark:bg-zinc-800 shadow-sm text-zinc-800 dark:text-zinc-100"
                                        : "text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300"
                                )}
                            >
                                <FileCode className="h-3.5 w-3.5" />
                                Raw Text
                            </button>
                        </div>
                    )}

                    {/* Input Area */}
                    <div className="space-y-3">
                        {sourceType === "file" ? (
                            <>
                                <label className="text-xs font-bold text-zinc-400 uppercase tracking-wider flex items-center gap-2">
                                    <FileText className="h-3.5 w-3.5" />
                                    Select File
                                </label>
                                <div
                                    className={cn(
                                        "relative border-2 border-dashed rounded-xl p-8 flex flex-col items-center justify-center transition-all cursor-pointer",
                                        file ? "border-emerald-200 bg-emerald-50/10 dark:border-emerald-900/30" : "border-zinc-200 dark:border-zinc-800 hover:bg-zinc-50 dark:hover:bg-zinc-900/30"
                                    )}
                                    onClick={() => document.getElementById('data-import-file')?.click()}
                                >
                                    <input
                                        id="data-import-file"
                                        type="file"
                                        className="hidden"
                                        onChange={handleFileChange}
                                        accept={dataType === "Archive" ? ".aiida" : undefined}
                                    />
                                    {file ? (
                                        <div className="flex flex-col items-center animate-in zoom-in-95">
                                            <div className="p-3 bg-emerald-100 dark:bg-emerald-900/30 rounded-full mb-3">
                                                <CheckCircle2 className="h-6 w-6 text-emerald-600" />
                                            </div>
                                            <span className="text-sm font-medium text-zinc-700 dark:text-zinc-200 text-center truncate max-w-[300px]">
                                                {file.name}
                                            </span>
                                            <span className="text-xs text-zinc-400 mt-1">
                                                {(file.size / 1024).toFixed(1)} KB
                                            </span>
                                        </div>
                                    ) : (
                                        <>
                                            <div className="p-3 bg-zinc-100 dark:bg-zinc-900 rounded-full mb-3">
                                                <Upload className="h-6 w-6 text-zinc-400" />
                                            </div>
                                            <span className="text-sm font-medium text-zinc-600 dark:text-zinc-400">
                                                Click or drag file to upload
                                            </span>
                                            <span className="text-[10px] text-zinc-400 mt-1 text-center">
                                                {dataType === "Archive" ? "Supports .aiida archives" : "Supported formats depend on data type"}
                                            </span>
                                        </>
                                    )}
                                </div>
                            </>
                        ) : (
                            <>
                                <label className="text-xs font-bold text-zinc-400 uppercase tracking-wider flex items-center gap-2">
                                    <FileCode className="h-3.5 w-3.5" />
                                    Raw Content
                                </label>
                                <textarea
                                    value={rawText}
                                    onChange={(e) => setRawText(e.target.value)}
                                    placeholder={dataType === "Dict" ? "Enter JSON or YAML content..." : "Enter data content..."}
                                    className="w-full h-40 bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-xl p-4 text-xs font-mono focus:ring-2 focus:ring-blue-500/10 focus:border-blue-500 outline-none transition-all resize-none shadow-inner"
                                />
                            </>
                        )}
                    </div>

                    {/* Metadata (Hide for Archive usually) */}
                    {dataType !== "Archive" && (
                        <div className="grid grid-cols-2 gap-4">
                            <div className="space-y-1.5">
                                <label className="text-xs font-bold text-zinc-400 uppercase tracking-wider flex items-center gap-2">
                                    <Tag className="h-3.5 w-3.5" />
                                    Label
                                </label>
                                <input
                                    value={label}
                                    onChange={(e) => setLabel(e.target.value)}
                                    placeholder="Enter node label..."
                                    className="w-full bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500/10 focus:border-blue-500 outline-none transition-all"
                                />
                            </div>
                            <div className="space-y-1.5">
                                <label className="text-xs font-bold text-zinc-400 uppercase tracking-wider flex items-center gap-2">
                                    <AlignLeft className="h-3.5 w-3.5" />
                                    Description
                                </label>
                                <input
                                    value={description}
                                    onChange={(e) => setDescription(e.target.value)}
                                    placeholder="Optional description..."
                                    className="w-full bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500/10 focus:border-blue-500 outline-none transition-all"
                                />
                            </div>
                        </div>
                    )}

                    {error && (
                        <div className="p-3 bg-rose-50 dark:bg-rose-900/20 border border-rose-100 dark:border-rose-900/30 rounded-xl flex gap-x-2 text-rose-600 dark:text-rose-400 text-sm animate-in slide-in-from-top-1">
                            <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
                            {error}
                        </div>
                    )}
                </div>

                <footer className="px-6 py-4 border-t border-zinc-100 dark:border-zinc-900 bg-zinc-50/50 dark:bg-zinc-900/50 flex items-center justify-end gap-3">
                    <Button variant="ghost" onClick={onClose} disabled={isSubmitting}>Cancel</Button>
                    <Button
                        disabled={(sourceType === "file" ? !file : !rawText) || isSubmitting}
                        onClick={handleSubmit}
                        className="bg-zinc-900 dark:bg-zinc-100 hover:bg-zinc-800 dark:hover:bg-zinc-200 text-white dark:text-zinc-900 rounded-xl px-6 gap-2"
                    >
                        {isSubmitting ? (
                            <>
                                <Loader2 className="h-4 w-4 animate-spin" />
                                Importing...
                            </>
                        ) : (
                            <>
                                <Upload className="h-4 w-4" />
                                Start Import
                            </>
                        )}
                    </Button>
                </footer>
            </div>
        </div>
    );
}
