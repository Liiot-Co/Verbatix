import { useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { LayoutDashboard, Plus, Keyboard, Command } from "lucide-react";
import { motion } from "framer-motion";
import { useKeyboardShortcuts, registerShortcuts, modLabel } from "@/hooks/useKeyboardShortcuts";

const NAV_ITEMS: { path: string; label: string; icon: typeof LayoutDashboard }[] = [
  { path: "/", label: "Inicio", icon: LayoutDashboard },
  { path: "/wizard", label: "Nuevo proyecto", icon: Plus },
];

export default function AppShell({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate();
  const location = useLocation();

  useKeyboardShortcuts("global");

  useEffect(() => {
    registerShortcuts("global", [
      {
        key: "/",
        meta: false,
        action: () => {
          const searchInput = document.querySelector('input[placeholder*="Buscar"]') as HTMLInputElement | null;
          searchInput?.focus();
        },
        description: "Buscar",
        category: "Navegación",
        allowInInput: false,
      },
      {
        key: "f",
        meta: true,
        shift: true,
        action: () => {
          const searchInput = document.querySelector('input[placeholder*="Buscar"]') as HTMLInputElement | null;
          searchInput?.focus();
        },
        description: "Buscar (alternativo)",
        category: "Navegación",
        allowInInput: false,
      },
      {
        key: "d",
        meta: true,
        shift: true,
        action: () => navigate("/"),
        description: "Ir al Dashboard",
        category: "Navegación",
      },
      {
        key: "n",
        meta: true,
        shift: true,
        action: () => navigate("/wizard"),
        description: "Nuevo proyecto",
        category: "Navegación",
      },
      {
        key: "ArrowLeft",
        meta: true,
        action: () => window.history.back(),
        description: "Atrás",
        category: "Navegación",
      },
      {
        key: "ArrowRight",
        meta: true,
        action: () => window.history.forward(),
        description: "Adelante",
        category: "Navegación",
      },
    ]);
  }, [navigate]);

  const openCommandPalette = () => {
    window.dispatchEvent(new CustomEvent("toggle-command-palette"));
  };

  return (
    <>
      {/* Ambient glow — drifting Verbatix Light corner gradients */}
      <div aria-hidden className="ambient-wash pointer-events-none fixed inset-0 -z-10" />
      <div className="flex h-screen bg-p-bg overflow-hidden">
        {/* Sidebar */}
        <aside className="w-[220px] shrink-0 h-screen sticky top-0 flex flex-col border-r border-p-border bg-p-surface overflow-hidden"
        >
          {/* Logo */}
          <div className="p-3.5 border-b border-p-border flex-shrink-0"
          >
            <div className="flex items-center gap-2.5">
              <motion.div
                whileHover={{ scale: 1.05, rotate: 3 }}
                whileTap={{ scale: 0.95 }}
                className="w-8 h-8 rounded-lg bg-gradient-to-br from-p-accent to-p-accent-mid flex items-center justify-center shrink-0"
              >
                <svg width="17" height="13" viewBox="0 0 17 13" fill="none">
                  <polyline points="1,1.5 4.5,11.5 8.5,3.5 12.5,11.5 16,1.5" stroke="white" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </motion.div>
              <div className="min-w-0">
                <div className="font-heading font-extrabold text-[15px] tracking-tight text-p-text leading-tight truncate">Verbatix</div>
                <div className="font-subtitle text-[10px] tracking-[0.18em] uppercase text-p-text-faint mt-0.5 truncate">Studio</div>
              </div>
            </div>
          </div>

          {/* Navigation */}
          <nav className="flex-1 p-2 flex flex-col gap-1 overflow-y-auto scrollbar-thin"
          >
            <div className="font-subtitle text-[10px] tracking-[0.22em] uppercase text-p-text-faint gradient-text-morph-brand px-2 pt-2.5 pb-1.5">
              Principal
            </div>
            <div className="flex flex-col gap-1">
              {NAV_ITEMS.map(({ path, label, icon: Icon }) => (
                <motion.button
                  key={path}
                  layout
                  onClick={() => navigate(path)}
                  whileHover={{ x: 4 }}
                  whileTap={{ scale: 0.98 }}
                  className={[
                    "relative flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm font-medium transition-colors duration-150",
                    location.pathname === path
                      ? "sidebar-nav-item-active-morph text-p-text"
                      : "text-p-text-muted hover:bg-p-bg-subtle/60 hover:text-p-text",
                  ].join(" ")}
                >
                  {location.pathname === path && (
                    <motion.span
                      layout
                      className="absolute left-0 top-1.5 bottom-1.5 w-[2.5px] bg-p-accent rounded-r"
                    />
                  )}
                  <Icon className="w-3.5 h-3.5 shrink-0" />
                  <span className="flex-1 text-left truncate">{label}</span>
                </motion.button>
              ))}
            </div>

            {/* Keyboard shortcuts hint */}
            <div className="mt-auto p-2 border-t border-p-border"
            >
              <button
                onClick={openCommandPalette}
                className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-xs text-p-text-muted hover:text-p-text hover:bg-p-bg-subtle transition-colors"
                title={`Abrir paleta de comandos (${modLabel()}K)`}
              >
                <Keyboard className="w-3.5 h-3.5 shrink-0" />
                <span className="flex-1 text-left">Atajos de teclado</span>
                <Command className="w-3.5 h-3.5 shrink-0 opacity-50" />
                <span className="kbd-hint">{modLabel()}K</span>
              </button>
            </div>
          </nav>
        </aside>

        {/* Main content area */}
        <div className="relative flex-1 flex flex-col overflow-hidden min-w-0 bg-p-bg"
        >
          <div className="relative z-10 flex-1 flex flex-col overflow-hidden min-w-0">
            {children}
          </div>
        </div>
      </div>
    </>
  );
}