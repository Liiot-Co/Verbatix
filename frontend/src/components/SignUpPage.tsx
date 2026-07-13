import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { Eye, EyeOff, UserPlus, Mail, Lock, AlertCircle, CheckCircle2 } from "lucide-react";
import { signup } from "@/api/client";
import { useVerbatixStore } from "@/store/useVerbatixStore";

export default function SignUpPage() {
  const navigate = useNavigate();
  const showToast = useVerbatixStore((s) => s.showToast);

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!email.trim() || !password) return;
    if (password.length < 6) {
      setError("La contraseña debe tener al menos 6 caracteres");
      return;
    }
    if (password !== confirmPassword) {
      setError("Las contraseñas no coinciden");
      return;
    }

    setLoading(true);
    try {
      const res = await signup({ email: email.trim(), password });
      if (res.access_token) {
        showToast("Cuenta creada correctamente", "success");
        navigate("/login");
      } else {
        setSuccess(true);
      }
    } catch {
      // El error crudo del backend/Supabase viene en inglés y como texto técnico
      // (JSON, códigos internos) — no es apto para mostrar tal cual.
      setError("No se pudo crear la cuenta. Intenta de nuevo.");
    } finally {
      setLoading(false);
    }
  };

  if (success) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center bg-p-bg relative overflow-hidden px-4">
        <div aria-hidden className="ambient-wash pointer-events-none fixed inset-0 -z-10" />
        <motion.div
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          className="card p-8 max-w-sm w-full text-center space-y-4"
        >
          <motion.div
            initial={{ scale: 0 }}
            animate={{ scale: 1 }}
            transition={{ type: "spring", stiffness: 300, damping: 15 }}
          >
            <CheckCircle2 className="w-12 h-12 text-p-success mx-auto" />
          </motion.div>
          <h2 className="font-heading text-lg font-semibold text-p-text tracking-tight">Revisa tu correo</h2>
          <p className="text-sm text-p-text-muted">
            Te enviamos un enlace de confirmación a <strong className="text-p-text">{email}</strong>.
          </p>
          <Link to="/login" className="btn-primary text-sm py-2.5 w-full justify-center mt-2 inline-flex">
            Volver al inicio de sesión
          </Link>
        </motion.div>
      </div>
    );
  }

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
            <h1 className="font-heading text-lg font-semibold text-p-text tracking-tight">Crear cuenta</h1>
            <p className="text-sm text-p-text-muted">Regístrate para empezar a usar Verbatix</p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <label className="form-label" htmlFor="signup-email">Correo electrónico</label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-p-text-faint pointer-events-none" />
                <input
                  id="signup-email"
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
              <label className="form-label" htmlFor="signup-password">Contraseña</label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-p-text-faint pointer-events-none" />
                <input
                  id="signup-password"
                  type={showPassword ? "text" : "password"}
                  autoComplete="new-password"
                  className="input pl-10 pr-10 text-sm"
                  placeholder="Mínimo 6 caracteres"
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

            <div className="space-y-1.5">
              <label className="form-label" htmlFor="signup-confirm">Confirmar contraseña</label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-p-text-faint pointer-events-none" />
                <input
                  id="signup-confirm"
                  type={showPassword ? "text" : "password"}
                  autoComplete="new-password"
                  className="input pl-10 text-sm"
                  placeholder="Repite la contraseña"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                />
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
              disabled={loading || !email.trim() || !password || !confirmPassword}
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
                <UserPlus className="w-4 h-4" />
              )}
              {loading ? "Creando cuenta..." : "Crear cuenta"}
            </motion.button>
          </form>

          <div className="relative">
            <div className="divider-with-text">
              <span>¿Ya tienes cuenta?</span>
            </div>
          </div>

          <Link
            to="/login"
            className="block w-full text-center btn-ghost text-sm py-2.5"
          >
            Iniciar sesión
          </Link>
        </div>
      </motion.div>

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
