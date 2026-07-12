import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, Link } from "react-router-dom";
import { LayoutDashboard, Wand2, Keyboard, Command, LogOut, ChevronDown } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { useKeyboardShortcuts, registerShortcuts, modLabel } from "@/hooks/useKeyboardShortcuts";
import { useVerbatixStore } from "@/store/useVerbatixStore";

const NAV_ITEMS: { path: string; label: string; icon: typeof LayoutDashboard }[] = [
  { path: "/", label: "Inicio", icon: LayoutDashboard },
];

export default function AppShell({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate();
  const location = useLocation();
  const user = useVerbatixStore((s) => s.user);
  const logout = useVerbatixStore((s) => s.logout);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useKeyboardShortcuts("global");

  useEffect(() => {
    registerShortcuts("global", [
      {
        key: "f",
        meta: true,
        action: () => {
          const searchInput = document.querySelector('input[placeholder*="Buscar"]') as HTMLInputElement | null;
          searchInput?.focus();
        },
        description: "Buscar",
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

  // Close menu on click outside
  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const openCommandPalette = () => {
    window.dispatchEvent(new CustomEvent("toggle-command-palette"));
  };

  const userInitial = user?.email?.charAt(0).toUpperCase() ?? "?";

  return (
    <>
      {/* Ambient glow — drifting Verbatix Light corner gradients */}
      <div aria-hidden className="ambient-wash pointer-events-none fixed inset-0 -z-10" />
      <div className="flex h-screen bg-p-bg overflow-hidden">
        {/* Sidebar */}
        <aside className="app-sidebar w-[220px] shrink-0 h-screen sticky top-0 flex flex-col"
        >
          {/* Logo */}
          <div className="p-3.5 border-b border-p-border flex-shrink-0"
          >
            <div className="flex items-center gap-2.5">
              <motion.div
                whileHover={{ scale: 1.05, rotate: 3 }}
                whileTap={{ scale: 0.95 }}
                className="w-8 h-8 rounded-lg bg-p-accent flex items-center justify-center shrink-0"
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
                <Link
                  key={path}
                  to={path}
                  className={[
                    "relative flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm font-medium transition-all duration-150 hover:translate-x-1 active:scale-[0.98]",
                    location.pathname === path
                      ? "sidebar-nav-item-active-morph text-p-text"
                      : "text-p-text-muted hover:bg-p-bg-subtle/60 hover:text-p-text",
                  ].join(" ")}
                >
                  {location.pathname === path && (
                    <motion.span
                      layoutId="sidebar-active"
                      className="absolute left-0 top-1.5 bottom-1.5 w-[2.5px] bg-p-accent rounded-r"
                    />
                  )}
                  <Icon className="w-3.5 h-3.5 shrink-0" />
                  <span className="flex-1 text-left truncate">{label}</span>
                </Link>
              ))}
            </div>

            <div className="font-subtitle text-[10px] tracking-[0.22em] uppercase text-p-text-faint px-2 pt-4 pb-1.5">
              Acciones
            </div>
            <Link
              to="/wizard"
              className="flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm font-medium text-p-text-muted hover:text-p-text hover:bg-p-bg-subtle/60 transition-all duration-150 hover:translate-x-1 active:scale-[0.98]"
            >
              <Wand2 className="w-3.5 h-3.5 shrink-0" />
              <span className="flex-1 text-left truncate">Nuevo proyecto</span>
            </Link>

            {/* User section at bottom */}
            <div className="mt-auto border-t border-p-border pt-2">
              <div className="relative" ref={menuRef}>
                <motion.button
                  onClick={() => setMenuOpen(!menuOpen)}
                  whileHover={{ x: 2 }}
                  whileTap={{ scale: 0.98 }}
                  className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-p-text-muted hover:text-p-text hover:bg-p-bg-subtle/60 transition-colors duration-150"
                >
                  <div className="avatar w-6 h-6 text-[11px] shrink-0">{userInitial}</div>
                  <span className="flex-1 text-left truncate text-xs">{user?.email ?? "Usuario"}</span>
                  <ChevronDown className={`w-3 h-3 shrink-0 transition-transform duration-150 ${menuOpen ? "rotate-180" : ""}`} />
                </motion.button>

                <AnimatePresence>
                  {menuOpen && (
                    <motion.div
                      initial={{ opacity: 0, y: -4, scale: 0.96 }}
                      animate={{ opacity: 1, y: 0, scale: 1 }}
                      exit={{ opacity: 0, y: -4, scale: 0.96 }}
                      transition={{ duration: 0.12, ease: [0.19, 1, 0.22, 1] }}
                      className="absolute bottom-full left-0 right-0 mb-1 bg-p-surface border border-p-border rounded-xl shadow-lg overflow-hidden"
                    >
                      <div className="p-2 space-y-0.5">
                        <div className="px-3 py-2 text-xs text-p-text-muted border-b border-p-border mb-1">
                          <div className="font-medium text-p-text truncate">{user?.email}</div>
                          <div className="capitalize">{user?.role ?? "analyst"}</div>
                        </div>
                        <button
                          onClick={() => { logout(); navigate("/login"); }}
                          className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-xs text-p-text-muted hover:text-p-error hover:bg-red-50 transition-colors"
                        >
                          <LogOut className="w-3.5 h-3.5" />
                          Cerrar sesión
                        </button>
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>

              {/* Keyboard shortcuts hint */}
              <div className="p-2"
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
