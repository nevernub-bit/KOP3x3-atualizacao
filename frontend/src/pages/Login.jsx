import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth";
import { formatErr } from "../api";
import { toast } from "sonner";

export default function Login() {
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [pw, setPw] = useState("");
  const [loading, setLoading] = useState(false);
  const nav = useNavigate();

  const submit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const logged = await login(email, pw);
      const isRangerUser = logged?.role === "ranger";
      toast.success(isRangerUser ? "Bem-vindo, Ranger" : "Bem-vindo, Organizador");
      nav(isRangerUser ? "/matches" : "/admin");
    } catch (err) {
      toast.error(formatErr(err.response?.data?.detail) || "Falha no login");
    } finally { setLoading(false); }
  };

  return (
    <div className="min-h-[80vh] flex items-center justify-center px-4">
      <form onSubmit={submit} className="w-full max-w-md bg-black/70 border border-red-900/50 kop-chamfer p-8">
        <div className="text-center mb-6">
          <div className="font-display text-cyan-300 text-xs tracking-[0.4em] uppercase">Admin Access</div>
          <h1 className="font-arcade text-3xl text-red-500 uppercase">Organizador</h1>
        </div>
        <div className="space-y-4">
          <div>
            <label className="text-xs font-display uppercase tracking-widest text-slate-400">Email</label>
            <input data-testid="login-email" value={email} onChange={e => setEmail(e.target.value)} type="email" className="w-full mt-1 bg-slate-900 border border-slate-700 focus:border-red-500 px-3 py-2 text-white outline-none" />
          </div>
          <div>
            <label className="text-xs font-display uppercase tracking-widest text-slate-400">Senha</label>
            <input data-testid="login-password" value={pw} onChange={e => setPw(e.target.value)} type="password" className="w-full mt-1 bg-slate-900 border border-slate-700 focus:border-red-500 px-3 py-2 text-white outline-none" />
          </div>
          <button disabled={loading} data-testid="login-submit" className="w-full kop-chamfer bg-red-600 hover:bg-red-500 disabled:opacity-50 text-white font-arcade uppercase tracking-widest py-3 kop-glow-red transition">
            {loading ? "Autenticando..." : "▶ Entrar"}
          </button>
        </div>
      </form>
    </div>
  );
}
