import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { KeyRound, ShieldCheck } from "lucide-react";
import { recoverAccount } from "@/api/client";
import { writeAuthToken } from "@/lib/tokenStorage";

export default function RecoverAccountPage({ intro = false }: { intro?: boolean }) {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [newCode, setNewCode] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  if (intro) return <div className="min-h-screen bg-p-bg grid place-items-center px-4"><div className="card p-7 max-w-sm w-full text-center"><KeyRound className="w-10 h-10 text-p-accent mx-auto mb-4" /><h1 className="font-heading text-xl font-semibold text-p-text">Recuperar cuenta</h1><p className="text-sm text-p-text-muted mt-2">La recuperación local usa el código personal que guardaste al registrarte.</p><Link to="/recover-account" className="btn-primary justify-center mt-6 w-full">Usar mi código</Link><Link to="/login" className="btn-ghost justify-center mt-2 w-full">Volver</Link></div></div>;
  const submit = async (event: React.FormEvent) => {
    event.preventDefault(); setError(null);
    if (password.length < 8) return setError("La contraseña debe tener al menos 8 caracteres");
    if (password !== confirm) return setError("Las contraseñas no coinciden");
    try { const response = await recoverAccount({ email, recovery_code: code, password }); writeAuthToken(response.access_token); setNewCode(response.recovery_code); }
    catch { setError("No fue posible recuperar la cuenta con esos datos."); }
  };
  return <div className="min-h-screen bg-p-bg grid place-items-center px-4"><div className="card p-7 max-w-sm w-full">
    {newCode ? <div className="text-center"><ShieldCheck className="w-10 h-10 text-p-success mx-auto mb-4" /><h1 className="font-heading text-xl font-semibold text-p-text">Contraseña actualizada</h1><p className="text-sm text-p-text-muted mt-2">Tus sesiones anteriores fueron revocadas. Guarda el nuevo código:</p><code className="block bg-p-bg-subtle border border-p-border rounded-xl p-3 my-4 tracking-wider">{newCode}</code><button onClick={() => navigate("/")} className="btn-primary justify-center w-full">Continuar</button></div> : <><h1 className="font-heading text-xl font-semibold text-p-text">Recuperar cuenta</h1><p className="text-sm text-p-text-muted mt-1 mb-5">Ingresa tu correo, código personal y una contraseña nueva.</p><form onSubmit={submit} className="space-y-3"><input className="input" type="email" placeholder="Correo" value={email} onChange={(e) => setEmail(e.target.value)} required /><input className="input uppercase" placeholder="Código de recuperación" value={code} onChange={(e) => setCode(e.target.value)} required /><input className="input" type="password" placeholder="Contraseña nueva" value={password} onChange={(e) => setPassword(e.target.value)} required /><input className="input" type="password" placeholder="Confirmar contraseña" value={confirm} onChange={(e) => setConfirm(e.target.value)} required />{error && <p className="text-sm text-p-error">{error}</p>}<button className="btn-primary justify-center w-full">Cambiar contraseña</button></form></>}
  </div></div>;
}
