import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { PlayerSelectStrip } from "../components/CharacterSelect";
import { UserPlus, Shield, Shuffle, Grid, Swords, Trophy, Users, BarChart3, GitFork, Crown, Tv, BookOpen } from "lucide-react";

const ITEMS = [
  { to: "/register", key: "INSCRICOES", label: "INSCRIÇÕES", icon: UserPlus, color: "red" },
  { to: "/teams", key: "TEAMS", label: "TEAMS", icon: Shield, color: "orange" },
  { to: "/team-select", key: "TEAM_SELECT", label: "TEAM SELECT", icon: Shuffle, color: "yellow" },
  { to: "/teams", key: "GROUPS", label: "GROUPS", icon: Grid, color: "blue" },
  { to: "/matches", key: "MATCHES", label: "MATCHES", icon: Swords, color: "red" },
  { to: "/standings", key: "STANDINGS", label: "STANDINGS", icon: Trophy, color: "orange" },
  { to: "/players", key: "PLAYERS", label: "PLAYERS", icon: Users, color: "blue" },
  { to: "/stats", key: "STATS", label: "STATS", icon: BarChart3, color: "yellow" },
  { to: "/playoffs", key: "PLAYOFFS", label: "PLAYOFFS", icon: GitFork, color: "red" },
  { to: "/champion", key: "CHAMPION", label: "CHAMPION", icon: Crown, color: "gold" },
  { to: "/rules", key: "RULES", label: "REGRAS", icon: BookOpen, color: "gold" },
  { to: "/live", key: "LIVE", label: "KOP LIVE", icon: Tv, color: "blue" },
];

const COLOR = {
  red: "text-red-400 border-red-500/60 hover:kop-glow-red hover:border-red-500",
  orange: "text-orange-400 border-orange-500/60 hover:border-orange-500 hover:shadow-[0_0_25px_rgba(255,107,0,0.55)]",
  yellow: "text-yellow-400 border-yellow-500/60 hover:border-yellow-500 hover:shadow-[0_0_25px_rgba(255,208,0,0.5)]",
  blue: "text-cyan-300 border-cyan-500/60 hover:kop-glow-blue hover:border-cyan-400",
  gold: "text-amber-400 border-amber-500/60 hover:kop-glow-gold hover:border-amber-500",
};

export default function Home() {
  const [banner, setBanner] = useState(null);
  const [players, setPlayers] = useState([]);
  const [cfg, setCfg] = useState(null);
  const [playersReady, setPlayersReady] = useState(false);
  const [phase, setPhase] = useState("SELECT");

  // One load per visit. The players endpoint answers 304 when nothing changed,
  // so returning visitors do not download the same photos again.
  useEffect(() => {
    let alive = true;
    Promise.all([
      api.get("/banner").catch(() => null),
      api.get("/players").catch(() => null),
      api.get("/tournament").catch(() => null),
    ]).then(([b, p, t]) => {
      if (!alive) return;
      setBanner(b?.data?.image || null);
      setPlayers(Array.isArray(p?.data) ? p.data : []);
      setCfg(t?.data || null);
      setPlayersReady(true);
    });
    return () => { alive = false; };
  }, []);

  const mode = cfg?.home_mode || "SELECT";
  const selectSeconds = Math.max(5, Number(cfg?.home_select_seconds ?? 15));
  const bannerSeconds = Math.max(3, Number(cfg?.home_banner_seconds ?? 10));

  // Presentation mode only decides where the banner sits. Without a banner
  // there is nothing to rotate to, so it stays on the roster.
  useEffect(() => {
    if (!playersReady) return;
    if (mode !== "AUTO" || !banner) {
      setPhase(mode === "BANNER" && banner ? "BANNER" : "SELECT");
      return;
    }
    let current = "SELECT";
    let timer = null;
    setPhase(current);
    const schedule = () => {
      const waitFor = current === "SELECT" ? selectSeconds : bannerSeconds;
      timer = setTimeout(() => {
        current = current === "SELECT" ? "BANNER" : "SELECT";
        setPhase(current);
        schedule();
      }, waitFor * 1000);
    };
    schedule();
    return () => clearTimeout(timer);
  }, [mode, banner, selectSeconds, bannerSeconds, playersReady]);

  const showHeroBanner = phase === "BANNER" && !!banner;
  const showFooterBanner = !!banner && !showHeroBanner;

  return (
    <div className="relative overflow-hidden">
      <div className="absolute inset-0 kop-grid-bg opacity-30 pointer-events-none" />

      <div className="relative max-w-6xl mx-auto px-4 py-8 sm:py-12">
        <div className="text-center mb-6 sm:mb-8">
          <div className="font-display text-[10px] sm:text-sm tracking-[0.4em] text-cyan-300 uppercase mb-2">
            Arcade Paintball Tournament
          </div>
          <h1 data-testid="home-title" className="font-arcade text-3xl sm:text-5xl lg:text-6xl text-red-500 uppercase animate-kop-pulse leading-none">
            Kings of Paintball
          </h1>
          <div className="font-display text-xl sm:text-3xl text-slate-100 tracking-widest mt-2">
            KOP 3<span className="text-red-500">×</span>3
          </div>
          <p className="mt-3 font-display text-[10px] sm:text-xs tracking-[0.45em] text-slate-500 uppercase">
            3 Players · 1 Team · 1 Champion
          </p>
        </div>

        {showHeroBanner && (
          <div className="mb-8 flex justify-center animate-kop-slam">
            <img
              src={banner}
              alt="Banner do evento"
              data-testid="home-banner"
              className="max-h-72 w-auto max-w-full object-contain border-2 border-red-900/60 kop-chamfer"
            />
          </div>
        )}

        {players.length > 0 && (
          <section data-testid="player-select" className="mb-7">
            <div className="flex items-baseline justify-between gap-2 mb-1 px-1">
              <span className="font-display text-[9px] sm:text-[10px] tracking-[0.4em] text-red-400 uppercase">
                KOP 3×3 — Player Select
              </span>
              <span className="font-mono-num text-[9px] text-slate-500 uppercase tracking-widest">
                {players.length} inscritos
              </span>
            </div>
            <PlayerSelectStrip players={players} />
          </section>
        )}

        <div className="mt-2 flex flex-col sm:flex-row gap-3 justify-center">
          <Link
            to="/register"
            data-testid="home-cta-register"
            className="kop-chamfer bg-red-600 hover:bg-red-500 text-white font-arcade uppercase tracking-widest px-8 py-3 kop-glow-red transition text-center"
          >
            ▶ Inscrever-se
          </Link>
          <Link
            to="/live"
            data-testid="home-cta-live"
            className="kop-chamfer border-2 border-cyan-500 text-cyan-300 hover:bg-cyan-500 hover:text-black font-arcade uppercase tracking-widest px-8 py-3 transition text-center"
          >
            ⚡ Modo Telão
          </Link>
        </div>

        <div className="mt-10 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3 sm:gap-4">
          {ITEMS.map((it) => {
            const Icon = it.icon;
            return (
              <Link
                key={it.key}
                to={it.to}
                data-testid={`home-menu-${it.key.toLowerCase()}`}
                className={`kop-chamfer relative border-2 bg-black/60 p-4 sm:p-5 flex flex-col items-start gap-2 transition-all ${COLOR[it.color]}`}
              >
                <Icon className="w-6 h-6" />
                <div className="font-arcade text-sm sm:text-base uppercase tracking-widest">▶ {it.label}</div>
                <div className="font-mono-num text-[10px] text-slate-500">KOP_{it.key}</div>
              </Link>
            );
          })}
        </div>

        {showFooterBanner && (
          <section data-testid="home-banner-section" className="mt-12 mb-2">
            <div className="text-center mb-3">
              <div className="font-display text-[10px] tracking-[0.4em] text-amber-400 uppercase">Evento</div>
              <div className="font-arcade text-sm sm:text-base text-white uppercase tracking-widest">KOP 3×3</div>
            </div>
            <div className="flex justify-center animate-kop-rise">
              <img
                src={banner}
                alt="Banner do evento"
                data-testid="home-banner"
                className="max-h-64 w-auto max-w-full object-contain border-2 border-red-900/60 kop-chamfer"
              />
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
