import React, { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { useAuth } from "../auth";
import { LogOut, Shield, Volume2, VolumeX } from "lucide-react";
import { isMuted, setMuted, sfx } from "../sound";

export function Layout({ children, hideNav = false }) {
  const loc = useLocation();
  const { isAdmin, isRanger, logout } = useAuth();
  const [muted, setLocalMuted] = useState(isMuted());

  useEffect(() => {
    const onChange = () => setLocalMuted(isMuted());
    window.addEventListener("kop-sound-change", onChange);
    return () => window.removeEventListener("kop-sound-change", onChange);
  }, []);

  const toggleMute = () => {
    const next = !muted;
    setMuted(next);
    setLocalMuted(next);
    if (!next) sfx.select();
  };

  if (hideNav) return <div className="min-h-screen">{children}</div>;

  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-red-900/50 bg-black/80 backdrop-blur sticky top-0 z-40">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between gap-4">
          <Link to="/" data-testid="header-home-link" onClick={() => sfx.navigate()} className="flex items-center gap-2 group">
            <div className="w-9 h-9 kop-chamfer bg-gradient-to-br from-red-500 to-red-900 flex items-center justify-center font-arcade text-white text-sm kop-glow-red">KOP</div>
            <div className="hidden sm:block">
              <div className="font-arcade text-sm text-red-500 leading-none">KINGS OF PAINTBALL</div>
              <div className="font-display text-xs text-slate-400 tracking-widest">KOP 3x3</div>
            </div>
          </Link>
          <nav className="flex items-center gap-1 sm:gap-2 flex-wrap text-xs font-display uppercase tracking-widest">
            {[
              ["/", "Home"],
              ["/register", "Inscrição"],
              ["/teams", "Teams"],
              ["/matches", "Matches"],
              ["/standings", "Standings"],
              ["/playoffs", "Playoffs"],
              ["/stats", "Stats"],
              ["/rules", "Regras"],
              ["/live", "Live"],
            ].map(([to, label]) => (
              <Link key={to} to={to} onClick={() => sfx.navigate()}
                data-testid={`nav-${label.toLowerCase()}`}
                className={`px-2 py-1 hover:text-red-400 transition ${loc.pathname === to ? "text-red-500 border-b-2 border-red-500" : "text-slate-300"}`}>
                {label}
              </Link>
            ))}
          </nav>
          <div className="flex items-center gap-2">
            <button data-testid="sound-toggle-global" onClick={toggleMute}
              title={muted ? "Ativar som" : "Silenciar"}
              className={`p-1.5 border kop-chamfer ${muted ? "border-slate-700 text-slate-500" : "border-cyan-500/50 text-cyan-300 kop-glow-blue"}`}>
              {muted ? <VolumeX className="w-4 h-4" /> : <Volume2 className="w-4 h-4" />}
            </button>
            {isAdmin ? (
              <>
                <Link to="/admin" onClick={() => sfx.select()} data-testid="admin-panel-link" className="flex items-center gap-1 text-xs font-display uppercase tracking-widest text-cyan-300 hover:text-cyan-200 border border-cyan-500/40 px-2 py-1 kop-chamfer">
                  <Shield className="w-3 h-3" /> Admin
                </Link>
                <button data-testid="logout-btn" onClick={() => { sfx.back(); logout(); }} className="text-slate-400 hover:text-red-500" title="Sair">
                  <LogOut className="w-4 h-4" />
                </button>
              </>
            ) : isRanger ? (
              <>
                <Link to="/matches" onClick={() => sfx.select()} data-testid="ranger-panel-link" className="flex items-center gap-1 text-xs font-display uppercase tracking-widest text-yellow-300 hover:text-yellow-200 border border-yellow-500/40 px-2 py-1 kop-chamfer">
                  <Shield className="w-3 h-3" /> Arbitragem
                </Link>
                <button data-testid="logout-btn" onClick={() => { sfx.back(); logout(); }} className="text-slate-400 hover:text-red-500" title="Sair">
                  <LogOut className="w-4 h-4" />
                </button>
              </>
            ) : (
              <Link to="/login" onClick={() => sfx.select()} data-testid="admin-login-link" className="text-xs font-display uppercase tracking-widest text-slate-400 hover:text-red-500">
                Admin
              </Link>
            )}
          </div>
        </div>
      </header>
      <main className="flex-1">{children}</main>
      <footer className="border-t border-red-900/30 py-4 text-center text-xs text-slate-600 font-display tracking-widest uppercase">
        3 PLAYERS. 1 TEAM. 1 CHAMPION.
      </footer>
    </div>
  );
}
