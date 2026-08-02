import { useEffect, useRef } from "react";

type RuntimeTerminalProps = {
  lines: string[];
};

export function RuntimeTerminal({ lines }: RuntimeTerminalProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return;
    }
    container.scrollTop = container.scrollHeight;
  }, [lines]);

  return (
    <section className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden bg-zinc-950 text-zinc-200">
      <div className="flex h-8 shrink-0 items-center border-b border-zinc-800 px-4">
        <p className="text-[10px] font-medium uppercase tracking-[0.16em] text-zinc-500">
          Terminal
        </p>
      </div>

      <div
        ref={containerRef}
        className="minimal-scrollbar min-h-0 flex-1 overflow-auto px-4 py-2 font-mono text-xs leading-5 text-zinc-300"
      >
        {lines.length === 0 ? (
          <p className="text-zinc-600">No runtime logs yet.</p>
        ) : (
          lines.map((line, index) => (
            <div key={`${index}-${line.slice(0, 20)}`} className="whitespace-nowrap">
              {line}
            </div>
          ))
        )}
      </div>
    </section>
  );
}
