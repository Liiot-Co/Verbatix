import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { Eye, EyeOff, LogIn, Mail, Lock, AlertCircle } from "lucide-react";
import { login } from "@/api/client";
import { useVerbatixStore } from "@/store/useVerbatixStore";

export default function SignInPage() {
  const navigate = useNavigate();
  const setAuth = useVerbatixStore((s) => s.setAuth);

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !password) return;
    setLoading(true);
    setError(null);
    try {
      const res = await login({ email: email.trim(), password });
      setAuth(res.access_token, { id: res.user.id, email: res.user.email, name: null, role: "analyst", is_active: true, created_at: "" });
      navigate("/");
    } catch {
      // El error crudo del backend/Supabase viene en inglés y como texto técnico
      // (JSON, códigos internos) — no es apto para mostrar tal cual.
      setError("No se pudo iniciar sesión. Revisa tu correo y contraseña.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-p-bg relative overflow-hidden px-4">
      {/* Ambient glow */}
      <div aria-hidden className="ambient-wash pointer-events-none fixed inset-0 -z-10" />

      {/* Logo */}
      <motion.div
        initial={{ opacity: 0, y: -20, scale: 0.9 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.5, ease: [0.19, 1, 0.22, 1] }}
        className="mb-8 flex flex-col items-center gap-3"
      >
        <motion.div
          whileHover={{ scale: 1.05, rotate: 3 }}
          className="w-12 h-12 rounded-xl bg-p-accent flex items-center justify-center shadow-lg"
        >
          <svg width="24" height="18" viewBox="0 0 17 13" fill="none">
            <polyline points="1,1.5 4.5,11.5 8.5,3.5 12.5,11.5 16,1.5" stroke="white" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </motion.div>
        <div className="text-center">
          <div className="font-heading font-extrabold text-xl tracking-tight text-p-text">Verbatix</div>
          <div className="font-subtitle text-[10px] tracking-[0.18em] uppercase text-p-text-faint mt-0.5">Studio</div>
        </div>
      </motion.div>

      {/* Card */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, delay: 0.1, ease: [0.19, 1, 0.22, 1] }}
        className="w-full max-w-sm"
      >
        <div className="card p-6 space-y-5">
          <div className="space-y-1">
            <h1 className="font-heading text-xl font-semibold text-p-text tracking-tight">Iniciar sesión</h1>
            <p className="text-sm text-p-text-muted">Ingresa con tu cuenta de Supabase</p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <label className="form-label" htmlFor="email">Correo electrónico</label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-p-text-faint pointer-events-none" />
                <input
                  id="email"
                  type="email"
                  autoComplete="email"
                  autoFocus
                  className="input pl-10 text-sm"
                  placeholder="tu@email.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </div>
            </div>

            <div className="space-y-1.5">
              <label className="form-label" htmlFor="password">Contraseña</label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-p-text-faint pointer-events-none" />
                <input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  autoComplete="current-password"
                  className="input pl-10 pr-10 text-sm"
                  placeholder="••••••••"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-p-text-faint hover:text-p-text transition-colors"
                  tabIndex={-1}
                >
                  {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            <AnimatePresence>
              {error && (
                <motion.div
                  initial={{ opacity: 0, y: -8, height: 0 }}
                  animate={{ opacity: 1, y: 0, height: "auto" }}
                  exit={{ opacity: 0, y: -8, height: 0 }}
                  className="flex items-center gap-2 text-sm text-p-error bg-red-50 border border-red-200 rounded-lg p-3"
                >
                  <AlertCircle className="w-4 h-4 shrink-0" />
                  <span>{error}</span>
                </motion.div>
              )}
            </AnimatePresence>

            <motion.button
              type="submit"
              disabled={loading || !email.trim() || !password}
              whileHover={{ scale: 1.01 }}
              whileTap={{ scale: 0.98 }}
              className="btn-primary w-full justify-center text-sm py-2.5"
            >
              {loading ? (
                <motion.span
                  animate={{ rotate: 360 }}
                  transition={{ duration: 1, repeat: Infinity, ease: "linear" }}
                  className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full"
                />
              ) : (
                <LogIn className="w-4 h-4" />
              )}
              {loading ? "Ingresando..." : "Ingresar"}
            </motion.button>
          </form>

          <div className="relative">
            <div className="divider-with-text">
              <span>¿No tienes cuenta?</span>
            </div>
          </div>

          <Link
            to="/signup"
            className="block w-full text-center btn-ghost text-sm py-2.5"
          >
            Crear cuenta nueva
          </Link>
        </div>
      </motion.div>

      {/* Footer */}
      <motion.p
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.4 }}
        className="mt-6 text-xs text-p-text-faint"
      >
        Verbatix Studio &copy; {new Date().getFullYear()}
      </motion.p>
    </div>
  );
}
