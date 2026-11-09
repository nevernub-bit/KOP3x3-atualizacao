import React, { useEffect, useMemo, useRef, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { PlayerCard } from "../components/PlayerCard";
import { toast } from "sonner";
import { sfx } from "../sound";
import { Play, Pause, Square, Undo2, Clock, Lock, Unlock } from "lucide-react";

function fmtTime(ms) {
  if (ms == null) return "00:00";
  const totalS = Math.max(0, Math.round(ms / 1000));
  const m = String(Math.floor(totalS / 60)).padStart(2, "0");
  const s = String(totalS % 60).padStart(2, "0");
  return `${m}:${s}`;
}

export default function MatchDetail() {
  const { mid } = useParams();
  const { isAdmin } = useAuth();
  const [match, setMatch] = useState(null);
  const [teams, setTeams] = useState([]);
  const [players, setPlayers] = useState([]);
  const [tick, setTick] = useState(0);
  const [selEliminated, setSelEliminated] = useState("");
  const [perfectOverlay, setPerfectOverlay] = useState(false);
  const [showResult, setShowResult] = useState(false);
  const [confirmAction, setConfirmAction] = useState(null);
  const [actionBusy, setActionBusy] = useState(false);
  const actionInFlight = useRef(false);
  const loadVersion = useRef(0);
  const lastAnnouncedRef = useRef({ elim: 0, warn: {}, ended: false });

  const load = async () => {
    const version = ++loadVersion.current;
    const [m, t, p] = await Promise.all([
      api.get(`/matches/${mid}`), api.get("/teams"), api.get("/players"),
    ]);
    if (version !== loadVersion.current) return;
    setMatch(m.data); setTeams(t.data); setPlayers(p.data);
  };
  useEffect(() => { load().catch(() => toast.error("Não foi possível carregar os dados da partida")); }, [mid]);

  useEffect(() => {
    if (!match) return;
    if (match.status === "EM_ANDAMENTO" || match.status === "PAUSADA") {
      const iv = setInterval(() => {
        if (!actionInFlight.current) load().catch(() => {});
      }, 1500);
      return () => clearInterval(iv);
    }
  }, [match?.status]);

  useEffect(() => {
    if (match?.status !== "EM_ANDAMENTO") return;
    const iv = setInterval(() => setTick(t => t + 1), 250);
    return () => clearInterval(iv);
  }, [match?.status]);

  const remainingMs = useMemo(() => {
    if (!match) return 0;
    if (match.status === "EM_ANDAMENTO" && match.started_at) {
      const started = new Date(match.started_at).getTime();
      const elapsed = Date.now() - started - (match.pause_accumulated_ms || 0);
      return Math.max(0, match.duration_seconds * 1000 - elapsed);
    }
    return match.remaining_ms ?? match.duration_seconds * 1000;
  }, [match, tick]);

  useEffect(() => {
    if (!match || match.status !== "EM_ANDAMENTO") return;
    const secs = Math.ceil(remainingMs / 1000);
    const w = lastAnnouncedRef.current.warn;
    if (secs === 60 && !w[60]) { w[60] = true; sfx.timeWarn(); toast.warning("1 minuto restante"); }
    if (secs === 30 && !w[30]) { w[30] = true; sfx.timeWarn(); }
    if (secs <= 10 && secs > 0 && !w[secs]) { w[secs] = true; sfx.countdown(); }
  }, [remainingMs, match?.status]);

  useEffect(() => {
    if (!match) return;
    const total = (match.eliminations || []).length;
    if (total > lastAnnouncedRef.current.elim) sfx.elim();
    lastAnnouncedRef.current.elim = total;

    if (match.status === "ENCERRADA" && !lastAnnouncedRef.current.ended) {
      lastAnnouncedRef.current.ended = true;
      setShowResult(true);
      if (match.perfect_a || match.perfect_b) {
        setPerfectOverlay(true); sfx.perfect();
        setTimeout(() => setPerfectOverlay(false), 3500);
      } else if (match.is_draw) { sfx.draw(); }
      else { sfx.winner(); }
    }
  }, [match?.eliminations?.length, match?.status]);

  if (!match) return <div className="p-8 text-center text-slate-500">Carregando...</div>;

  const teamA = teams.find(t => t.id === match.team_a);
  const teamB = teams.find(t => t.id === match.team_b);
  const byId = Object.fromEntries(players.map(p => [p.id, p]));
  const rosterA = (teamA?.players || []).map(pid => byId[pid]).filter(Boolean);
  const rosterB = (teamB?.players || []).map(pid => byId[pid]).filter(Boolean);
  const elims = match.eliminations || [];
  const eliminatedIds = new Set(elims.map(e => e.eliminated_id));
  const isEliminated = (pid) => eliminatedIds.has(pid);
  const aliveA = rosterA.filter(p => !isEliminated(p.id));
  const aliveB = rosterB.filter(p => !isEliminated(p.id));

  // Only alive players can be marked eliminated
  const eliminatedOptions = [...aliveA, ...aliveB];

  const runMatchMutation = async (request, errorMessage = "Erro") => {
    if (actionInFlight.current) return null;
    actionInFlight.current = true;
    loadVersion.current += 1;
    setActionBusy(true);
    try {
      const r = await request();
      setMatch(r.data);
      return r.data;
    } catch (e) {
      sfx.error();
      toast.error(e.response?.data?.detail || errorMessage);
      return null;
    } finally {
      actionInFlight.current = false;
      setActionBusy(false);
    }
  };
  const runAction = (action, args = {}) => runMatchMutation(() => api.post(`/matches/${mid}/${action}`, args));

  const startMatch = async () => {
    sfx.vs();
    const result = await runMatchMutation(async () => {
      await new Promise(r => setTimeout(r, 200));
      sfx.countdown(); await new Promise(r => setTimeout(r, 500));
      sfx.countdown(); await new Promise(r => setTimeout(r, 500));
      sfx.countdown(); await new Promise(r => setTimeout(r, 500));
      sfx.fight();
      return api.post(`/matches/${mid}/start`);
    });
    if (result) lastAnnouncedRef.current = { elim: match.eliminations?.length || 0, warn: {}, ended: false };
  };
  const pauseMatch = async () => { sfx.back(); await runAction("pause"); };
  const resumeMatch = async () => { sfx.confirm(); await runAction("resume"); };
  const endMatch = async () => {
    setConfirmAction(null);
    sfx.timeUp();
    await runAction("end");
  };
  const undo = async () => {
    setConfirmAction(null);
    const result = await runMatchMutation(() => api.delete(`/matches/${mid}/eliminate/last`));
    if (result) sfx.back();
  };
  const toggleLock = () => runMatchMutation(() => api.post(`/matches/${mid}/lock`), "Erro ao alterar bloqueio");
  const submitElim = async () => {
    if (!selEliminated) return toast.error("Selecione o jogador eliminado");
    const result = await runMatchMutation(() => api.post(`/matches/${mid}/eliminate`, { eliminated_id: selEliminated }));
    if (result) setSelEliminated("");
  };
  const chooseWinner = (teamId) => runMatchMutation(() => api.post(`/matches/${mid}/set-winner`, { winner_team_id: teamId }));

  const canEdit = isAdmin && !match.locked;
  const running = match.status === "EM_ANDAMENTO";
  const paused = match.status === "PAUSADA";
  const finished = match.status === "ENCERRADA";
  const waiting = match.status === "AGUARDANDO";
  const winnerTeam = teams.find(t => t.id === match.winner_team_id);

  return (
    <div className="max-w-6xl mx-auto px-4 py-6">
      <div className="text-center mb-3">
        <div className="font-arcade text-red-400 text-sm tracking-widest uppercase">MATCH {String(match.number).padStart(2, "0")}</div>
        <div className="font-display text-xs text-cyan-300 tracking-widest uppercase">{match.phase}{match.group ? ` — GRUPO ${match.group}` : ""}</div>
      </div>

      <div className="bg-black/70 border-2 border-red-900/50 kop-chamfer p-4 mb-6">
        <div className="flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <Clock className={`w-6 h-6 ${running ? "text-red-400" : paused ? "text-yellow-400" : "text-slate-500"}`} />
            <div data-testid="match-timer"
              className={`font-mono-num text-5xl sm:text-6xl font-black leading-none ${running && Math.ceil(remainingMs/1000) <= 10 ? "text-red-500 animate-kop-pulse" : paused ? "text-yellow-400" : "text-white"}`}
              style={{ letterSpacing: "0.05em" }}>
              {fmtTime(remainingMs)}
            </div>
            <div className="text-xs font-display uppercase tracking-widest text-slate-500">
              {waiting && "AGUARDANDO"}
              {running && "EM ANDAMENTO"}
              {paused && "PAUSADA"}
              {finished && (match.is_draw ? "EMPATE" : "ENCERRADA")}
            </div>
          </div>

          {isAdmin && !match.locked && (
            <div className="flex flex-wrap gap-2">
              {waiting && (
                <button data-testid="start-match-btn" onClick={startMatch} disabled={actionBusy} className="kop-chamfer bg-red-600 hover:bg-red-500 disabled:opacity-50 text-white font-arcade uppercase tracking-widest px-4 py-2 flex items-center gap-2 kop-glow-red">
                  <Play className="w-4 h-4" /> Start
                </button>
              )}
              {running && (
                <>
                  <button data-testid="pause-match-btn" onClick={pauseMatch} disabled={actionBusy} className="kop-chamfer border-2 border-yellow-500 text-yellow-400 hover:bg-yellow-500 hover:text-black disabled:opacity-50 font-arcade uppercase tracking-widest px-4 py-2 flex items-center gap-2">
                    <Pause className="w-4 h-4" /> Pause
                  </button>
                  <button data-testid="end-match-btn" onClick={() => setConfirmAction("end")} disabled={actionBusy} className="kop-chamfer border-2 border-slate-600 text-slate-300 hover:border-red-500 hover:text-red-400 disabled:opacity-50 font-arcade uppercase tracking-widest px-4 py-2 flex items-center gap-2">
                    <Square className="w-4 h-4" /> End
                  </button>
                </>
              )}
              {paused && (
                <>
                  <button data-testid="resume-match-btn" onClick={resumeMatch} disabled={actionBusy} className="kop-chamfer bg-red-600 hover:bg-red-500 disabled:opacity-50 text-white font-arcade uppercase tracking-widest px-4 py-2 flex items-center gap-2 kop-glow-red">
                    <Play className="w-4 h-4" /> Resume
                  </button>
                  <button data-testid="end-match-btn-p" onClick={() => setConfirmAction("end")} disabled={actionBusy} className="kop-chamfer border-2 border-slate-600 text-slate-300 hover:border-red-500 hover:text-red-400 disabled:opacity-50 font-arcade uppercase tracking-widest px-4 py-2 flex items-center gap-2">
                    <Square className="w-4 h-4" /> End
                  </button>
                </>
              )}
            </div>
          )}
          {isAdmin && (
            <button data-testid="lock-toggle-btn" onClick={toggleLock} disabled={actionBusy} className="text-slate-500 hover:text-red-400 border border-slate-700 kop-chamfer p-2 disabled:opacity-50" title={match.locked ? "Desbloquear" : "Bloquear"}>
              {match.locked ? <Lock className="w-4 h-4" /> : <Unlock className="w-4 h-4" />}
            </button>
          )}
        </div>

        <div className="mt-4 grid grid-cols-[1fr,auto,1fr] gap-3 items-center">
          <div className="text-right">
            <div className="font-arcade text-xl text-red-400 uppercase truncate">{teamA?.name}</div>
            <div className="text-xs text-slate-500 uppercase font-display tracking-widest">{aliveA.length}/{rosterA.length} vivos · Elims {match.elims_a}</div>
          </div>
          <div className="text-center">
            <div className="font-mono-num text-4xl sm:text-6xl font-black">
              <span className={match.winner_team_id === match.team_a ? "text-yellow-400" : "text-white"}>{match.elims_a}</span>
              <span className="text-slate-600 mx-2">×</span>
              <span className={match.winner_team_id === match.team_b ? "text-yellow-400" : "text-white"}>{match.elims_b}</span>
            </div>
            <div className="text-[10px] font-display tracking-widest uppercase text-slate-500">Eliminações ao vivo</div>
            {finished && (
              <div className="mt-1 font-mono-num text-xs text-cyan-300">Pts {match.points_a} · {match.points_b}</div>
            )}
          </div>
          <div>
            <div className="font-arcade text-xl text-cyan-300 uppercase truncate">{teamB?.name}</div>
            <div className="text-xs text-slate-500 uppercase font-display tracking-widest">{aliveB.length}/{rosterB.length} vivos · Elims {match.elims_b}</div>
          </div>
        </div>

        <div className="mt-3 text-center">
          <Link to={`/versus/${mid}`} onClick={() => sfx.vs()} className="text-xs text-cyan-300 hover:text-cyan-200 font-display tracking-widest uppercase">▶ TELA VERSUS</Link>
        </div>
      </div>

      <div className="grid md:grid-cols-2 gap-4 mb-6">
        {[{ team: teamA, roster: rosterA, color: "text-red-400" }, { team: teamB, roster: rosterB, color: "text-cyan-300" }].map((side, si) => (
          <div key={si} className="bg-black/60 border border-slate-800 kop-chamfer p-3">
            <div className={`font-arcade text-lg ${side.color} uppercase mb-2 text-center`}>{side.team?.name}</div>
            <div className="grid grid-cols-3 gap-2">
              {side.roster.map(p => (
                <PlayerCard key={p.id} player={p} eliminated={isEliminated(p.id)} size="sm" showLevel={false} />
              ))}
            </div>
          </div>
        ))}
      </div>

      {canEdit && running && (
        <div className="bg-black/70 border-2 border-red-900/50 kop-chamfer p-4 mb-6">
          <div className="font-arcade text-red-400 uppercase text-sm tracking-widest mb-3">Registrar Eliminação</div>
          <div className="grid sm:grid-cols-[1fr,auto] gap-3">
            <div>
              <label className="text-[10px] font-display uppercase tracking-widest text-slate-400">Jogador eliminado</label>
              <select data-testid="eliminated-select" value={selEliminated} onChange={e => { setSelEliminated(e.target.value); sfx.select(); }}
                className="w-full mt-1 bg-slate-900 border border-slate-700 focus:border-red-500 px-2 py-2 text-white outline-none text-sm">
                <option value="">— Selecionar jogador —</option>
                {[["A", teamA, aliveA], ["B", teamB, aliveB]].map(([lbl, t, list]) => (
                  <optgroup key={lbl} label={t?.name}>
                    {list.map(p => <option key={p.id} value={p.id}>{p.name}{p.nickname ? ` "${p.nickname}"` : ""}</option>)}
                  </optgroup>
                ))}
              </select>
            </div>
            <div className="flex items-end gap-2">
              <button data-testid="submit-elim-btn" onClick={submitElim} disabled={actionBusy}
                className="flex-1 kop-chamfer bg-red-600 hover:bg-red-500 disabled:opacity-50 text-white font-arcade uppercase tracking-widest px-4 py-2 kop-glow-red">
                ▶ Eliminado
              </button>
              {elims.length > 0 && (
                <button data-testid="undo-elim-btn" onClick={() => setConfirmAction("undo")} disabled={actionBusy} title="Desfazer última"
                  className="kop-chamfer border-2 border-slate-700 text-slate-400 hover:text-yellow-400 hover:border-yellow-400 disabled:opacity-50 px-3 py-2">
                  <Undo2 className="w-4 h-4" />
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {confirmAction && (
        <div data-testid="match-action-confirm" className="mb-4 bg-black/70 border border-yellow-500/60 kop-chamfer p-3 flex flex-wrap items-center gap-3">
          <span className="text-sm text-yellow-300 font-display uppercase tracking-widest">
            {confirmAction === "end" ? "Encerrar partida agora?" : "Desfazer a última eliminação?"}
          </span>
          <button data-testid="match-action-confirm-btn" onClick={confirmAction === "end" ? endMatch : undo} disabled={actionBusy}
            className="kop-chamfer bg-red-600 hover:bg-red-500 disabled:opacity-50 text-white font-arcade uppercase tracking-widest px-3 py-2">
            {actionBusy ? "Processando..." : "Confirmar"}
          </button>
          <button data-testid="match-action-cancel-btn" onClick={() => setConfirmAction(null)} disabled={actionBusy}
            className="kop-chamfer border-2 border-slate-700 text-slate-400 hover:text-white px-3 py-2">
            Cancelar
          </button>
        </div>
      )}

      {elims.length > 0 && (
        <div className="bg-black/50 border border-slate-800 kop-chamfer p-4 mb-6">
          <div className="font-arcade text-slate-300 uppercase text-xs tracking-widest mb-2">Histórico de Eliminações</div>
          <ol className="space-y-1 text-sm">
            {elims.map((e, i) => {
              const victim = byId[e.eliminated_id];
              const inA = teamA?.players?.includes(e.eliminated_id);
              return (
                <li key={i} className="flex items-center gap-2 text-slate-300">
                  <span className="font-mono-num text-xs text-slate-500 w-14">{fmtTime(e.at_ms || 0)}</span>
                  <span className={`font-display uppercase truncate ${inA ? "text-red-400" : "text-cyan-300"}`}>{victim?.name}</span>
                  <span className="text-red-500 font-arcade text-xs">ELIMINATED</span>
                </li>
              );
            })}
          </ol>
        </div>
      )}

      {finished && showResult && (
        <div className="text-center animate-kop-slam bg-black/60 border-2 border-yellow-500/60 kop-chamfer p-6">
          {match.is_draw ? (
            <>
              <div className="font-arcade text-4xl sm:text-6xl text-cyan-300 uppercase animate-kop-pulse">DRAW</div>
              <div className="mt-2 font-arcade text-2xl text-white">{teamA?.name} <span className="text-slate-500">·</span> {teamB?.name}</div>
              <div className="mt-3 font-mono-num text-xl text-slate-400">0 · 0 pts</div>
            </>
          ) : (
            <>
              <div className="font-arcade text-4xl sm:text-6xl text-yellow-400 uppercase animate-kop-pulse">WINNER</div>
              <div className="font-arcade text-3xl text-white uppercase mt-2">{winnerTeam?.name}</div>
              <div className="mt-3 font-mono-num text-2xl text-cyan-300">{match.points_a} · {match.points_b} pts</div>
            </>
          )}
          {(match.perfect_a || match.perfect_b) && (
            <div className="mt-3 inline-block bg-gradient-to-r from-amber-500 via-orange-500 to-red-500 text-black font-arcade tracking-widest px-4 py-1 kop-glow-gold animate-pulse">
              PERFECT! {winnerTeam?.players?.length || 0}/{winnerTeam?.players?.length || 0} PLAYERS ALIVE
            </div>
          )}
          {isAdmin && !match.locked && match.phase !== "GROUP" && match.is_draw && (
            <div className="mt-4 text-xs text-slate-400 font-display uppercase tracking-widest">
              <div className="mb-2">Playoff empatado — defina o vencedor manualmente:</div>
              <div className="flex gap-2 justify-center">
                <button data-testid="set-winner-a" onClick={async () => { const r = await chooseWinner(match.team_a); if (r) sfx.winner(); }} disabled={actionBusy}
                  className="kop-chamfer border-2 border-red-500 text-red-400 disabled:opacity-50 px-3 py-1">{teamA?.name}</button>
                <button data-testid="set-winner-b" onClick={async () => { const r = await chooseWinner(match.team_b); if (r) sfx.winner(); }} disabled={actionBusy}
                  className="kop-chamfer border-2 border-cyan-500 text-cyan-300 disabled:opacity-50 px-3 py-1">{teamB?.name}</button>
              </div>
            </div>
          )}
        </div>
      )}

      {perfectOverlay && winnerTeam && (
        <div className="fixed inset-0 z-50 bg-black flex items-center justify-center overflow-hidden">
          <div className="absolute inset-0 kop-grid-bg opacity-40" />
          <div className="scanlines absolute inset-0" />
          <div className="absolute inset-0" style={{ background: "radial-gradient(circle at center, rgba(234,179,8,0.6) 0%, transparent 60%)" }} />
          <div className="relative text-center animate-kop-slam">
            <div className="font-arcade text-6xl sm:text-9xl uppercase tracking-widest" style={{
              background: "linear-gradient(90deg,#f59e0b,#ff2e4c,#f59e0b)",
              WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent",
              textShadow: "0 0 60px rgba(234,179,8,0.9)",
            }}>PERFECT!</div>
            <div className="mt-4 font-arcade text-3xl sm:text-5xl text-white uppercase">{winnerTeam.name}</div>
            <div className="mt-2 text-cyan-300 font-display uppercase tracking-widest">{winnerTeam?.players?.length || 0}/{winnerTeam?.players?.length || 0} PLAYERS ALIVE · +2 BONUS</div>
            <div className="mt-6 flex gap-3 justify-center">
              {(winnerTeam.players || []).map(pid => byId[pid] && (
                <PlayerCard key={pid} player={byId[pid]} size="md" />
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
