import { Check, ChevronDown, Search } from "lucide-react";
import {
  type CSSProperties,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";

import { cn } from "@/lib/utils";

export type CommandPaletteSelectOption = {
  value: string;
  label: string;
  description?: string | null;
  keywords?: string[];
  disabled?: boolean;
};

type CommandPaletteSelectProps = {
  value: string;
  options: CommandPaletteSelectOption[];
  onChange: (value: string) => void;
  label?: string;
  icon?: React.ReactNode;
  placeholder?: string;
  fallbackLabel?: string;
  emptyLabel?: string;
  searchPlaceholder?: string;
  disabled?: boolean;
  searchable?: boolean;
  className?: string;
  triggerClassName?: string;
  labelClassName?: string;
  valueClassName?: string;
  menuClassName?: string;
  optionClassName?: string;
  minMenuWidth?: number;
  align?: "start" | "end";
  ariaLabel?: string;
};

type MenuPosition = {
  left: number;
  width: number;
  top?: number;
  bottom?: number;
  maxHeight: number;
};

const VIEWPORT_PADDING = 12;
const DEFAULT_MIN_MENU_WIDTH = 240;
const DEFAULT_MAX_MENU_HEIGHT = 320;

function normalizeText(value: string): string {
  return value.trim().toLowerCase();
}

export function CommandPaletteSelect({
  value,
  options,
  onChange,
  label,
  icon,
  placeholder = "Select",
  fallbackLabel,
  emptyLabel = "No options available",
  searchPlaceholder = "Search options",
  disabled = false,
  searchable = true,
  className,
  triggerClassName,
  labelClassName,
  valueClassName,
  menuClassName,
  optionClassName,
  minMenuWidth = DEFAULT_MIN_MENU_WIDTH,
  align = "start",
  ariaLabel,
}: CommandPaletteSelectProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [menuPosition, setMenuPosition] = useState<MenuPosition | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const listboxId = useId();

  const selectedOption = useMemo(
    () => options.find((option) => option.value === value) ?? null,
    [options, value],
  );
  const selectedLabel = selectedOption?.label ?? fallbackLabel ?? placeholder;
  const isSearchEnabled = searchable ?? options.length > 8;

  const filteredOptions = useMemo(() => {
    const normalizedQuery = normalizeText(query);
    if (!normalizedQuery) {
      return options;
    }
    return options.filter((option) => {
      const haystacks = [
        option.label,
        option.value,
        option.description ?? "",
        ...(option.keywords ?? []),
      ];
      return haystacks.some((entry) => normalizeText(entry).includes(normalizedQuery));
    });
  }, [options, query]);

  useEffect(() => {
    if (!isOpen) {
      setQuery("");
      return;
    }
    if (isSearchEnabled) {
      const frame = requestAnimationFrame(() => {
        searchRef.current?.focus();
        searchRef.current?.select();
      });
      return () => cancelAnimationFrame(frame);
    }
  }, [isOpen, isSearchEnabled]);

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    const updateMenuPosition = () => {
      const trigger = triggerRef.current;
      if (!trigger) {
        return;
      }
      const rect = trigger.getBoundingClientRect();
      const width = Math.min(
        Math.max(rect.width, minMenuWidth),
        window.innerWidth - VIEWPORT_PADDING * 2,
      );
      const availableBelow = window.innerHeight - rect.bottom - VIEWPORT_PADDING;
      const availableAbove = rect.top - VIEWPORT_PADDING;
      const openUpward = availableBelow < 220 && availableAbove > availableBelow;
      const maxHeight = Math.min(
        DEFAULT_MAX_MENU_HEIGHT,
        Math.max(140, (openUpward ? availableAbove : availableBelow) - 8),
      );
      const unclampedLeft = align === "end" ? rect.right - width : rect.left;
      const left = Math.min(
        Math.max(VIEWPORT_PADDING, unclampedLeft),
        window.innerWidth - width - VIEWPORT_PADDING,
      );

      setMenuPosition({
        left,
        width,
        top: openUpward ? undefined : rect.bottom + 8,
        bottom: openUpward ? window.innerHeight - rect.top + 8 : undefined,
        maxHeight,
      });
    };

    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (
        target &&
        (triggerRef.current?.contains(target) || menuRef.current?.contains(target))
      ) {
        return;
      }
      setIsOpen(false);
    };

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsOpen(false);
        triggerRef.current?.focus();
      }
    };

    updateMenuPosition();
    window.addEventListener("resize", updateMenuPosition);
    window.addEventListener("scroll", updateMenuPosition, true);
    window.addEventListener("pointerdown", handlePointerDown);
    window.addEventListener("keydown", handleEscape);

    return () => {
      window.removeEventListener("resize", updateMenuPosition);
      window.removeEventListener("scroll", updateMenuPosition, true);
      window.removeEventListener("pointerdown", handlePointerDown);
      window.removeEventListener("keydown", handleEscape);
    };
  }, [align, isOpen, minMenuWidth]);

  const menu = isOpen && menuPosition && typeof document !== "undefined"
    ? createPortal(
        <div
          ref={menuRef}
          role="dialog"
          aria-label={ariaLabel ?? label ?? placeholder}
          className={cn(
            "fixed z-[120] flex flex-col overflow-hidden rounded-2xl border border-zinc-200/85 bg-white/96 shadow-[0_18px_48px_-24px_rgba(15,23,42,0.45)] backdrop-blur-xl dark:border-zinc-800 dark:bg-zinc-950/96",
            menuClassName,
          )}
          style={{
            left: menuPosition.left,
            width: menuPosition.width,
            top: menuPosition.top,
            bottom: menuPosition.bottom,
            maxHeight: menuPosition.maxHeight,
          } satisfies CSSProperties}
        >
          {isSearchEnabled ? (
            <div className="border-b border-zinc-200/80 px-3 py-2 dark:border-zinc-800">
              <label className="relative flex items-center">
                <Search className="pointer-events-none absolute left-0.5 h-3.5 w-3.5 text-zinc-400" />
                <input
                  ref={searchRef}
                  value={query}
                  onChange={(event) => setQuery(event.currentTarget.value)}
                  placeholder={searchPlaceholder}
                  className="w-full border-0 bg-transparent pl-5 pr-1 text-sm text-zinc-700 outline-none placeholder:text-zinc-400 dark:text-zinc-200"
                />
              </label>
            </div>
          ) : null}
          <div id={listboxId} role="listbox" className="min-h-0 overflow-y-auto py-1.5">
            {filteredOptions.length > 0 ? (
              filteredOptions.map((option) => {
                const isSelected = option.value === value;
                return (
                  <button
                    key={`${option.value}-${option.label}`}
                    type="button"
                    role="option"
                    aria-selected={isSelected}
                    disabled={option.disabled}
                    className={cn(
                      "flex w-full items-start gap-2 px-3 py-2 text-left text-sm transition-colors",
                      option.disabled
                        ? "cursor-not-allowed text-zinc-400 dark:text-zinc-600"
                        : isSelected
                          ? "bg-zinc-100/90 text-zinc-950 dark:bg-zinc-800/80 dark:text-zinc-50"
                          : "text-zinc-700 hover:bg-zinc-100/80 hover:text-zinc-950 dark:text-zinc-200 dark:hover:bg-zinc-900/80 dark:hover:text-zinc-50",
                      optionClassName,
                    )}
                    onClick={() => {
                      if (option.disabled || option.value === value) {
                        setIsOpen(false);
                        return;
                      }
                      onChange(option.value);
                      setIsOpen(false);
                    }}
                  >
                    <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center">
                      {isSelected ? <Check className="h-3.5 w-3.5" /> : null}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate">{option.label}</span>
                      {option.description ? (
                        <span className="mt-0.5 block text-xs text-zinc-500 dark:text-zinc-400">
                          {option.description}
                        </span>
                      ) : null}
                    </span>
                  </button>
                );
              })
            ) : (
              <div className="px-3 py-3 text-sm text-zinc-500 dark:text-zinc-400">
                {emptyLabel}
              </div>
            )}
          </div>
        </div>,
        document.body,
      )
    : null;

  return (
    <>
      <div className={cn("min-w-0", className)}>
        <button
          ref={triggerRef}
          type="button"
          disabled={disabled}
          aria-haspopup="dialog"
          aria-expanded={isOpen}
          aria-controls={isOpen ? listboxId : undefined}
          aria-label={ariaLabel ?? label ?? placeholder}
          className={cn(
            "inline-flex max-w-full items-center justify-start gap-1 rounded-md px-1 py-0.5 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-zinc-400/70 focus-visible:ring-offset-1 dark:focus-visible:ring-zinc-500/70 dark:focus-visible:ring-offset-zinc-950 disabled:pointer-events-none disabled:opacity-50",
            "text-zinc-600 hover:bg-zinc-100/80 hover:text-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-900/70 dark:hover:text-zinc-100",
            triggerClassName,
          )}
          onClick={() => setIsOpen((current) => !current)}
        >
          {icon ? (
            <span className={cn("shrink-0", labelClassName || "text-zinc-500 dark:text-zinc-400")}>{icon}</span>
          ) : label ? (
            <span className={cn("shrink-0", labelClassName || "text-zinc-500 dark:text-zinc-400")}>{label}:</span>
          ) : null}
          <span className={cn("min-w-0 flex-1 truncate text-left font-medium", valueClassName || "text-zinc-900 dark:text-zinc-100")}>
            {selectedLabel}
          </span>
          <ChevronDown
            className={cn(
              "ml-auto h-3.5 w-3.5 shrink-0 transition-transform",
              isOpen && "rotate-180",
            )}
          />
        </button>
      </div>
      {menu}
    </>
  );
}
