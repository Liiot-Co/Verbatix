import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, Link } from "react-router-dom";
import { LayoutDashboard, Wand2, Keyboard, Command, LogOut, ChevronDown, PanelLeftClose, PanelLeft, Users, Bell, Inbox } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { useKeyboardShortcuts, registerShortcuts, modLabel } from "@/hooks/useKeyboardShortcuts";
import { useVerbatixStore } from "@/store/useVerbatixStore";
import { logoutSession } from "@/api/client";
import { can } from "@/lib/capabilities";
import NotificationsPanel from "@/components/NotificationsPanel";
import { useNotificationPoll } from "@/hooks/useNotificationPoll";
import { useNotificationStore } from "@/store/useNotificationStore";
import MascotAvatar from "@/components/mascot/MascotAvatar";
import StatusPicker from "@/components/mascot/StatusPicker";
import { PRESENCE_CATALOG, type PresenceStatus } from "@/lib/presence";

const NAV_ITEMS: { path: string; label: string; icon: typeof LayoutDashboard }[] = [
  { path: "/", label: "Inicio", icon: LayoutDashboard },
  { path: "/notifications", label: "Bandeja", icon: Inbox },
];

export default function AppShell({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate();
  const location = useLocation();
  const user = useVerbatixStore((s) => s.user);
  const logout = useVerbatixStore((s) => s.logout);
  const [menuOpen, setMenuOpen] = useState(false);
  const [bellOpen, setBellOpen] = useState(false);
  const [presenceOpen, setPresenceOpen] = useState(false);
  const [mascotHint, setMascotHint] = useState(() => localStorage.getItem("verbatix:mascot-hint") !== "1");
  const menuRef = useRef<HTMLDivElement>(null);
  const bellRef = useRef<HTMLDivElement>(null);
  const presenceRef = useRef<HTMLDivElement>(null);
  const unread = useNotificationStore((state) => state.unread);
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem("verbatix:sidebar-collapsed") === "1");

  useNotificationPoll(Boolean(user));

  useEffect(() => {
    localStorage.setItem("verbatix:sidebar-collapsed", collapsed ? "1" : "0");
  }, [collapsed]);

  useKeyboardShortcuts("global");

  useEffect(() => {
    const shortcuts = [
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
    ];
    if (can(user, "projects.manage")) shortcuts.push({
        key: "n",
        meta: true,
        shift: true,
        action: () => navigate("/wizard"),
        description: "Nuevo proyecto",
        category: "Navegación",
      });
    registerShortcuts("global", shortcuts);
  }, [navigate, user]);

  // Close menu on click outside
  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
      if (bellRef.current && !bellRef.current.contains(e.target as Node)) setBellOpen(false);
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const openCommandPalette = () => {
    window.dispatchEvent(new CustomEvent("toggle-command-palette"));
  };

  const presenceStatus: PresenceStatus = user?.presence_status ?? "disponible";
  const presenceLabel = PRESENCE_CATALOG[presenceStatus].label;

  return (
    <>
      {/* Ambient glow — drifting Verbatix Light corner gradients */}
      <div aria-hidden className="ambient-wash pointer-events-none fixed inset-0 -z-10" />
      <div className="relative flex h-screen bg-p-bg overflow-hidden">
        {/* Sidebar */}
        <aside className={`app-sidebar ${collapsed ? "w-[64px]" : "w-[220px]"} shrink-0 h-screen sticky top-0 flex flex-col transition-[width] duration-200`}
        >
          {/* Logo */}
          <div className={`p-3.5 border-b border-p-border flex-shrink-0 ${collapsed ? "flex justify-center" : ""}`}
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
              {!collapsed && (
                <div className="min-w-0 flex-1">
                  <div className="font-heading font-extrabold text-[15px] tracking-tight text-p-text leading-tight truncate">Verbatix</div>
                  <div className="font-subtitle text-[10px] tracking-[0.18em] uppercase text-p-text-faint mt-0.5 truncate">Studio</div>
                </div>
              )}
            </div>
          </div>

          {/* Navigation */}
          <nav className="flex-1 p-2 flex flex-col gap-1 overflow-y-auto scrollbar-thin"
          >
            {!collapsed && (
              <div className="font-subtitle text-[10px] tracking-[0.22em] uppercase text-p-text-faint gradient-text-morph-brand px-2 pt-2.5 pb-1.5">
                Principal
              </div>
            )}
            <div className="flex flex-col gap-1">
              {NAV_ITEMS.map(({ path, label, icon: Icon }) => (
                <Link
                  key={path}
                  to={path}
                  title={collapsed ? label : undefined}
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
                  {!collapsed && <span className="flex-1 text-left truncate">{label}</span>}
                </Link>
              ))}
              {can(user, "users.manage") && <Link to="/team" className="flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm font-medium text-p-text-muted hover:text-p-text hover:bg-p-bg-subtle/60"><Users className="w-3.5 h-3.5" />{!collapsed && "Equipo y asignaciones"}</Link>}
            </div>

            {can(user, "projects.manage") && <>
            {!collapsed && (
              <div className="font-subtitle text-[10px] tracking-[0.22em] uppercase text-p-text-faint px-2 pt-4 pb-1.5">
                Acciones
              </div>
            )}
            <Link
              to="/wizard"
              title={collapsed ? "Nuevo proyecto" : undefined}
              className="flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm font-medium text-p-text-muted hover:text-p-text hover:bg-p-bg-subtle/60 transition-all duration-150 hover:translate-x-1 active:scale-[0.98]"
            >
              <Wand2 className="w-3.5 h-3.5 shrink-0" />
              {!collapsed && <span className="flex-1 text-left truncate">Nuevo proyecto</span>}
            </Link>
            </>}

            {/* User section at bottom */}
            <div className="mt-auto border-t border-p-border pt-2">
              <div className="relative px-2 pb-1" ref={bellRef}>
                <motion.button
                  onClick={() => setBellOpen((open) => !open)}
                  whileTap={{ scale: 0.95 }}
                  className="relative flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-p-text-muted transition-colors hover:bg-p-bg-subtle/60 hover:text-p-text"
                  title={collapsed ? "Notificaciones" : undefined}
                  aria-label="Abrir notificaciones"
                  aria-expanded={bellOpen}
                >
                  <motion.span key={unread} animate={unread > 0 ? { rotate: [0, -8, 8, 0] } : { rotate: 0 }} transition={{ duration: 0.32 }}><Bell className="h-4 w-4 shrink-0" /></motion.span>
                  {!collapsed && <span className="flex-1 text-left text-xs">Notificaciones</span>}
                  <AnimatePresence>{unread > 0 && <motion.span key={unread} initial={{ scale: 0.5, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.5, opacity: 0 }} transition={{ type: "spring", stiffness: 420, damping: 22 }} className="min-w-4 rounded-full bg-p-accent px-1.5 py-0.5 text-center text-[10px] font-bold leading-none text-white">{unread > 99 ? "99+" : unread}</motion.span>}</AnimatePresence>
                </motion.button>
                {bellOpen && <NotificationsPanel anchorRef={bellRef} onClose={() => setBellOpen(false)} />}
              </div>
              <div className={`flex items-center gap-1.5 px-2 pb-1 ${collapsed ? "justify-center" : ""}`}>
                <div className="relative" ref={presenceRef}>
                  <MascotAvatar
                    status={presenceStatus}
                    size="sm"
                    onClick={() => setPresenceOpen((open) => !open)}
                    hint={mascotHint}
                    title={collapsed ? `${presenceLabel} — haz clic para cambiar` : undefined}
                  />
                  <AnimatePresence>
                    {presenceOpen && <StatusPicker status={presenceStatus} onClose={() => setPresenceOpen(false)} onChanged={() => setMascotHint(false)} anchorRef={presenceRef} />}
                  </AnimatePresence>
                </div>
                {!collapsed && <div className="relative min-w-0 flex-1" ref={menuRef}>
                  <motion.button
                    onClick={() => setMenuOpen(!menuOpen)}
                    whileHover={{ x: 2 }}
                    whileTap={{ scale: 0.98 }}
                    className="w-full flex items-center gap-2 px-2 py-2 rounded-lg text-sm text-p-text-muted hover:text-p-text hover:bg-p-bg-subtle/60 transition-colors duration-150"
                  >
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
                        className="absolute bottom-full mb-1 left-0 right-0 bg-p-surface border border-p-border rounded-xl shadow-lg overflow-hidden"
                      >
                        <div className="p-2 space-y-0.5">
                          <div className="px-3 py-2 text-xs text-p-text-muted border-b border-p-border mb-1">
                            <div className="font-medium text-p-text truncate">{user?.email}</div>
                            <div className="capitalize">{user?.roles.join(" · ") || "Sin roles"}</div>
                          </div>
                          <button
                            onClick={async () => { try { await logoutSession(); } finally { logout(); navigate("/login"); } }}
                            className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-xs text-p-text-muted hover:text-p-error hover:bg-p-error/10 transition-colors"
                          >
                            <LogOut className="w-3.5 h-3.5" />
                            Cerrar sesión
                          </button>
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>}
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
                  {!collapsed && (
                    <>
                      <span className="flex-1 text-left">Atajos de teclado</span>
                      <Command className="w-3.5 h-3.5 shrink-0 opacity-50" />
                      <span className="kbd-hint">{modLabel()}K</span>
                    </>
                  )}
                </button>
              </div>
            </div>
          </nav>
        </aside>

        <button
          onClick={() => setCollapsed((v) => !v)}
          className="absolute top-[26px] z-20 -translate-x-1/2 w-6 h-6 rounded-full bg-p-surface border border-p-border shadow-sm flex items-center justify-center text-p-text-faint hover:text-p-text hover:bg-p-bg-subtle transition-all duration-200"
          style={{ left: collapsed ? 64 : 220 }}
          title={collapsed ? "Expandir menú" : "Colapsar menú"}
          aria-label={collapsed ? "Expandir menú" : "Colapsar menú"}
        >
          {collapsed ? <PanelLeft className="w-3.5 h-3.5" /> : <PanelLeftClose className="w-3.5 h-3.5" />}
        </button>

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
