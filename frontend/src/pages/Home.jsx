import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { PlayerSelectStrip } from "../components/CharacterSelect";
import { UserPlus, Shield, Shuffle, Grid, Swords, Trophy, Users, BarChart3, GitFork, Crown, Tv, BookOpen, MessageCircle } from "lucide-react";

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

// The organizer contact is configured in the Admin panel (tournament settings),
// never hardcoded here. wa.me only accepts digits, so the label keeps whatever
// the organizer typed while the link strips the formatting.
const whatsappLink = (raw) => {
  const digits = String(raw || "").replace(/\D/g, "");
  if (!digits) return null;
  const text = encodeURIComponent("Olá! Quero falar com a organização do KOP 3×3.");
  return `https://wa.me/${digits}?text=${text}`;
};

export default function Home() {
  const [banner, setBanner] = useState(null);
  const [players, setPlayers] = useState([]);
  const [tour, setTour] = useState(null);

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
      setTour(t?.data || null);
    });
    return () => { alive = false; };
  }, []);

  const contact = whatsappLink(tour?.organizer_whatsapp);

  // Home layout is identical in production and TEST: one moving participant
  // strip in the main content and the event banner only in the footer.
  const sponsorSlotLabel = "ESPAÇO PARA PATROCINADOR";

  return (
    <div className="relative overflow-hidden">
      <div className="absolute inset-0 kop-grid-bg opacity-30 pointer-events-none" />

      <div className="relative max-w-6xl mx-auto px-4 py-8 sm:py-12">
        <section data-testid="home-select-mode">
          <div className="text-center mb-5">
            <div className="font-display text-[10px] tracking-[0.45em] text-cyan-300 uppercase">Arcade Paintball Tournament</div>
            <h1 data-testid="home-title" className="font-arcade text-3xl sm:text-5xl text-red-500 uppercase animate-kop-pulse leading-none mt-1">
              Kings of Paintball
            </h1>
          </div>

          {players.length > 0 ? (
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
          ) : (
            <p className="text-center font-display text-xs uppercase tracking-[0.4em] text-slate-500">
              Aguardando inscrições confirmadas
            </p>
          )}
        </section>

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

        <footer data-testid="home-footer" className="mt-12 pt-5 flex flex-col sm:flex-row items-center justify-between gap-5">
          <div className="flex w-full sm:w-auto flex-1 justify-center sm:justify-start">
            {banner && (
              <img
                src={banner}
                alt="Banner do evento KOP"
                data-testid="home-banner"
                className="block w-full max-w-[420px] h-[68px] sm:h-[76px] object-contain object-left"
              />
            )}
          </div>
          <div
            data-testid="home-sponsor-slot"
            aria-label="Espaço reservado para um patrocinador"
            className="min-h-[52px] w-full sm:w-[220px] flex items-center justify-center sm:justify-end font-display text-[9px] tracking-[0.3em] text-slate-700 uppercase"
          >
            {sponsorSlotLabel}
          </div>
        </footer>

        <section
          data-testid="home-credits"
          className="mt-8 border-t border-red-900/30 pt-5 text-center sm:text-left"
        >
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div className="space-y-1">
              <div className="font-display text-[10px] sm:text-[11px] uppercase tracking-[0.35em] text-slate-400">
                KOP 3×3 — Kings of Paintball
              </div>
              <p className="text-[11px] sm:text-xs leading-relaxed text-slate-500 max-w-2xl">
                Modelo de competição desenvolvido originalmente para este projeto.
              </p>
              <p className="text-[11px] sm:text-xs leading-relaxed text-slate-500 max-w-2xl">
                É proibida a reprodução, cópia para uso comercial do formato, identidade e estrutura
                deste evento sem autorização dos organizadores.
              </p>
            </div>

            <div className="flex flex-col items-center sm:items-end gap-1 shrink-0">
              <span className="font-display text-[9px] uppercase tracking-[0.3em] text-slate-600">
                Contato
              </span>
              {contact ? (
                <a
                  href={contact}
                  target="_blank"
                  rel="noopener noreferrer"
                  data-testid="home-organizer-whatsapp"
                  className="kop-chamfer inline-flex items-center gap-2 border border-green-500/50 px-3 py-2 font-display text-[10px] uppercase tracking-widest text-green-400 hover:bg-green-500/10 hover:border-green-400 transition"
                >
                  <MessageCircle className="w-4 h-4" /> WhatsApp
                </a>
              ) : (
                <span data-testid="home-organizer-whatsapp-empty" className="font-mono-num text-[10px] text-slate-700 uppercase tracking-widest">
                  a definir no painel
                </span>
              )}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
