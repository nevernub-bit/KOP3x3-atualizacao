import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { api, formatErr } from "../api";
import { useAuth } from "../auth";
import { PlayerRoster } from "../components/CharacterSelect";
import { sfx } from "../sound";
import {
  Play, Pause, RotateCcw, Shuffle, Shield, ArrowLeft, SlidersHorizontal, Users, Timer,
} from "lucide-react";

const pad2 = (n) => String(n).padStart(2, "0");
const byOrder = (a, b) => (a?.order ?? 0) - (b?.order ?? 0);

function TeamCard({ team, order, players, photosById, revealedIds, highlight = false, testId, perTeam = 0 }) {
  const roster = (team?.players || []).map((pid) => photosById.get(pid)).filter(Boolean);
  // Slot count comes from the event configuration (10×3, 8×4, 12×3 …), never
  // from a fixed number.
  const slots = Math.max(roster.length, team?.players?.length || 0, perTeam || 0);
  return (
    <div
      data-testid={testId}
      className={`kop-chamfer border-2 bg-black/70 p-2.5 ${highlight ? "border-yellow-400 kop-glow-gold" : "border-slate-700/70"}`}
    >
      <div className="flex items-center justify-between gap-2 mb-2">
        <span className="font-mono-num text-[9px] tracking-[0.25em] text-slate-500">TEAM {pad2(order + 1)}</span>
        <span className="font-mono-num text-[9px] text-cyan-300">{slots} slots</span>
      </div>
      <div className="font-display text-sm sm:text-base text-white uppercase tracking-widest truncate">
        {team?.name || `TEAM ${pad2(order + 1)}`}
      </div>
      <div className="mt-2 flex gap-1.5">
        {Array.from({ length: slots }).map((_, i) => {
          const p = roster[i];
          const filled = p && revealedIds.has(p.id);
          return (
            <div key={i} className="relative flex-1 border border-slate-800 bg-slate-950 overflow-hidden" style={{ aspectRatio: "3 / 4" }}>
              {filled ? (
                <>
                  <img src={p.photo} alt={p.name} loading="lazy" decoding="async" className="absolute inset-0 h-full w-full object-cover" />
                  <div className="absolute inset-0 bg-gradient-to-t from-black via-black/20 to-transparent" />
                  <div className="absolute bottom-0 inset-x-0 px-0.5 pb-0.5 font-display text-[7px] leading-tight text-white uppercase truncate">
                    {(p.name || "").split(" ")[0]}
                  </div>
                </>
              ) : (
                <div className="absolute inset-0 flex items-center justify-center font-arcade text-[10px] text-slate-700">?</div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function DrawEvent() {
  const { isAdmin } = useAuth();
  const [tour, setTour] = useState(null);
  const [teams, setTeams] = useState([]);
  const [players, setPlayers] = useState([]);
  // loading | waiting | ready | opening | roster | countdown | playing | done
  const [phase, setPhase] = useState("loading");
  const [countdown, setCountdown] = useState(3);
  const [revealCount, setRevealCount] = useState(0);
  const [index, setIndex] = useState(-1);
  const [revealed, setRevealed] = useState(false);
  const [highlightId, setHighlightId] = useState(null);
  const [paused, setPaused] = useState(false);
  const [runId, setRunId] = useState(0);
  const [autoplay, setAutoplay] = useState(true);
  const [busy, setBusy] = useState(false);
  const [confirmDraw, setConfirmDraw] = useState(false);
  const [drawMode, setDrawMode] = useState("BALANCED");
  const [timing, setTiming] = useState({ spin: 2.6, pause: 6 });
  const [savingTiming, setSavingTiming] = useState(false);

  const runRef = useRef(0);
  const pausedRef = useRef(false);
  const live = useRef({});
  pausedRef.current = paused;

  const load = useCallback(async () => {
    const [t, tm, p] = await Promise.all([api.get("/tournament"), api.get("/teams"), api.get("/players")]);
    const doc = t.data || null;
    setTour(doc);
    setTeams(tm.data || []);
    setPlayers(p.data || []);
    setTiming({
      spin: Number(doc?.draw_spin_seconds ?? 2.6),
      pause: Number(doc?.draw_pause_seconds ?? 6),
    });
    return doc;
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const doc = await load();
        setPhase(doc?.draw_done ? "ready" : "waiting");
      } catch {
        toast.error("Não foi possível carregar o sorteio");
        setPhase("waiting");
      }
    })();
  }, [load]);

  const photosById = useMemo(() => {
    const m = new Map();
    players.forEach((p) => m.set(p.id, p));
    return m;
  }, [players]);

  // Reveal order is derived from the persisted teams (team order, then roster
  // order). A refresh therefore replays the exact same sequence and can never
  // produce different or duplicated results.
  const assignments = useMemo(() => {
    return [...teams]
      .sort(byOrder)
      .flatMap((t) => (t.players || []).map((pid) => ({ pid, teamId: t.id, teamName: t.name, order: t.order })));
  }, [teams]);

  const total = assignments.length;
  const current = index >= 0 ? assignments[index] : null;
  const currentPlayer = current ? photosById.get(current.pid) : null;

  const revealedAssignments = useMemo(() => {
    if (index < 0) return [];
    return assignments.slice(0, revealed ? index + 1 : index);
  }, [assignments, index, revealed]);

  const revealedIds = useMemo(() => new Set(revealedAssignments.map((a) => a.pid)), [revealedAssignments]);

  const revealedTeams = useMemo(() => {
    const m = new Map();
    revealedAssignments.forEach((a) => m.set(a.teamId, (m.get(a.teamId) || 0) + 1));
    return m;
  }, [revealedAssignments]);

  const spinSeconds = Number(tour?.draw_spin_seconds ?? 2.6);
  const pauseSeconds = Number(tour?.draw_pause_seconds ?? 6);
  live.current = { assignments, players, spinSeconds, pauseSeconds };

  // The event always starts at the opening screen; the reveal loop only begins
  // after the arcade intro, so the persisted draw is presented like a show.
  const startShow = useCallback(() => {
    setIndex(-1);
    setRevealed(false);
    setHighlightId(null);
    setRevealCount(0);
    setCountdown(3);
    setPaused(false);
    setRunId((n) => n + 1);
    setPhase("opening");
  }, []);

  // Arcade intro: title card -> roster presentation -> 3·2·1 -> reveal.
  const perTeam = Number(tour?.players_per_team || 0);
  useEffect(() => {
    if (phase === "opening") {
      sfx.confirm();
      const t = setTimeout(() => setPhase("roster"), 5400);
      return () => clearTimeout(t);
    }
    if (phase === "roster") {
      const size = players.length;
      setRevealCount(0);
      const step = 165;
      const iv = setInterval(() => {
        setRevealCount((c) => {
          if (c >= size) return c;
          sfx.select();
          return c + 1;
        });
      }, step);
      const t = setTimeout(() => setPhase("countdown"), 1700 + size * step);
      return () => { clearInterval(iv); clearTimeout(t); };
    }
    if (phase === "countdown") {
      let n = 3;
      setCountdown(3);
      sfx.countdown();
      const iv = setInterval(() => {
        n -= 1;
        if (n >= 1) { setCountdown(n); sfx.countdown(); }
        else if (n === 0) { setCountdown(0); sfx.fight(); }
        else { clearInterval(iv); setPhase("playing"); }
      }, 950);
      return () => clearInterval(iv);
    }
  }, [phase, runId, players.length]);

  // Telão-friendly: once a persisted draw exists the show starts by itself.
  useEffect(() => {
    if (phase !== "ready" || !autoplay) return;
    const t = setTimeout(() => startShow(), 2200);
    return () => clearTimeout(t);
  }, [phase, autoplay, startShow]);

  // Reveal loop. It only reads the persisted assignments and never calls the
  // draw endpoint again.
  useEffect(() => {
    if (phase !== "playing") return;
    const my = ++runRef.current;
    let cancelled = false;
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    const gate = async () => { while (pausedRef.current && !cancelled) await sleep(120); };

    (async () => {
      const { assignments: list, players: roster, spinSeconds: spin, pauseSeconds: hold } = live.current;
      const pool = roster.map((p) => p.id);
      if (!list.length) { setPhase("done"); return; }

      for (let i = 0; i < list.length; i++) {
        await gate();
        if (cancelled || my !== runRef.current) return;
        setIndex(i);
        setRevealed(false);

        const duration = Math.max(900, spin * 1000);
        const started = Date.now();
        let gap = 45;
        while (Date.now() - started < duration) {
          await gate();
          if (cancelled || my !== runRef.current) return;
          setHighlightId(pool[Math.floor(Math.random() * pool.length)] ?? null);
          await sleep(gap);
          const progress = Math.min(1, (Date.now() - started) / duration);
          gap = 45 + Math.pow(progress, 2) * 240;
        }
        if (cancelled || my !== runRef.current) return;

        const target = list[i];
        if (!target) continue;
        setHighlightId(target.pid);
        setRevealed(true);
        sfx.reveal();
        await sleep(260);
        if (cancelled || my !== runRef.current) return;
        sfx.teamReady();
        await gate();
        await sleep(Math.max(800, hold * 1000));
      }

      if (cancelled || my !== runRef.current) return;
      setIndex(-1);
      setRevealed(false);
      setPhase("done");
      sfx.champion();
    })();

    return () => { cancelled = true; runRef.current += 1; };
  }, [phase, runId]);

  // Waiting room: a light poll (every 5s, tournament document only) so a telão
  // picks up the draw started from another device.
  useEffect(() => {
    if (phase !== "waiting") return;
    let alive = true;
    const iv = setInterval(async () => {
      try {
        const r = await api.get("/tournament");
        if (!alive) return;
        if (r.data?.draw_done) {
          await load();
          if (!alive) return;
          setPhase("ready");
        }
      } catch { /* a failed poll must not break the screen */ }
    }, 5000);
    return () => { alive = false; clearInterval(iv); };
  }, [phase, load]);

  const runDraw = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await api.post("/draw", {
        num_teams: tour?.num_teams ?? 10,
        players_per_team: tour?.players_per_team ?? 3,
        num_groups: tour?.num_groups ?? 2,
        qualifiers_per_group: tour?.qualifiers_per_group ?? 2,
        mode: drawMode,
      });
      await load();
      setConfirmDraw(false);
      setPhase("ready");
      toast.success("Sorteio realizado");
    } catch (e) {
      toast.error(formatErr(e?.response?.data?.detail) || "Falha ao realizar o sorteio");
    } finally {
      setBusy(false);
    }
  };

  const saveTiming = async () => {
    if (savingTiming) return;
    setSavingTiming(true);
    try {
      const r = await api.patch("/tournament", {
        draw_spin_seconds: Number(timing.spin),
        draw_pause_seconds: Number(timing.pause),
      });
      setTour((prev) => ({ ...prev, ...(r.data || {}) }));
      toast.success("Tempos do sorteio salvos");
    } catch (e) {
      toast.error(formatErr(e?.response?.data?.detail) || "Falha ao salvar os tempos");
    } finally {
      setSavingTiming(false);
    }
  };

  const waiting = phase === "waiting" && !tour?.draw_done;
  const showFinal = phase === "done";
  const introPhase = phase === "opening" || phase === "roster" || phase === "countdown";
  const roster = players.map((p) => ({ id: p.id, name: p.name, nickname: p.nickname, level: p.level, photo: p.photo }));
  const remaining = total > 0 ? Math.max(0, total - (index + 1)) : 0;

  return (
    <div className="min-h-screen kop-grid-bg bg-black/40">
      <div className="max-w-[1500px] mx-auto px-3 sm:px-6 py-5 sm:py-8">
        <div className="flex flex-wrap items-center gap-3 justify-between mb-5">
          <Link to="/" className="inline-flex items-center gap-1.5 font-display text-[10px] uppercase tracking-[0.3em] text-slate-400 hover:text-white">
            <ArrowLeft className="w-3.5 h-3.5" /> Voltar
          </Link>
          <div className="text-center flex-1 min-w-[220px]">
            <div className="font-display text-[9px] sm:text-[11px] tracking-[0.45em] text-red-400 uppercase">
              KOP 3×3 — {showFinal ? "Team Select" : "Player Select"}
            </div>
            <h1 className="font-arcade text-xl sm:text-3xl text-white uppercase leading-tight">
              {waiting
                ? "Aguardando sorteio"
                : showFinal
                  ? "Times formados"
                  : phase === "opening"
                    ? "KOP 3×3 — Official Draw"
                    : phase === "roster"
                      ? "Player Select"
                      : phase === "countdown"
                        ? "Get Ready"
                        : "Sorteio das equipes"}
            </h1>
          </div>
          <div className="flex items-center gap-2 font-mono-num text-[10px] uppercase tracking-widest">
            <span className={`inline-flex items-center gap-1.5 px-2 py-1 border ${phase === "playing" ? "border-red-500 text-red-300" : "border-slate-700 text-slate-400"}`}>
              <span className={`w-1.5 h-1.5 rounded-full ${phase === "playing" ? "bg-red-500 animate-pulse" : "bg-slate-500"}`} />
              {phase === "playing" ? (paused ? "paused" : "live") : phase}
            </span>
          </div>
        </div>

        {isAdmin && (
          <div className="kop-chamfer border border-slate-700 bg-black/70 p-3 mb-5 flex flex-wrap items-center gap-2 sm:gap-3">
            <div className="flex gap-1.5">
              {["BALANCED", "NORMAL"].map((m) => (
                <button key={m} onClick={() => setDrawMode(m)} disabled={busy || phase === "playing"}
                  className={`px-2.5 py-1 text-[10px] font-display uppercase tracking-widest border ${drawMode === m ? "border-red-500 text-red-300 bg-red-500/10" : "border-slate-700 text-slate-400"}`}>
                  {m === "BALANCED" ? "Balanceado" : "Normal"}
                </button>
              ))}
            </div>

            {confirmDraw ? (
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[10px] text-yellow-400 font-display uppercase tracking-widest">
                  {tour?.draw_done
                    ? "Refazer o sorteio substitui equipes e tabela atuais. Confirmar?"
                    : "Executar o sorteio oficial agora?"}
                </span>
                <button onClick={runDraw} disabled={busy}
                  className="kop-chamfer bg-red-600 hover:bg-red-500 disabled:opacity-50 text-white font-arcade uppercase tracking-widest px-3 py-1.5 text-xs">
                  {busy ? "Sorteando…" : "Confirmar sorteio"}
                </button>
                <button onClick={() => setConfirmDraw(false)} disabled={busy}
                  className="kop-chamfer border border-slate-700 text-slate-400 px-3 py-1.5 text-xs font-arcade uppercase">
                  Cancelar
                </button>
              </div>
            ) : (
              <button onClick={() => setConfirmDraw(true)} disabled={busy || phase === "playing"}
                className="kop-chamfer bg-red-600 hover:bg-red-500 disabled:opacity-50 text-white font-arcade uppercase tracking-widest px-4 py-1.5 text-xs inline-flex items-center gap-1.5"
                data-testid="draw-start-btn">
                <Shuffle className="w-3.5 h-3.5" /> {tour?.draw_done ? "Refazer sorteio" : "Iniciar sorteio"}
              </button>
            )}

            <div className="h-6 w-px bg-slate-700" />

            <button onClick={() => setPaused((p) => !p)} disabled={phase !== "playing"}
              className="kop-chamfer border-2 border-cyan-600 text-cyan-300 disabled:opacity-40 px-3 py-1.5 text-xs font-arcade uppercase inline-flex items-center gap-1.5">
              {paused ? <Play className="w-3.5 h-3.5" /> : <Pause className="w-3.5 h-3.5" />} {paused ? "Continuar" : "Pausar"}
            </button>
            <button onClick={startShow} disabled={!tour?.draw_done || busy}
              className="kop-chamfer border border-slate-700 text-slate-300 disabled:opacity-40 px-3 py-1.5 text-xs font-arcade uppercase inline-flex items-center gap-1.5">
              <RotateCcw className="w-3.5 h-3.5" /> Reiniciar apresentação
            </button>
            <label className="inline-flex items-center gap-1.5 text-[10px] font-display uppercase tracking-widest text-slate-400">
              <input type="checkbox" checked={autoplay} onChange={(e) => setAutoplay(e.target.checked)} className="accent-red-500" />
              Auto-play
            </label>

            <div className="h-6 w-px bg-slate-700" />

            <div className="flex items-center gap-2 text-[10px] font-display uppercase tracking-widest text-slate-400">
              <SlidersHorizontal className="w-3.5 h-3.5 text-amber-400" />
              <label className="flex items-center gap-1">
                Giro (s)
                <input type="number" min="1" max="10" step="0.2" value={timing.spin}
                  onChange={(e) => setTiming((t) => ({ ...t, spin: e.target.value }))}
                  className="w-14 bg-slate-900 border border-slate-700 px-1 py-0.5 text-white text-xs" />
              </label>
              <label className="flex items-center gap-1">
                Pausa (s)
                <input type="number" min="1" max="30" step="0.5" value={timing.pause}
                  onChange={(e) => setTiming((t) => ({ ...t, pause: e.target.value }))}
                  className="w-14 bg-slate-900 border border-slate-700 px-1 py-0.5 text-white text-xs" />
              </label>
              <button onClick={saveTiming} disabled={savingTiming}
                className="kop-chamfer border border-amber-500/70 text-amber-300 px-2 py-1 text-[10px] uppercase">
                {savingTiming ? "…" : "Salvar"}
              </button>
            </div>
          </div>
        )}

        {waiting && (
          <div className="kop-chamfer border-2 border-slate-700 bg-black/70 p-6 text-center mb-5">
            <div className="font-arcade text-lg sm:text-2xl text-slate-200 uppercase animate-kop-flicker">Aguardando o sorteio</div>
            <p className="text-slate-400 text-xs sm:text-sm mt-2 font-display uppercase tracking-widest">
              O organizador inicia o sorteio. Esta tela atualiza sozinha.
            </p>
          </div>
        )}

        {introPhase ? (
          <section
            data-testid={`draw-${phase}`}
            className="relative kop-chamfer border-2 border-red-900/60 bg-black/85 overflow-hidden min-h-[440px] sm:min-h-[520px] flex items-center justify-center animate-kop-rise"
          >
            <div className="pointer-events-none absolute inset-0 kop-diag-bg opacity-25" />
            <div className="pointer-events-none absolute inset-x-0 top-0 h-1.5 bg-gradient-to-r from-transparent via-red-500 to-transparent animate-kop-pulse" />

            {phase === "opening" && (
              <div className="relative text-center px-4 py-10">
                <div className="font-display text-[10px] sm:text-xs tracking-[0.6em] text-cyan-300 uppercase mb-3">
                  Kings of Paintball
                </div>
                <div className="font-arcade text-4xl sm:text-6xl lg:text-7xl text-red-500 uppercase leading-none animate-kop-pulse">
                  KOP 3<span className="text-white">×</span>3
                </div>
                <div className="mt-5 font-display text-base sm:text-2xl text-white tracking-[0.35em] uppercase">
                  Official Team Draw
                </div>
                <div className="mt-4 font-mono-num text-[10px] sm:text-xs text-slate-400 uppercase tracking-[0.3em]">
                  {tour?.num_teams ?? "—"} teams · {perTeam || "—"} players per team · {players.length} inscritos
                </div>
                <div className="mt-9 font-arcade text-xs sm:text-sm text-yellow-300 uppercase tracking-[0.45em] animate-kop-flicker">
                  PRESS START
                </div>
              </div>
            )}

            {phase === "roster" && (
              <div className="relative w-full px-3 sm:px-6 py-5">
                <div className="text-center mb-4">
                  <div className="font-display text-[10px] tracking-[0.45em] text-red-400 uppercase">Player Select</div>
                  <div className="font-arcade text-xl sm:text-3xl text-white uppercase">{players.length} jogadores confirmados</div>
                </div>
                <PlayerRoster players={roster} dense revealCount={revealCount} />
              </div>
            )}

            {phase === "countdown" && (
              <div className="relative text-center px-4">
                <div
                  key={countdown}
                  className={`font-arcade uppercase leading-none animate-kop-slam ${countdown > 0 ? "text-7xl sm:text-9xl text-red-500" : "text-5xl sm:text-7xl text-yellow-300"}`}
                >
                  {countdown > 0 ? countdown : "FIGHT!"}
                </div>
                <div className="mt-4 font-display text-[10px] sm:text-sm uppercase tracking-[0.45em] text-slate-300">
                  Sorteio oficial em andamento
                </div>
              </div>
            )}
          </section>
        ) : showFinal ? (
          <section data-testid="draw-final" className="animate-kop-rise">
            <div className="text-center mb-4">
              <div className="font-arcade text-lg sm:text-2xl text-yellow-300 uppercase">KOP 3×3 — Team Select</div>
              <div className="font-display text-[10px] tracking-[0.4em] text-slate-400 uppercase mt-1">
                {teams.length} teams · {total} players
              </div>
            </div>
            <div className={`grid gap-3 ${teams.length <= 3 ? "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3" : "grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5"}`}>
              {[...teams].sort(byOrder).map((t, i) => (
                <TeamCard key={t.id} team={t} order={t.order ?? i} photosById={photosById} perTeam={perTeam}
                  revealedIds={new Set(t.players || [])} testId={`final-team-${t.id}`} />
              ))}
            </div>
            {isAdmin && (
              <div className="text-center mt-6">
                <button onClick={startShow} className="kop-chamfer border-2 border-red-600 text-red-300 hover:bg-red-600 hover:text-white px-5 py-2 font-arcade uppercase tracking-widest text-sm inline-flex items-center gap-2">
                  <Play className="w-4 h-4" /> Repetir apresentação
                </button>
              </div>
            )}
          </section>
        ) : (
          <div className="grid lg:grid-cols-[1fr_320px] gap-4 sm:gap-6">
            <section className="relative">
              <div className="flex items-center justify-between gap-2 mb-2 font-mono-num text-[10px] uppercase tracking-widest text-slate-400">
                <span className="inline-flex items-center gap-1.5">
                  <Users className="w-3.5 h-3.5 text-red-400" />
                  {total ? `Player ${Math.min(index + 1, total)}/${total}` : "Sem sorteio"}
                </span>
                <span className="inline-flex items-center gap-1.5">
                  <Timer className="w-3.5 h-3.5 text-cyan-300" />
                  {spinSeconds}s giro · {pauseSeconds}s pausa
                </span>
              </div>

              <div className="relative kop-chamfer border-2 border-red-900/60 bg-black/70 p-2 sm:p-3 overflow-hidden">
                <div className="pointer-events-none absolute inset-0 kop-diag-bg opacity-30" />
                {phase === "playing" && (
                  <div className="absolute inset-x-0 top-0 h-1.5 bg-gradient-to-r from-transparent via-red-500 to-transparent animate-kop-pulse" />
                )}
                <div className="relative">
                  <PlayerRoster
                    players={roster}
                    highlightId={revealed ? current?.pid : highlightId}
                    selectedId={revealed ? current?.pid : null}
                  />
                </div>

                {phase === "playing" && !revealed && (
                  <div className="pointer-events-none absolute inset-0 flex items-end justify-center pb-4">
                    <div className="font-arcade text-sm sm:text-xl text-red-300 uppercase tracking-[0.35em] animate-kop-flicker bg-black/70 px-3 py-1 border border-red-500/60">
                      Selecionando…
                    </div>
                  </div>
                )}
              </div>

              {revealed && current && (
                <div key={`${current.pid}-${index}`} className="mt-4 animate-kop-slam">
                  <div className="kop-chamfer border-2 border-yellow-400 kop-glow-gold bg-black/85 p-3 sm:p-5 flex items-center gap-4">
                    <div className="w-20 h-24 sm:w-24 sm:h-28 shrink-0 border-2 border-yellow-400/70 overflow-hidden bg-slate-900">
                      {currentPlayer?.photo
                        ? <img src={currentPlayer.photo} alt={currentPlayer?.name || "Jogador"} className="h-full w-full object-cover" />
                        : <div className="h-full w-full flex items-center justify-center font-arcade text-slate-600">?</div>}
                    </div>
                    <div className="min-w-0">
                      <div className="font-display text-[9px] sm:text-[11px] tracking-[0.45em] text-yellow-300 uppercase">Player selected</div>
                      <div className="font-arcade text-lg sm:text-3xl text-white uppercase leading-tight truncate">
                        {currentPlayer?.name || "—"}
                      </div>
                      {currentPlayer?.nickname && (
                        <div className="font-mono-num text-[10px] sm:text-xs text-cyan-300 uppercase tracking-widest">"{currentPlayer.nickname}"</div>
                      )}
                      <div className="mt-2 inline-flex items-center gap-1.5 font-display uppercase tracking-widest text-[10px] sm:text-xs text-slate-300">
                        <Shield className="w-3.5 h-3.5 text-red-400" /> Team:
                        <span className="text-white font-arcade text-xs sm:text-base">{current.teamName || "—"}</span>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {phase === "ready" && (
                <div className="mt-4 text-center">
                  <button onClick={startShow} className="kop-chamfer bg-red-600 hover:bg-red-500 text-white px-6 py-3 font-arcade uppercase tracking-widest inline-flex items-center gap-2">
                    <Play className="w-4 h-4" /> Iniciar apresentação
                  </button>
                </div>
              )}
            </section>

            <aside>
              <div className="font-display text-[10px] tracking-[0.35em] text-slate-400 uppercase mb-2">
                Equipes {remaining > 0 ? `· ${remaining} restantes` : ""}
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-1 gap-2 max-h-[70vh] overflow-auto pr-1">
                {[...teams].sort(byOrder).map((t, i) => (
                  <TeamCard key={t.id} team={t} order={t.order ?? i} photosById={photosById} perTeam={perTeam}
                    revealedIds={revealedIds}
                    highlight={revealed && current?.teamId === t.id}
                    testId={`board-team-${t.id}`} />
                ))}
              </div>
            </aside>
          </div>
        )}

        <div className="mt-6 text-center font-display text-[9px] uppercase tracking-[0.4em] text-slate-600">
          Resultado oficial persistido · esta tela apenas revela o sorteio
        </div>
      </div>
    </div>
  );
}
