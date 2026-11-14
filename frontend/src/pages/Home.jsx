import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { PlayerSelectStrip, PlayerSelectWall } from "../components/CharacterSelect";
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
  // SELECT = participants only · BANNER = KOP identity only · AUTO = both, timed.
  const [stage, setStage] = useState("SELECT");

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

  // Only AUTO rotates. SELECT and BANNER are fixed compositions, which is the
  // whole point of the three modes: one is about the players, the other about
  // the KOP identity.
  useEffect(() => {
    if (!playersReady) return;
    if (mode !== "AUTO") {
      setStage(mode === "BANNER" ? "BANNER" : "SELECT");
      return undefined;
    }
    let current = "SELECT";
    let timer = null;
    setStage(current);
    const schedule = () => {
      const waitFor = current === "SELECT" ? selectSeconds : bannerSeconds;
      timer = setTimeout(() => {
        current = current === "SELECT" ? "BANNER" : "SELECT";
        setStage(current);
        schedule();
      }, waitFor * 1000);
    };
    schedule();
    return () => clearTimeout(timer);
  }, [mode, selectSeconds, bannerSeconds, playersReady]);

  const showingBanner = stage === "BANNER";
  const eventLine = cfg
    ? `${cfg.num_teams ?? "—"} equipes · ${cfg.players_per_team ?? "—"} jogadores por equipe · ${cfg.capacity ?? "—"} vagas`
    : "3 players · 1 team · 1 champion";

  return (
    <div className="relative overflow-hidden">
      <div className="absolute inset-0 kop-grid-bg opacity-30 pointer-events-none" />

      <div className="relative max-w-6xl mx-auto px-4 py-8 sm:py-12">
        {showingBanner ? (
          /* ---------- MODO B: identidade KOP ---------- */
          <section data-testid="home-banner-mode" className="animate-kop-rise">
            <div className="text-center mb-4">
              <div className="font-display text-[10px] tracking-[0.45em] text-cyan-300 uppercase">Kings of Paintball</div>
              <h1 data-testid="home-title" className="font-arcade text-2xl sm:text-4xl text-red-500 uppercase animate-kop-pulse leading-none mt-1">
                KOP 3<span className="text-white">×</span>3
              </h1>
            </div>

            <div className="relative kop-chamfer border-2 border-red-900/60 bg-black overflow-hidden">
              <div className="pointer-events-none absolute inset-0 kop-diag-bg opacity-20" />
              {banner ? (
                <div className="flex items-center justify-center">
                  <img
                    src={banner}
                    alt="Banner do evento"
                    data-testid="home-banner"
                    className="max-h-[56vh] w-auto max-w-full object-contain"
                  />
                </div>
              ) : (
                <div className="relative flex flex-col items-center justify-center gap-3 py-14 px-6">
                  <img src={`${process.env.PUBLIC_URL || ""}/kop-logo.png`} alt="KOP" className="w-20 h-20 sm:w-24 sm:h-24" />
                  <div className="font-arcade text-3xl sm:text-5xl text-white uppercase leading-none">
                    KINGS OF PAINTBALL
                  </div>
                  <div className="font-display text-[11px] tracking-[0.5em] text-amber-300 uppercase">
                    KOP 3×3 — Evento oficial
                  </div>
                </div>
              )}
              <div className="pointer-events-none absolute inset-x-0 bottom-0 px-4 pb-3 pt-8 bg-gradient-to-t from-black via-black/70 to-transparent">
                <div className="font-display text-[10px] sm:text-xs tracking-[0.4em] text-white/85 uppercase">
                  KOP 3×3 — Kings of Paintball
                </div>
                <div className="font-mono-num text-[10px] text-cyan-300 uppercase tracking-widest">{eventLine}</div>
              </div>
            </div>
          </section>
        ) : (
          /* ---------- MODO A: Character Select ---------- */
          <section data-testid="home-select-mode">
            <div className="text-center mb-5">
              <div className="font-display text-[10px] tracking-[0.45em] text-cyan-300 uppercase">Arcade Paintball Tournament</div>
              <h1 data-testid="home-title" className="font-arcade text-3xl sm:text-5xl text-red-500 uppercase animate-kop-pulse leading-none mt-1">
                Kings of Paintball
              </h1>
            </div>

            {players.length > 0 ? (
              <>
                <div className="mb-7" data-testid="player-select">
                  <div className="flex items-baseline justify-between gap-2 mb-1 px-1">
                    <span className="font-display text-[9px] sm:text-[10px] tracking-[0.4em] text-red-400 uppercase">
                      KOP 3×3 — Player Select
                    </span>
                    <span className="font-mono-num text-[9px] text-slate-500 uppercase tracking-widest">
                      {players.length} inscritos
                    </span>
                  </div>
                  <PlayerSelectStrip players={players} />
                </div>

                <div data-testid="home-player-wall" className="kop-chamfer border border-slate-800/70 bg-black/40 p-2 sm:p-3">
                  <div className="h-[min(46vh,420px)] min-h-[240px]">
                    <PlayerSelectWall players={players} maxCardWidth={132} gap={6} />
                  </div>
                </div>
              </>
            ) : (
              <p className="text-center font-display text-xs uppercase tracking-[0.4em] text-slate-500">
                Aguardando inscrições confirmadas
              </p>
            )}
          </section>
        )}

        <div className="mt-7 flex flex-col sm:flex-row gap-3 justify-center">
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
      </div>
    </div>
  );
}
