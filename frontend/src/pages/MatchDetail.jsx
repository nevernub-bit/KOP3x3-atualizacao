import React, { useEffect, useMemo, useRef, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api, formatErr } from "../api";
import { useAuth } from "../auth";
import { PlayerCard } from "../components/PlayerCard";
import { toast } from "sonner";
import { sfx } from "../sound";
import { Play, Pause, Square, Undo2, Clock, Lock, Unlock, AlertTriangle, RotateCcw, Gavel } from "lucide-react";

function fmtTime(ms) {
  if (ms == null) return "00:00";
  const totalS = Math.max(0, Math.round(ms / 1000));
  const m = String(Math.floor(totalS / 60)).padStart(2, "0");
  const s = String(totalS % 60).padStart(2, "0");
  return `${m}:${s}`;
}

export default function MatchDetail() {
  const { mid } = useParams();
  const { isAdmin, isStaff } = useAuth();
  const [match, setMatch] = useState(null);
  const [teams, setTeams] = useState([]);
  const [players, setPlayers] = useState([]);
  const [tick, setTick] = useState(0);
  const [selEliminated, setSelEliminated] = useState("");
  const [perfectOverlay, setPerfectOverlay] = useState(false);
  const [showResult, setShowResult] = useState(false);
  const [confirmAction, setConfirmAction] = useState(null);
  const [actionBusy, setActionBusy] = useState(false);
  const [quickTarget, setQuickTarget] = useState(null);
  const [penaltyTeam, setPenaltyTeam] = useState("");
  const [penaltyReason, setPenaltyReason] = useState("");
  const [showPenalty, setShowPenalty] = useState(false);
  const [confirmWo, setConfirmWo] = useState(null);
  const [showRedo, setShowRedo] = useState(false);
  const [redoReason, setRedoReason] = useState("");
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
  const elimEntry = Object.fromEntries(elims.map(e => [e.eliminated_id, e]));

  const eliminatedOptions = [...aliveA, ...aliveB];
  const finished = match.status === "ENCERRADA";
  const running = match.status === "EM_ANDAMENTO";
  const paused = match.status === "PAUSADA";
  const waiting = match.status === "AGUARDANDO";
  const canEdit = isStaff && !match.locked;
  const canCorrect = canEdit && (running || paused || (finished && isAdmin));
  const winnerTeam = teams.find(t => t.id === match.winner_team_id);

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
      const detail = e.response?.data?.detail;
      toast.error(detail ? formatErr(detail) : errorMessage);
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
    // When the admin corrects a finished match, it stays finished.
    const config = finished ? { params: { keep_finished: true } } : undefined;
    const result = await runMatchMutation(() => api.delete(`/matches/${mid}/eliminate/last`, config));
    if (result) sfx.back();
  };
  const toggleLock = () => runMatchMutation(() => api.post(`/matches/${mid}/lock`), "Erro ao alterar bloqueio");
  const submitElim = async () => {
    if (!selEliminated) return toast.error("Selecione o jogador eliminado");
    const token = crypto.randomUUID();
    const result = await runMatchMutation(() => api.post(`/matches/${mid}/eliminate`, {
      eliminated_id: selEliminated, client_token: token,
    }));
    if (result) setSelEliminated("");
  };
  const quickEliminate = async () => {
    if (!quickTarget) return;
    const target = quickTarget;
    const token = crypto.randomUUID();
    const result = await runMatchMutation(() => api.post(`/matches/${mid}/eliminate`, {
      eliminated_id: target.id, client_token: token,
    }));
    if (result) { setQuickTarget(null); sfx.elim(); toast.success(`${target.name} eliminado`); }
  };
  const quickUndeclared = async () => {
    if (!quickTarget) return;
    const target = quickTarget;
    const token = crypto.randomUUID();
    const result = await runMatchMutation(() => api.post(`/matches/${mid}/undeclared`, {
      player_id: target.id, reason: "Eliminação não declarada", client_token: token,
    }), "Erro ao registrar eliminação não declarada");
    if (result) {
      setQuickTarget(null); sfx.elim();
      toast.success(`${target.name}: eliminação + −1 ponto`);
    }
  };
  const undoEntry = async (entry) => {
    const key = entry.id || entry.eliminated_id;
    const config = finished ? { params: { keep_finished: true } } : undefined;
    const result = await runMatchMutation(() => api.delete(`/matches/${mid}/eliminations/${key}`, config), "Erro ao desfazer eliminação");
    if (result) sfx.back();
  };
  const submitPenalty = async () => {
    if (!penaltyTeam) return toast.error("Selecione a equipe penalizada");
    if (penaltyReason.trim().length < 3) return toast.error("Informe o motivo da penalidade");
    const result = await runMatchMutation(() => api.post(`/matches/${mid}/penalty`, {
      team_id: penaltyTeam, points: 1, reason: penaltyReason.trim(),
    }), "Erro ao aplicar penalidade");
    if (result) { setShowPenalty(false); setPenaltyReason(""); setPenaltyTeam(""); toast.success("Penalidade registrada"); }
  };
  const removePenalty = (pid) => runMatchMutation(() => api.delete(`/matches/${mid}/penalty/${pid}`), "Erro ao remover penalidade");
  const declareDraw = () => runMatchMutation(() => api.post(`/matches/${mid}/declare-draw`, {
    simultaneous: true, reason: "Eliminação simultânea",
  }), "Erro ao declarar empate");
  const submitWo = async (teamId) => {
    setConfirmWo(null);
    const result = await runMatchMutation(() => api.post(`/matches/${mid}/wo`, {
      team_id: teamId, reason: "W.O. — equipe adversária ausente",
    }), "Erro ao registrar W.O.");
    if (result) sfx.winner();
  };
  const redoMatch = async () => {
    const result = await runMatchMutation(() => api.post(`/matches/${mid}/redo`, {
      confirm: true, reason: redoReason.trim(),
    }), "Erro ao refazer partida");
    if (result) { setShowRedo(false); setRedoReason(""); toast.success("Partida liberada para nova disputa"); }
  };
  const chooseWinner = (teamId) => runMatchMutation(() => api.post(`/matches/${mid}/set-winner`, { winner_team_id: teamId }));

  return (
    <div className="max-w-6xl mx-auto px-4 py-6">
      <div className="text-center mb-3">
        <div className="font-arcade text-red-400 text-sm tracking-widest uppercase">MATCH {String(match.number).padStart(2, "0")}</div>
        <div className="font-display text-xs text-cyan-300 tracking-widest uppercase">{match.phase}{match.group ? ` — GRUPO ${match.group}` : ""}</div>
        {match.wo && <div className="mt-1 inline-block bg-amber-500 text-black font-arcade text-xs px-2 py-0.5 tracking-widest">W.O.</div>}
        {match.redo_count > 0 && <span className="ml-2 text-[10px] font-display uppercase tracking-widest text-amber-400">refeita {match.redo_count}x</span>}
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
              {finished && (match.wo ? "W.O." : match.is_draw ? "EMPATE" : "ENCERRADA")}
            </div>
          </div>

          {canEdit && (
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
              <div className="mt-1 font-mono-num text-xs text-cyan-300">
                Pts {match.points_a} · {match.points_b}
                {match.wo && <span className="text-amber-400"> · W.O.</span>}
              </div>
            )}
            {((match.penalty_points_a || 0) > 0 || (match.penalty_points_b || 0) > 0) && (
              <div className="mt-1 text-[10px] font-display uppercase tracking-widest text-red-400">
                Penalidades: −{match.penalty_points_a || 0} / −{match.penalty_points_b || 0}
              </div>
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

      {canCorrect && (
        <div data-testid="quick-elimination" className="bg-black/70 border-2 border-red-900/50 kop-chamfer p-4 mb-6">
          <div className="font-arcade text-red-400 uppercase text-sm tracking-widest mb-1">Eliminação rápida</div>
          <div className="text-[10px] text-slate-500 font-display uppercase tracking-widest mb-3">Toque na foto do jogador → ELIMINAR</div>
          <div className="grid grid-cols-3 gap-2">
            {[...rosterA, ...rosterB].map(p => {
              const gone = isEliminated(p.id);
              return (
                <button
                  key={p.id}
                  data-testid={`quick-elim-${p.id}`}
                  onClick={() => { if (!gone) { setQuickTarget(p); sfx.select(); } }}
                  disabled={gone || actionBusy}
                  className={`relative text-left disabled:cursor-not-allowed ${gone ? "opacity-30" : ""}`}
                >
                  <PlayerCard player={p} eliminated={gone} size="sm" showLevel={false} />
                  {!gone && (
                    <span className="absolute bottom-1 right-1 bg-red-600 text-white font-arcade text-[9px] px-1.5 py-0.5 uppercase tracking-widest">
                      Eliminar
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {quickTarget && (
        <div data-testid="quick-elim-confirm" className="mb-4 bg-black/80 border-2 border-red-500/60 kop-chamfer p-4 flex flex-wrap items-center gap-3">
          <PlayerCard player={quickTarget} size="sm" showLevel={false} />
          <div className="flex-1 min-w-[160px]">
            <div className="font-arcade text-lg text-white uppercase">{quickTarget.name}</div>
            <div className="text-xs text-slate-400 font-display uppercase tracking-widest">Confirmar eliminação?</div>
          </div>
          <button onClick={quickEliminate} disabled={actionBusy} className="kop-chamfer bg-red-600 hover:bg-red-500 disabled:opacity-50 text-white font-arcade uppercase tracking-widest px-4 py-2">
            {actionBusy ? "Registrando..." : "▶ Eliminar"}
          </button>
          <button onClick={quickUndeclared} disabled={actionBusy} className="kop-chamfer border-2 border-amber-500 text-amber-300 hover:bg-amber-500 hover:text-black disabled:opacity-50 font-arcade uppercase tracking-widest px-3 py-2">
            Não declarada ( −1 )
          </button>
          <button onClick={() => setQuickTarget(null)} disabled={actionBusy} className="kop-chamfer border-2 border-slate-700 text-slate-400 hover:text-white px-3 py-2">
            Cancelar
          </button>
        </div>
      )}

      {canEdit && running && (
        <div className="bg-black/70 border-2 border-red-900/50 kop-chamfer p-4 mb-6">
          <div className="font-arcade text-red-400 uppercase text-sm tracking-widest mb-3">Registro alternativo</div>
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
                <li key={e.id || i} className="flex items-center gap-2 text-slate-300">
                  <span className="font-mono-num text-xs text-slate-500 w-14">{fmtTime(e.at_ms || 0)}</span>
                  <span className={`font-display uppercase truncate ${inA ? "text-red-400" : "text-cyan-300"}`}>{victim?.name || e.eliminated_id}</span>
                  <span className="text-red-500 font-arcade text-xs">ELIMINATED</span>
                  {canCorrect && (
                    <button data-testid={`undo-elim-${e.id || e.eliminated_id}`} onClick={() => undoEntry(e)} disabled={actionBusy}
                      title="Desfazer esta eliminação" className="ml-auto text-slate-500 hover:text-yellow-400 disabled:opacity-50">
                      <Undo2 className="w-3.5 h-3.5" />
                    </button>
                  )}
                </li>
              );
            })}
          </ol>
        </div>
      )}

      {(showPenalty || (match.penalties || []).length > 0) && (
        <div data-testid="penalty-panel" className="bg-black/60 border-2 border-red-900/60 kop-chamfer p-4 mb-6">
          <div className="flex items-center gap-2 mb-3">
            <Gavel className="w-4 h-4 text-red-400" />
            <div className="font-arcade text-red-400 uppercase text-sm tracking-widest">Penalidades</div>
            {isStaff && !showPenalty && (
              <button onClick={() => setShowPenalty(true)} className="ml-auto text-xs font-display uppercase tracking-widest text-red-300 hover:text-red-200">+ Aplicar</button>
            )}
          </div>
          {(match.penalties || []).length > 0 && (
            <ul className="space-y-1 text-xs mb-3">
              {match.penalties.map(p => (
                <li key={p.id} className="flex flex-wrap items-center gap-2 text-slate-300">
                  <span className="font-mono-num text-red-400">−{p.points}</span>
                  <span className="font-display uppercase">{teams.find(t => t.id === p.team_id)?.name}</span>
                  <span className="text-slate-400">{p.reason}</span>
                  <span className="text-slate-600">· {p.match_status} · {p.by}</span>
                  {isAdmin && (
                    <button onClick={() => removePenalty(p.id)} disabled={actionBusy} className="ml-auto text-slate-500 hover:text-red-400 disabled:opacity-50" title="Remover penalidade">×</button>
                  )}
                </li>
              ))}
            </ul>
          )}
          {showPenalty && isStaff && (
            <div className="grid sm:grid-cols-[auto,1fr,auto] gap-2 items-end">
              <select value={penaltyTeam} onChange={e => setPenaltyTeam(e.target.value)}
                className="bg-slate-900 border border-slate-700 px-2 py-2 text-white text-sm outline-none">
                <option value="">Equipe</option>
                <option value={match.team_a}>{teamA?.name}</option>
                <option value={match.team_b}>{teamB?.name}</option>
              </select>
              <input value={penaltyReason} onChange={e => setPenaltyReason(e.target.value)}
                placeholder="Motivo da penalidade (obrigatório)"
                className="bg-slate-900 border border-slate-700 focus:border-red-500 px-3 py-2 text-white text-sm outline-none" />
              <div className="flex gap-2">
                <button onClick={submitPenalty} disabled={actionBusy} className="kop-chamfer bg-red-600 hover:bg-red-500 disabled:opacity-50 text-white font-arcade uppercase tracking-widest px-3 py-2">−1 pt</button>
                <button onClick={() => setShowPenalty(false)} disabled={actionBusy} className="kop-chamfer border-2 border-slate-700 text-slate-400 px-3 py-2">×</button>
              </div>
            </div>
          )}
        </div>
      )}

      {isStaff && !showPenalty && (match.penalties || []).length === 0 && (
        <div className="mb-6">
          <button data-testid="open-penalty" onClick={() => setShowPenalty(true)} className="kop-chamfer border border-red-900/60 text-red-400 hover:text-red-300 text-xs font-display uppercase tracking-widest px-3 py-2">
            <Gavel className="w-3 h-3 inline mr-1" /> Aplicar penalidade à equipe
          </button>
        </div>
      )}

      {isAdmin && !match.wo && !match.locked && elims.length === 0 && (
        <div className="mb-6 bg-black/50 border border-amber-600/40 kop-chamfer p-3">
          <div className="text-[10px] font-display uppercase tracking-widest text-amber-300 mb-2">W.O. — registrar ausência (5 × 0 administrativo)</div>
          <div className="flex flex-wrap gap-2">
            <button onClick={() => setConfirmWo(match.team_a)} disabled={actionBusy} className="kop-chamfer border border-amber-500 text-amber-300 text-xs px-3 py-1.5 uppercase font-display tracking-widest disabled:opacity-50">
              W.O. a favor de {teamA?.name}
            </button>
            <button onClick={() => setConfirmWo(match.team_b)} disabled={actionBusy} className="kop-chamfer border border-amber-500 text-amber-300 text-xs px-3 py-1.5 uppercase font-display tracking-widest disabled:opacity-50">
              W.O. a favor de {teamB?.name}
            </button>
          </div>
        </div>
      )}

      {confirmWo && (
        <div className="mb-4 bg-black/80 border border-amber-500 kop-chamfer p-3 flex flex-wrap items-center gap-3">
          <AlertTriangle className="w-4 h-4 text-amber-400" />
          <span className="text-sm text-amber-300 font-display uppercase tracking-widest">
            Confirmar W.O. a favor de {teams.find(t => t.id === confirmWo)?.name}?
          </span>
          <button onClick={() => submitWo(confirmWo)} disabled={actionBusy} className="kop-chamfer bg-amber-500 hover:bg-amber-400 text-black font-arcade uppercase tracking-widest px-3 py-2">Confirmar</button>
          <button onClick={() => setConfirmWo(null)} disabled={actionBusy} className="kop-chamfer border-2 border-slate-700 text-slate-400 px-3 py-2">Cancelar</button>
        </div>
      )}

      {isStaff && (running || paused) && (
        <div className="mb-6 flex flex-wrap gap-2">
          <button onClick={declareDraw} disabled={actionBusy} className="kop-chamfer border border-cyan-500 text-cyan-300 text-xs font-display uppercase tracking-widest px-3 py-2 disabled:opacity-50">
            Declarar empate (eliminação simultânea)
          </button>
        </div>
      )}

      {isAdmin && finished && (
        <div className="mb-6">
          {showRedo ? (
            <div className="bg-black/80 border-2 border-amber-500/70 kop-chamfer p-3 flex flex-wrap items-center gap-2">
              <span className="text-sm text-amber-300 font-display uppercase tracking-widest">
                Refazer esta partida? O resultado atual será arquivado no histórico.
              </span>
              <input value={redoReason} onChange={e => setRedoReason(e.target.value)} placeholder="Motivo (opcional)"
                className="bg-slate-900 border border-slate-700 px-3 py-1.5 text-white text-sm outline-none" />
              <button onClick={redoMatch} disabled={actionBusy} className="kop-chamfer bg-amber-500 hover:bg-amber-400 text-black font-arcade uppercase tracking-widest px-3 py-2 disabled:opacity-50">
                <RotateCcw className="w-3 h-3 inline mr-1" /> Confirmar
              </button>
              <button onClick={() => setShowRedo(false)} disabled={actionBusy} className="kop-chamfer border-2 border-slate-700 text-slate-400 px-3 py-2">Cancelar</button>
            </div>
          ) : (
            <button onClick={() => setShowRedo(true)} disabled={actionBusy} className="kop-chamfer border border-amber-700 text-amber-500 hover:text-amber-300 text-xs font-display uppercase tracking-widest px-3 py-2 disabled:opacity-50">
              <RotateCcw className="w-3 h-3 inline mr-1" /> Refazer partida
            </button>
          )}
        </div>
      )}

      {finished && showResult && (
        <div className="text-center animate-kop-slam bg-black/60 border-2 border-yellow-500/60 kop-chamfer p-6">
          {match.is_draw ? (
            <>
              <div className="font-arcade text-4xl sm:text-6xl text-cyan-300 uppercase animate-kop-pulse">DRAW</div>
              <div className="mt-2 font-arcade text-2xl text-white">{teamA?.name} <span className="text-slate-500">·</span> {teamB?.name}</div>
              <div className="mt-3 font-mono-num text-xl text-slate-400">{match.points_a} · {match.points_b} pts</div>
              {match.draw_reason && <div className="mt-1 text-[10px] uppercase font-display tracking-widest text-slate-500">Empate: {match.draw_reason}</div>}
            </>
          ) : (
            <>
              <div className="font-arcade text-4xl sm:text-6xl text-yellow-400 uppercase animate-kop-pulse">WINNER</div>
              <div className="font-arcade text-3xl text-white uppercase mt-2">{winnerTeam?.name}</div>
              <div className="mt-3 font-mono-num text-2xl text-cyan-300">
                {match.wo ? "5 × 0 — W.O." : `${match.points_a} · ${match.points_b} pts`}
              </div>
            </>
          )}
          {(match.perfect_a || match.perfect_b) && (
            <div className="mt-3 inline-block bg-gradient-to-r from-amber-500 via-orange-500 to-red-500 text-black font-arcade tracking-widest px-4 py-1 kop-glow-gold animate-pulse">
              PERFECT! {winnerTeam?.players?.length || 0}/{winnerTeam?.players?.length || 0} PLAYERS ALIVE
            </div>
          )}
          {(match.admin_perfect_a || match.admin_perfect_b) && (
            <div className="mt-3 text-[10px] uppercase font-display tracking-widest text-amber-400">
              PERFECT administrativo (W.O.) — não conta para desempate
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
            <div className="mt-2 text-cyan-300 font-display uppercase tracking-widest">{winnerTeam?.players?.length || 0}/{winnerTeam?.players?.length || 0} PLAYERS ALIVE</div>
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
