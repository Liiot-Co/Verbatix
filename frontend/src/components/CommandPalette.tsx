import { useEffect, useState, useRef, useMemo } from "react";
import { createPortal } from "react-dom";
import { motion, AnimatePresence } from "framer-motion";
import { Search, Keyboard, ChevronRight } from "lucide-react";
import { modLabel } from "@/hooks/useKeyboardShortcuts";

interface CommandItem {
  label: string;
  description?: string;
  icon: string;
  shortcut?: string;
  action: () => void;
  keywords: string[];
  category: string;
}

function getCommands(): CommandItem[] {
  const m = () => modLabel();
  return [
    {
      label: "Ir al Dashboard",
      description: "Ver lista de proyectos",
      icon: "📊",
      shortcut: `${m()}⇧D`,
      action: () => window.location.href = "/",
      keywords: ["dashboard", "proyectos", "inicio", "home", "index"],
      category: "Navegación",
    },
    {
      label: "Nuevo proyecto",
      description: "Crear proyecto desde el wizard",
      icon: "✨",
      shortcut: `${m()}⇧N`,
      action: () => window.location.href = "/wizard",
      keywords: ["nuevo", "crear", "proyecto", "wizard", "asistente"],
      category: "Acciones",
    },
    {
      label: "Atrás",
      description: "Navegar a la página anterior",
      icon: "⬅️",
      shortcut: `${m()}←`,
      action: () => window.history.back(),
      keywords: ["atras", "back", "anterior", "volver", "retroceder"],
      category: "Navegación",
    },
    {
      label: "Adelante",
      description: "Navegar a la página siguiente",
      icon: "➡️",
      shortcut: `${m()}→`,
      action: () => window.history.forward(),
      keywords: ["adelante", "forward", "siguiente", "avanzar"],
      category: "Navegación",
    },
    {
      label: "Buscar",
      description: "Enfocar campo de búsqueda",
      icon: "🔍",
      shortcut: "/",
      action: () => {
        const input = document.querySelector('input[placeholder*="Buscar"]') as HTMLInputElement | null;
        input?.focus();
      },
      keywords: ["buscar", "search", "filtrar", "find", "localizar"],
      category: "Acciones",
    },
    {
      label: "Recargar página",
      description: "Actualizar la vista actual",
      icon: "🔄",
      shortcut: `${m()}R`,
      action: () => window.location.reload(),
      keywords: ["recargar", "refresh", "actualizar", "reload"],
      category: "Acciones",
    },
    {
      label: "Exportar resultados",
      icon: "📥",
      action: () => {},
      keywords: ["exportar", "export", "descargar", "excel"],
      category: "Acciones",
    },
    {
      label: "Buscar (alternativo)",
      description: `Usar ${modLabel()}⇧F`,
      icon: "🔍",
      shortcut: `${m()}⇧F`,
      action: () => {
        const input = document.querySelector('input[placeholder*="Buscar"]') as HTMLInputElement | null;
        input?.focus();
      },
      keywords: ["buscar", "search", "filtrar", "find", "localizar", "busqueda"],
      category: "Acciones",
    },
  ];
}

export function CommandPalette() {
  const [isOpen, setIsOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const toggle = () => setIsOpen((o) => !o);

  const cmds = useMemo(() => getCommands(), []);
  const filtered = cmds.filter((cmd) => {
    const q = query.toLowerCase().trim();
    if (!q) return true;
    return (
      cmd.label.toLowerCase().includes(q) ||
      cmd.description?.toLowerCase().includes(q) ||
      cmd.keywords.some((k) => k.includes(q)) ||
      cmd.shortcut?.toLowerCase().includes(q)
    );
  });

  const select = (idx: number) => {
    const cmd = filtered[idx];
    if (cmd) {
      cmd.action();
      setIsOpen(false);
    }
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        setSelectedIndex((i) => Math.min(i + 1, filtered.length - 1));
        break;
      case "ArrowUp":
        e.preventDefault();
        setSelectedIndex((i) => Math.max(i - 1, 0));
        break;
      case "Enter":
        e.preventDefault();
        select(selectedIndex);
        break;
      case "Escape":
        setIsOpen(false);
        break;
    }
  };

  const isMac = navigator.platform.includes("Mac");

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const mod = isMac ? e.metaKey : e.ctrlKey;
      if (mod && e.key === "k") {
        e.preventDefault();
        toggle();
      }
    };
    const onToggle = () => toggle();
    window.addEventListener("keydown", handler);
    window.addEventListener("toggle-command-palette", onToggle);
    return () => {
      window.removeEventListener("keydown", handler);
      window.removeEventListener("toggle-command-palette", onToggle);
    };
  }, []);

  useEffect(() => {
    if (isOpen) {
      setQuery("");
      setSelectedIndex(0);
      document.body.style.overflow = "hidden";
      setTimeout(() => inputRef.current?.focus(), 50);
    } else {
      document.body.style.overflow = "";
    }
    return () => {
      document.body.style.overflow = "";
    };
  }, [isOpen]);

  return createPortal(
    <AnimatePresence>
      {isOpen && (
        <div className="command-palette command-palette-open">
          <motion.div
            className="command-palette-backdrop"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => setIsOpen(false)}
          />
          <motion.div
            initial={{ opacity: 0, scale: 0.96, y: 8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: 8 }}
            transition={{ type: "spring", stiffness: 400, damping: 30 }}
            className="command-palette-panel"
            onClick={(e) => e.stopPropagation()}
            onKeyDown={onKeyDown}
          >
            {/* Search input */}
            <div className="flex items-center gap-3 px-4 py-3 border-b border-p-border">
              <Search className="w-5 h-5 text-p-text-faint shrink-0" />
              <input
                ref={inputRef}
                type="text"
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value);
                  setSelectedIndex(0);
                }}
                placeholder="Escribe un comando o busca..."
                className="flex-1 bg-transparent text-sm text-p-text placeholder-p-text-faint outline-none"
                autoComplete="off"
                spellCheck={false}
              />
              <kbd className="kbd-hint hidden sm:flex">
                <Keyboard className="w-3.5 h-3.5" />
                <span>K</span>
              </kbd>
            </div>

            {/* Results */}
            <AnimatePresence mode="wait">
              {filtered.length > 0 ? (
                <motion.ul
                  key="results"
                  className="max-h-[360px] overflow-y-auto scrollbar-thin p-2"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                >
                  {filtered.map((cmd, idx) => (
                    <motion.button
                      key={cmd.label + idx}
                      onClick={() => select(idx)}
                      onMouseEnter={() => setSelectedIndex(idx)}
                      className={`w-full flex items-center gap-3 px-3 py-2.5 text-left rounded-xl transition-all duration-150 ${
                        idx === selectedIndex
                          ? "bg-p-accent-soft text-p-accent"
                          : "text-p-text hover:bg-p-bg-subtle"
                      }`}
                      initial={{ opacity: 0, x: -10 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: idx * 0.02, duration: 0.15 }}
                    >
                      <span className="text-base shrink-0">{cmd.icon}</span>
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-medium truncate">{cmd.label}</div>
                        {cmd.description && (
                          <div className="text-xs text-p-text-muted truncate">{cmd.description}</div>
                        )}
                      </div>
                      {cmd.shortcut && (
                        <kbd className="kbd-hint shrink-0 ml-2">{cmd.shortcut}</kbd>
                      )}
                      <ChevronRight className="w-4 h-4 text-p-text-faint shrink-0 opacity-50" />
                    </motion.button>
                  ))}
                </motion.ul>
              ) : (
                <motion.div
                  key="empty"
                  className="px-4 py-8 text-center"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                >
                  <div className="text-2xl mb-2">🔍</div>
                  <div className="text-sm text-p-text-muted">No se encontraron comandos para "{query}"</div>
                </motion.div>
              )}
            </AnimatePresence>

            {/* Footer */}
            <div className="px-4 py-2 border-t border-p-border flex items-center justify-between text-[10px] text-p-text-faint">
              <span>Verbatix Studio</span>
              <div className="flex items-center gap-2">
                <kbd className="kbd-hint text-[10px]">↑↓</kbd>
                <span>Navegar</span>
                <kbd className="kbd-hint text-[10px]">Enter</kbd>
                <span>Abrir</span>
                <kbd className="kbd-hint text-[10px]">Esc</kbd>
                <span>Cerrar</span>
              </div>
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>,
    document.body
  );
}