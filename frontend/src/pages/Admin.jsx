import React, { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, formatErr } from "../api";
import { useAuth } from "../auth";
import { toast } from "sonner";
import { sfx } from "../sound";
import { Shuffle, Trash2, RefreshCw, Lock, Unlock, Tv, Trophy, Swords, SkipForward, Pencil, Save, Users, Image as ImageIcon, FileText, Plus, UserCheck, UserX, RotateCcw, History, AlertTriangle } from "lucide-react";
import { PlayerEditModal } from "../components/PlayerEditModal";

export default function Admin() {
  const { isAdmin, loading } = useAuth();
  const nav = useNavigate();
  const [tour, setTour] = useState(null);
  const [teams, setTeams] = useState([]);
  const [players, setPlayers] = useState([]);
  const [matches, setMatches] = useState([]);
  const [live, setLive] = useState({ mode: "MATCH", match_id: null });
  const loadVersion = useRef(0);
  const [mode, setMode] = useState("BALANCED");
  const [editing, setEditing] = useState(null);
  const [playerSearch, setPlayerSearch] = useState("");
  const [cfg, setCfg] = useState({ num_teams: 10, players_per_team: 3, num_groups: 2, qualifiers_per_group: 2 });
  const [confirmDraw, setConfirmDraw] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(null);
  const [confirmReset, setConfirmReset] = useState(false);
  const [pendingAction, setPendingAction] = useState(null);
  const [banner, setBanner] = useState(null);
  const [bannerDraft, setBannerDraft] = useState(null);
  const [bannerDraftName, setBannerDraftName] = useState("");
  const bannerInputRef = useRef(null);
  const [rules, setRules] = useState(null);
  const [rulesDraft, setRulesDraft] = useState("");
  const [rangers, setRangers] = useState([]);
  const [newRanger, setNewRanger] = useState({ name: "", email: "", password: "" });
  const [redoMatch, setRedoMatch] = useState(null);
  const [redoReason, setRedoReason] = useState("");
  const [historyMatch, setHistoryMatch] = useState(null);
  const [historyDocs, setHistoryDocs] = useState([]);
  const [historyBusy, setHistoryBusy] = useState(false);
  const [confirmRestore, setConfirmRestore] = useState(null);
  const [bracketStatus, setBracketStatus] = useState(null);
  const [recalc, setRecalc] = useState(null);
  const [confirmRecalc, setConfirmRecalc] = useState(false);
  const actionInFlight = useRef(false);
  const actionBusy = pendingAction !== null;

  useEffect(() => {
    if (!loading && !isAdmin) nav("/login");
  }, [isAdmin, loading, nav]);

  const load = async () => {
    const version = ++loadVersion.current;
    const [t, tm, p, m, l, b, ru, rg, bs] = await Promise.all([
      api.get("/tournament"), api.get("/teams"),
      api.get("/players"), api.get("/matches"),
      api.get("/live/state"), api.get("/banner"),
      api.get("/rules"), api.get("/rangers"), api.get("/bracket/status"),
    ]);
    if (version !== loadVersion.current) return;
    setTour(t.data); setTeams(tm.data); setPlayers(p.data); setMatches(m.data); setLive(l.data);
    setBanner(b.data?.image || null);
    setRules(ru.data || null); setRulesDraft(ru.data?.content || "");
    setRangers(rg.data || []);
    setBracketStatus(bs.data || null);
    setCfg({
      num_teams: t.data?.num_teams ?? 10,
      players_per_team: t.data?.players_per_team ?? 3,
      num_groups: t.data?.num_groups ?? 2,
      qualifiers_per_group: t.data?.qualifiers_per_group ?? 2,
    });
  };
  useEffect(() => {
    if (isAdmin) load().catch(() => toast.error("Não foi possível carregar os dados do torneio"));
  }, [isAdmin]);
  // Poll live state so admin sees external changes and next-match auto-selection
  useEffect(() => {
    if (!isAdmin) return;
    const iv = setInterval(async () => {
      if (actionInFlight.current) return;
      const version = loadVersion.current;
      try {
        const r = await api.get("/live/state");
        if (!actionInFlight.current && version === loadVersion.current) setLive(r.data);
      } catch { /* polling falho não deve interromper o painel */ }
    }, 3000);
    return () => clearInterval(iv);
  }, [isAdmin]);

  // Um único executor para mutações administrativas: impede chamadas duplicadas,
  // apresenta erros e só refaz a leitura depois que a mutação terminou.
  const runAdminAction = async (key, action, { refresh = true, onSuccess, errorMessage = "Falha na ação administrativa" } = {}) => {
    if (actionInFlight.current) return null;
    actionInFlight.current = true;
    loadVersion.current += 1;
    setPendingAction(key);
    try {
      const result = await action();
      onSuccess?.(result);
      if (refresh) {
        load().catch(() => toast.error("A ação foi concluída, mas não foi possível atualizar os dados"));
      }
      return result;
    } catch (e) {
      sfx.error();
      toast.error(formatErr(e.response?.data?.detail) || errorMessage);
      return null;
    } finally {
      actionInFlight.current = false;
      setPendingAction(null);
    }
  };

  const runDraw = () => {
    setConfirmDraw(false);
    return runAdminAction("draw", () => api.post("/draw", {
      num_teams: tour?.num_teams || 10,
      players_per_team: tour?.players_per_team || 3,
      num_groups: tour?.num_groups,
      qualifiers_per_group: tour?.qualifiers_per_group,
      mode,
    }), {
      onSuccess: () => toast.success("Sorteio concluído!"),
      errorMessage: "Falha ao executar o sorteio",
    });
  };
  const saveConfig = () => runAdminAction("save-config", async () => {
    const r = await api.patch("/tournament", {
      num_teams: Number(cfg.num_teams),
      players_per_team: Number(cfg.players_per_team),
      num_groups: Number(cfg.num_groups),
      qualifiers_per_group: Number(cfg.qualifiers_per_group),
    });
    setTour(r.data);
    setCfg({
      num_teams: r.data.num_teams,
      players_per_team: r.data.players_per_team,
      num_groups: r.data.num_groups,
      qualifiers_per_group: r.data.qualifiers_per_group,
    });
    sfx.save();
    toast.success("Configuração do evento salva");
  }, { refresh: false, errorMessage: "Falha ao salvar configuração" });

  const reset = () => {
    setConfirmReset(false);
    return runAdminAction("reset", async () => {
      const r = await api.post("/tournament/reset");
      const snap = r.data?.tournament;
      if (snap) {
        setTour(snap);
        setCfg({
          num_teams: snap.num_teams ?? 10,
          players_per_team: snap.players_per_team ?? 3,
          num_groups: snap.num_groups ?? 2,
          qualifiers_per_group: snap.qualifiers_per_group ?? 2,
        });
      }
      // Estrutura limpa na hora: equipes, partidas, grupos e mata-mata somem.
      setTeams([]); setMatches([]);
      setLive({ mode: "MATCH", match_id: null });
      sfx.confirm();
      toast.success("Torneio reiniciado — jogadores preservados");
    }, { errorMessage: "Falha ao reiniciar o torneio" });
  };
  const removePlayer = (id) => {
    setConfirmDelete(null);
    return runAdminAction(`delete-player-${id}`, () => api.delete(`/players/${id}`), {
      errorMessage: "Falha ao excluir jogador",
    });
  };
  const toggleLock = (id) => runAdminAction(`lock-match-${id}`, () => api.post(`/matches/${id}/lock`));
  const renameTeam = (id, name) => runAdminAction(`rename-team-${id}`, () => api.patch(`/teams/${id}`, { name }), {
    errorMessage: "Falha ao renomear equipe",
  });

  const selectBanner = (file) => {
    if (!file) return;
    if (!/^image\/(png|jpe?g|webp)$/.test(file.type)) {
      toast.error("Use uma imagem PNG, JPEG ou WEBP");
      return;
    }
    if (file.size > 900 * 1024) {
      toast.error("Imagem muito grande (máx. 900 KB)");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      setBannerDraft(reader.result);
      setBannerDraftName(file.name);
    };
    reader.onerror = () => toast.error("Não foi possível ler a imagem selecionada");
    reader.readAsDataURL(file);
  };

  const uploadBanner = () => {
    if (!bannerDraft) return;
    const image = bannerDraft;
    const filename = bannerDraftName;
    return runAdminAction("banner", async () => {
      const r = await api.post("/banner", { image, filename });
      setBanner(image);
      setBannerDraft(null);
      setBannerDraftName("");
      toast.success("Banner do evento atualizado");
      return r;
    }, { refresh: false, errorMessage: "Falha ao enviar o banner" });
  };
  const removeBanner = () => runAdminAction("banner-del", async () => {
    await api.delete("/banner");
    setBanner(null);
    toast.success("Banner removido");
  }, { refresh: false, errorMessage: "Falha ao remover o banner" });

  const saveRules = () => runAdminAction("rules", async () => {
    const r = await api.put("/rules", { content: rulesDraft });
    setRules(r.data);
    toast.success(`Regras publicadas (versão ${r.data.version})`);
    return r;
  }, { refresh: false, errorMessage: "Falha ao salvar as regras" });

  const createRanger = () => runAdminAction("ranger-create", async () => {
    const r = await api.post("/rangers", newRanger);
    setRangers(rs => [...rs, r.data]);
    setNewRanger({ name: "", email: "", password: "" });
    toast.success("Ranger criado");
    return r;
  }, { refresh: false, errorMessage: "Falha ao criar Ranger" });

  const toggleRanger = (r) => runAdminAction(`ranger-toggle-${r.id}`, async () => {
    if (r.active) await api.delete(`/rangers/${r.id}`);
    else await api.patch(`/rangers/${r.id}`, { active: true });
    setRangers(rs => rs.map(x => x.id === r.id ? { ...x, active: !r.active } : x));
    toast.success(r.active ? "Ranger desativado" : "Ranger ativado");
    return r;
  }, { refresh: false, errorMessage: "Falha ao atualizar Ranger" });

  const runRedo = () => {
    const target = redoMatch;
    setRedoMatch(null);
    return runAdminAction("redo", async () => {
      await api.post(`/matches/${target.id}/redo`, { confirm: true, reason: redoReason });
      setRedoReason("");
      toast.success("Partida invalidada e liberada para nova disputa");
    }, { errorMessage: "Falha ao refazer a partida" });
  };

  const openHistory = async (m) => {
    setHistoryMatch(m); setHistoryDocs([]); setConfirmRestore(null); setHistoryBusy(true);
    try {
      const r = await api.get(`/matches/${m.id}/history`);
      setHistoryDocs(r.data || []);
    } catch {
      toast.error("Não foi possível carregar o histórico da partida");
      setHistoryMatch(null);
    } finally {
      setHistoryBusy(false);
    }
  };

  const runRestore = (h) => {
    const target = historyMatch;
    setConfirmRestore(null);
    return runAdminAction(`restore-${h.id}`, async () => {
      await api.post(`/matches/${target.id}/history/${h.id}/restore`, { confirm: true });
      const r = await api.get(`/matches/${target.id}/history`);
      setHistoryDocs(r.data || []);
      toast.success("Resultado anterior restaurado e arquivado");
      await load();
      return r;
    }, { refresh: false, errorMessage: "Falha ao restaurar o snapshot" });
  };

  const previewRecalc = () => runAdminAction("recalc-preview", async () => {
    const r = await api.post("/admin/recalculate-scores", { dry_run: true, confirm: true });
    setRecalc(r.data);
    toast.success(`${r.data.count} partida(s) com diferença`);
    return r;
  }, { refresh: false, errorMessage: "Falha ao pré-visualizar o recálculo" });

  const applyRecalc = () => {
    setConfirmRecalc(false);
    return runAdminAction("recalc-apply", async () => {
      const r = await api.post("/admin/recalculate-scores", { dry_run: false, confirm: true });
      setRecalc(r.data);
      toast.success(`${r.data.applied} partida(s) recalculada(s) — anteriores arquivadas`);
      return r;
    }, { errorMessage: "Falha ao recalcular os resultados" });
  };

  const setLiveMode = (nextMode) => runAdminAction("live-mode", () => api.post("/live/state", { mode: nextMode }), {
    refresh: false,
    onSuccess: r => {
      setLive(r.data); sfx.select();
      toast.success(nextMode === "MATCH" ? "Telão: Partida" : "Telão: Classificação");
    },
  });
  const pinMatch = (mid) => runAdminAction(`pin-match-${mid}`, () => api.post("/live/state", { mode: "MATCH", match_id: mid }), {
    refresh: false,
    onSuccess: r => { setLive(r.data); sfx.confirm(); toast.success("Partida carregada no telão"); },
  });
  const loadNext = () => runAdminAction("load-next", () => api.post("/live/load-next"), {
    refresh: false,
    onSuccess: r => {
      setLive({ mode: r.data.mode, match_id: r.data.match_id });
      sfx.reveal();
      if (r.data.match_id) toast.success("Próxima partida carregada no telão");
      else toast.warning("Sem partidas AGUARDANDO");
    },
  });

  if (!isAdmin) return null;

  const pinnedMatch = matches.find(m => m.id === live.match_id);
  const pinnedTeams = pinnedMatch ? [teams.find(t => t.id === pinnedMatch.team_a)?.name, teams.find(t => t.id === pinnedMatch.team_b)?.name] : null;

  return (
    <div className="max-w-6xl mx-auto px-4 py-8 space-y-8">
      <div>
        <div className="font-display text-cyan-300 text-xs tracking-[0.4em] uppercase">Control Center</div>
        <h1 data-testid="admin-title" className="font-arcade text-3xl text-red-500 uppercase">Painel do Organizador</h1>
      </div>

      {/* LIVE CONTROLLER */}
      <section className="bg-black/60 border-2 border-cyan-500/40 kop-chamfer p-5">
        <div className="flex items-center gap-2 mb-3">
          <Tv className="w-5 h-5 text-cyan-300" />
          <h2 className="font-display text-xl text-white uppercase tracking-widest">Telão — KOP Live</h2>
        </div>
        <div className="grid sm:grid-cols-2 gap-3 mb-4">
          <button data-testid="live-mode-match" onClick={() => setLiveMode("MATCH")} disabled={actionBusy}
            className={`kop-chamfer border-2 p-3 flex items-center gap-2 justify-center font-arcade uppercase tracking-widest disabled:opacity-50 ${live.mode === "MATCH" ? "border-red-500 bg-red-500/10 text-red-400 kop-glow-red" : "border-slate-700 text-slate-400 hover:border-red-500"}`}>
            <Swords className="w-4 h-4" /> Tela de Partida
          </button>
          <button data-testid="live-mode-standings" onClick={() => setLiveMode("STANDINGS")} disabled={actionBusy}
            className={`kop-chamfer border-2 p-3 flex items-center gap-2 justify-center font-arcade uppercase tracking-widest disabled:opacity-50 ${live.mode === "STANDINGS" ? "border-cyan-400 bg-cyan-500/10 text-cyan-300 kop-glow-blue" : "border-slate-700 text-slate-400 hover:border-cyan-400"}`}>
            <Trophy className="w-4 h-4" /> Classificação
          </button>
        </div>

        <div className="border-t border-slate-800 pt-3 flex flex-wrap items-center gap-3">
          <div className="text-xs font-display uppercase tracking-widest text-slate-400">
            <span className="text-slate-500">Fixada:</span>{" "}
            {pinnedMatch ? (
              <span className="text-white">
                MATCH {String(pinnedMatch.number).padStart(2,"0")} · {pinnedTeams?.[0]} vs {pinnedTeams?.[1]} ·{" "}
                <span className={pinnedMatch.status === "ENCERRADA" ? "text-slate-500" : "text-green-400"}>{pinnedMatch.status}</span>
              </span>
            ) : <span className="text-slate-600">nenhuma (auto)</span>}
          </div>
          <button data-testid="live-load-next" onClick={loadNext} disabled={actionBusy}
            className="ml-auto kop-chamfer bg-red-600 hover:bg-red-500 disabled:opacity-50 text-white font-arcade uppercase tracking-widest px-4 py-2 flex items-center gap-2 kop-glow-red">
            <SkipForward className="w-4 h-4" /> Carregar Próxima Partida
          </button>
          <Link to="/live" target="_blank" data-testid="open-live-tab"
            className="kop-chamfer border-2 border-cyan-500 text-cyan-300 hover:bg-cyan-500 hover:text-black font-arcade uppercase tracking-widest px-4 py-2 transition">
            Abrir Telão
          </Link>
        </div>
        <div className="mt-3 text-[10px] text-slate-500 font-display uppercase tracking-widest">
          Ao clicar em START numa partida, o telão fixa automaticamente essa partida em modo Match.
        </div>
      </section>

      <section className="bg-black/60 border border-red-900/50 kop-chamfer p-5">
        <h2 className="font-display text-xl text-white uppercase tracking-widest mb-3">Torneio</h2>
        <div className="grid sm:grid-cols-4 gap-3 text-sm">
          <div><div className="text-slate-500 text-xs uppercase">Status</div><div className="font-arcade text-red-400">{tour?.status}</div></div>
          <div><div className="text-slate-500 text-xs uppercase">Equipes</div><div className="font-arcade text-white">{tour?.num_teams}</div></div>
          <div><div className="text-slate-500 text-xs uppercase">Por Equipe</div><div className="font-arcade text-white">{tour?.players_per_team}</div></div>
          <div><div className="text-slate-500 text-xs uppercase">Inscritos</div><div className="font-arcade text-cyan-300">{players.length}</div></div>
        </div>
        <div className="mt-4 flex flex-wrap gap-3 items-center">
          <div className="flex gap-2">
            {["NORMAL", "BALANCED"].map(m => (
              <button key={m} data-testid={`draw-mode-${m}`} onClick={() => setMode(m)} disabled={actionBusy}
                className={`px-3 py-1 text-xs font-display uppercase tracking-widest border-2 kop-chamfer ${mode === m ? "border-red-500 text-red-400 bg-red-500/10" : "border-slate-700 text-slate-400"}`}>
                {m === "BALANCED" ? "Balanceado" : "Normal"}
              </button>
            ))}
          </div>
          {confirmDraw ? (
            <div data-testid="draw-confirm" className="flex flex-wrap items-center gap-2">
              <span className="text-[10px] text-yellow-400 font-display uppercase tracking-widest">
                Executar sorteio e substituir equipes e tabela atuais?
              </span>
              <button data-testid="draw-confirm-btn" onClick={runDraw} disabled={actionBusy}
                className="kop-chamfer bg-red-600 hover:bg-red-500 disabled:opacity-50 text-white font-arcade uppercase tracking-widest px-3 py-2">
                {pendingAction === "draw" ? "Sorteando..." : "Confirmar sorteio"}
              </button>
              <button data-testid="draw-cancel-btn" onClick={() => setConfirmDraw(false)} disabled={actionBusy}
                className="kop-chamfer border-2 border-slate-700 text-slate-400 hover:text-white font-arcade uppercase tracking-widest px-3 py-2">
                Cancelar
              </button>
            </div>
          ) : (
            <button data-testid="run-draw-btn" onClick={() => setConfirmDraw(true)} disabled={actionBusy}
              className="kop-chamfer bg-red-600 hover:bg-red-500 disabled:opacity-50 text-white font-arcade uppercase tracking-widest px-4 py-2 flex items-center gap-2">
              <Shuffle className="w-4 h-4" /> Sortear Equipes
            </button>
          )}
          <Link to="/team-select" className="kop-chamfer border-2 border-cyan-500 text-cyan-300 hover:bg-cyan-500 hover:text-black font-arcade uppercase tracking-widest px-4 py-2 transition">
            Ver Team Select
          </Link>
          {confirmReset ? (
            <div data-testid="reset-confirm" className="flex flex-wrap items-center gap-2">
              <span className="text-[10px] text-yellow-400 font-display uppercase tracking-widest">
                Apagar equipes, partidas e sorteio? Os jogadores inscritos são mantidos.
              </span>
              <button data-testid="reset-confirm-btn" onClick={reset} disabled={actionBusy}
                className="kop-chamfer bg-red-600 hover:bg-red-500 disabled:opacity-50 text-white font-arcade uppercase tracking-widest px-4 py-2 flex items-center gap-2">
                <RefreshCw className="w-4 h-4" /> {pendingAction === "reset" ? "Resetando..." : "Confirmar reset"}
              </button>
              <button data-testid="reset-cancel-btn" onClick={() => setConfirmReset(false)} disabled={actionBusy}
                className="kop-chamfer border-2 border-slate-700 text-slate-400 hover:text-white font-arcade uppercase tracking-widest px-3 py-2">
                Cancelar
              </button>
            </div>
          ) : (
            <button data-testid="reset-btn" onClick={() => setConfirmReset(true)} disabled={actionBusy}
              className="kop-chamfer border-2 border-slate-700 text-slate-400 hover:text-red-500 hover:border-red-500 font-arcade uppercase tracking-widest px-4 py-2 flex items-center gap-2">
              <RefreshCw className="w-4 h-4" /> Reset
            </button>
          )}
        </div>
      </section>

      <section data-testid="event-config" className="bg-black/60 border-2 border-cyan-500/30 kop-chamfer p-5">
        <div className="flex items-center gap-2 mb-3">
          <Users className="w-5 h-5 text-cyan-300" />
          <h2 className="font-display text-xl text-white uppercase tracking-widest">Configuração do Evento</h2>
        </div>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          {[
            ["num_teams", "Equipes", "config-teams"],
            ["players_per_team", "Jogadores / Equipe", "config-players"],
            ["num_groups", "Grupos", "config-groups"],
            ["qualifiers_per_group", "Classificados / Grupo", "config-qualifiers"],
          ].map(([key, label, testId]) => (
            <label key={key} className="text-xs font-display uppercase tracking-widest text-slate-400">
              {label}
              <input
                data-testid={testId}
                type="number"
                min={1}
                value={cfg[key]}
                disabled={actionBusy}
                onChange={e => setCfg(c => ({ ...c, [key]: e.target.value }))}
                className="w-full mt-1 bg-slate-900 border border-slate-700 focus:border-cyan-400 px-3 py-2 text-white font-mono-num outline-none"
              />
            </label>
          ))}
        </div>
        <div className="mt-3 text-[11px] font-display uppercase tracking-widest text-slate-400 flex flex-wrap gap-x-6 gap-y-1">
          <span>Vagas totais: <span className="text-cyan-300">{Number(cfg.num_teams || 0) * Number(cfg.players_per_team || 0)}</span></span>
          <span>Classificados: <span className="text-cyan-300">{Number(cfg.num_groups || 0) * Number(cfg.qualifiers_per_group || 0)}</span></span>
          <span>Inscritos: <span className="text-white">{players.length}</span></span>
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button data-testid="save-config-btn" onClick={saveConfig} disabled={actionBusy}
            className="kop-chamfer bg-cyan-500 hover:bg-cyan-400 disabled:opacity-50 text-black font-arcade uppercase tracking-widest px-4 py-2 flex items-center gap-2">
            <Save className="w-4 h-4" /> {pendingAction === "save-config" ? "Salvando..." : "Salvar Configuração"}
          </button>
          {tour?.draw_done && (
            <span className="text-[10px] text-yellow-400 font-display uppercase tracking-widest">
              Estrutura sorteada — use Reset antes de alterar equipes/grupos
            </span>
          )}
        </div>
      </section>

      <section className="bg-black/60 border border-red-900/50 kop-chamfer p-5">
        <h2 className="font-display text-xl text-white uppercase tracking-widest mb-3">Equipes (renomear)</h2>
        <div className="grid sm:grid-cols-2 gap-3">
          {teams.map(t => (
            <div key={t.id} className="flex items-center gap-2 border border-slate-800 p-2">
              <span className="text-slate-500 font-mono-num text-xs">{t.group}</span>
              <input defaultValue={t.name} onBlur={e => e.target.value !== t.name && renameTeam(t.id, e.target.value)}
                data-testid={`team-rename-${t.id}`}
                className="flex-1 bg-transparent text-white font-display uppercase tracking-widest outline-none border-b border-transparent focus:border-red-500" />
              <span className="text-xs text-cyan-300">{t.players?.length || 0}/{tour?.players_per_team || 3}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="bg-black/60 border border-red-900/50 kop-chamfer p-5">
        <div className="flex items-center justify-between gap-2 mb-3 flex-wrap">
          <h2 className="font-display text-xl text-white uppercase tracking-widest">Jogadores Inscritos ({players.length})</h2>
          <input
            data-testid="player-search"
            value={playerSearch}
            onChange={e => setPlayerSearch(e.target.value)}
            placeholder="Buscar nome, apelido…"
            className="bg-slate-900 border border-slate-700 focus:border-red-500 px-3 py-1 text-white text-sm outline-none max-w-xs"
          />
        </div>
        <div className="max-h-[32rem] overflow-auto">
          <table className="w-full text-sm min-w-[640px]">
            <thead className="text-xs text-slate-500 uppercase sticky top-0 bg-slate-950 z-10">
              <tr>
                <th className="text-left p-2">Foto</th>
                <th className="text-left p-2">Nome · Apelido</th>
                <th className="text-left p-2">Nível</th>
                <th className="text-left p-2">Equipe</th>
                <th className="text-left p-2">Status</th>
                <th className="text-right p-2">Ações</th>
              </tr>
            </thead>
            <tbody>
              {players
                .filter(p => {
                  if (!playerSearch.trim()) return true;
                  const q = playerSearch.trim().toLowerCase();
                  return (p.name || "").toLowerCase().includes(q) || (p.nickname || "").toLowerCase().includes(q);
                })
                .map(p => (
                <tr key={p.id} className="border-t border-slate-800 hover:bg-slate-900/50">
                  <td className="p-2">
                    {p.photo ? (
                      <img src={p.photo} alt={p.name} className="w-10 h-10 object-cover rounded border border-red-500/40" />
                    ) : (
                      <div className="w-10 h-10 bg-slate-800 rounded flex items-center justify-center text-slate-600 text-xs">?</div>
                    )}
                  </td>
                  <td className="p-2">
                    <div className="text-white font-display uppercase tracking-wide">{p.name}</div>
                    {p.nickname && <div className="text-cyan-300 text-xs">"{p.nickname}"</div>}
                    {p.whatsapp && <div className="text-slate-500 text-[10px] font-mono-num">📱 {p.whatsapp}</div>}
                  </td>
                  <td className="p-2 text-slate-300 text-xs">{p.level}</td>
                  <td className="p-2 text-slate-400 text-xs">{teams.find(t => t.id === p.team_id)?.name || "—"}</td>
                  <td className="p-2">
                    <span className={`text-[10px] font-display uppercase tracking-widest px-1.5 py-0.5 border ${
                      p.status === "CONFIRMADO" ? "border-green-500/50 text-green-400"
                      : p.status === "PENDENTE" ? "border-yellow-500/50 text-yellow-400"
                      : "border-red-500/50 text-red-400"
                    }`}>{p.status}</span>
                  </td>
                  <td className="p-2 text-right">
                    <button data-testid={`edit-player-${p.id}`} onClick={() => { setEditing(p); sfx.select(); }} disabled={actionBusy}
                      className="text-cyan-300 hover:text-cyan-200 disabled:opacity-50 mr-2" title="Editar">
                      <Pencil className="w-4 h-4 inline" />
                    </button>
                    {confirmDelete === p.id ? (
                      <span data-testid={`delete-confirm-${p.id}`} className="inline-flex items-center gap-2">
                        <span className="text-[10px] text-yellow-400">Excluir?</span>
                        <button data-testid={`delete-confirm-btn-${p.id}`} onClick={() => removePlayer(p.id)} disabled={actionBusy}
                          className="text-red-400 hover:text-red-300 disabled:opacity-50">{pendingAction === `delete-player-${p.id}` ? "Excluindo..." : "Confirmar"}</button>
                        <button data-testid={`delete-cancel-btn-${p.id}`} onClick={() => setConfirmDelete(null)} disabled={actionBusy}
                          className="text-slate-400 hover:text-white disabled:opacity-50">Cancelar</button>
                      </span>
                    ) : (
                      <button data-testid={`delete-player-${p.id}`} onClick={() => setConfirmDelete(p.id)} disabled={actionBusy}
                        className="text-red-500 hover:text-red-400 disabled:opacity-50" title="Excluir">
                        <Trash2 className="w-4 h-4 inline" />
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {players.length === 0 && (
                <tr><td colSpan={6} className="p-8 text-center text-slate-500 font-display uppercase tracking-widest">Nenhum inscrito ainda</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="bg-black/60 border-2 border-red-500/30 kop-chamfer p-5">
        <div className="flex items-center gap-2 mb-2">
          <RefreshCw className="w-5 h-5 text-red-400" />
          <h2 className="font-display text-xl text-white uppercase tracking-widest">Recalcular Resultados (Regra v2)</h2>
        </div>
        <p className="text-[11px] text-slate-400 font-display uppercase tracking-widest mb-3">
          1 ponto por eliminação + 2 de bônus. Cada resultado anterior é arquivado no histórico antes de mudar.
        </p>
        <div className="flex flex-wrap gap-2">
          <button onClick={previewRecalc} disabled={actionBusy}
            className="kop-chamfer border-2 border-cyan-500 text-cyan-300 font-arcade uppercase tracking-widest px-4 py-2 disabled:opacity-50">
            {pendingAction === "recalc-preview" ? "Verificando..." : "Pré-visualizar"}
          </button>
          <button onClick={() => setConfirmRecalc(true)} disabled={actionBusy}
            className="kop-chamfer bg-red-600 hover:bg-red-500 text-white font-arcade uppercase tracking-widest px-4 py-2 disabled:opacity-50">
            Aplicar com backup
          </button>
        </div>
        {confirmRecalc && (
          <div className="mt-3 border border-amber-500/60 kop-chamfer p-3 flex flex-wrap items-center gap-2">
            <span className="text-[11px] text-amber-300 font-display uppercase tracking-widest">
              Confirmar recálculo? Os resultados anteriores serão arquivados e poderão ser restaurados.
            </span>
            <button onClick={applyRecalc} disabled={actionBusy}
              className="kop-chamfer bg-red-600 hover:bg-red-500 text-white font-arcade uppercase tracking-widest px-3 py-2 disabled:opacity-50">
              {pendingAction === "recalc-apply" ? "Recalculando..." : "Confirmar"}
            </button>
            <button onClick={() => setConfirmRecalc(false)} disabled={actionBusy}
              className="kop-chamfer border-2 border-slate-700 text-slate-400 px-3 py-2">
              Cancelar
            </button>
          </div>
        )}
        {recalc && (
          <div className="mt-3 text-xs text-slate-300 font-mono-num">
            {recalc.dry_run ? `${recalc.count} partida(s) com diferença` : `${recalc.applied} partida(s) recalculada(s)`}
            {(recalc.changes || []).slice(0, 8).map(c => (
              <div key={c.match_id} className="text-[11px] text-slate-400">
                #{c.number}: {c.before.points_a}·{c.before.points_b} → {c.after.points_a}·{c.after.points_b}
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="bg-black/60 border-2 border-amber-500/40 kop-chamfer p-5">
        <div className="flex items-center gap-2 mb-3">
          <ImageIcon className="w-5 h-5 text-amber-400" />
          <h2 className="font-display text-xl text-white uppercase tracking-widest">Banner do Evento</h2>
        </div>
        <div className="flex flex-col sm:flex-row gap-4 items-start">
          <div className="w-full sm:w-72 h-36 bg-slate-900 border border-slate-700 flex items-center justify-center overflow-hidden">
            {bannerDraft || banner
              ? <img src={bannerDraft || banner} alt={bannerDraft ? "Prévia do novo banner" : "Banner atual"} className="w-full h-full object-contain" />
              : <span className="text-slate-600 text-xs font-display uppercase tracking-widest">Sem banner</span>}
          </div>
          <div className="space-y-2">
            <input
              ref={bannerInputRef}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              className="sr-only"
              disabled={actionBusy}
              onChange={e => { selectBanner(e.target.files?.[0]); e.target.value = ""; }}
            />
            <button
              type="button"
              onClick={() => bannerInputRef.current?.click()}
              disabled={actionBusy}
              className="inline-block kop-chamfer bg-amber-500 hover:bg-amber-400 text-black font-arcade uppercase tracking-widest px-4 py-2 disabled:opacity-50"
            >
              Selecionar banner
            </button>
            <div className="text-[10px] text-slate-500 font-display uppercase tracking-widest">PNG, JPEG ou WEBP · máximo 900 KB</div>
            {bannerDraft && (
              <>
                <div className="text-[10px] text-cyan-300 font-display uppercase tracking-widest">Prévia: {bannerDraftName}</div>
                <div className="flex flex-wrap gap-2">
                  <button onClick={uploadBanner} disabled={actionBusy}
                    className="kop-chamfer bg-cyan-500 hover:bg-cyan-400 text-black font-arcade uppercase tracking-widest px-3 py-2 disabled:opacity-50">
                    {pendingAction === "banner" ? "Enviando..." : "Confirmar e enviar"}
                  </button>
                  <button onClick={() => { setBannerDraft(null); setBannerDraftName(""); }} disabled={actionBusy}
                    className="kop-chamfer border border-slate-700 text-slate-400 px-3 py-2 disabled:opacity-50">
                    Cancelar
                  </button>
                </div>
              </>
            )}
            {banner && !bannerDraft && (
              <button onClick={removeBanner} disabled={actionBusy} className="block text-red-400 hover:text-red-300 text-xs font-display uppercase tracking-widest disabled:opacity-50">
                Remover banner
              </button>
            )}
          </div>
        </div>
      </section>

      <section className="bg-black/60 border-2 border-cyan-500/30 kop-chamfer p-5">
        <div className="flex items-center gap-2 mb-3">
          <FileText className="w-5 h-5 text-cyan-300" />
          <h2 className="font-display text-xl text-white uppercase tracking-widest">Regras Públicas</h2>
          <span className="ml-auto text-[10px] font-mono-num text-slate-500">v{rules?.version || 1}</span>
        </div>
        <textarea value={rulesDraft} onChange={e => setRulesDraft(e.target.value)} rows={14} disabled={actionBusy}
          className="w-full bg-slate-900 border border-slate-700 focus:border-cyan-400 px-3 py-2 text-slate-200 text-sm font-mono outline-none"
          placeholder="# Regulamento..." />
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <button onClick={saveRules} disabled={actionBusy || !rulesDraft.trim()}
            className="kop-chamfer bg-cyan-500 hover:bg-cyan-400 text-black font-arcade uppercase tracking-widest px-4 py-2 flex items-center gap-2 disabled:opacity-50">
            <Save className="w-4 h-4" /> {pendingAction === "rules" ? "Publicando..." : "Publicar regras"}
          </button>
          <Link to="/rules" target="_blank" className="text-cyan-300 text-xs font-display uppercase tracking-widest">Ver página pública</Link>
          <span className="text-[10px] text-slate-500 font-display uppercase tracking-widest">
            Atualizado por {rules?.updated_by || "—"}
          </span>
        </div>
      </section>

      <section className="bg-black/60 border-2 border-yellow-500/30 kop-chamfer p-5">
        <div className="flex items-center gap-2 mb-3">
          <Users className="w-5 h-5 text-yellow-300" />
          <h2 className="font-display text-xl text-white uppercase tracking-widest">Rangers</h2>
        </div>
        <div className="grid sm:grid-cols-3 gap-2 mb-4">
          <input value={newRanger.name} onChange={e => setNewRanger(r => ({ ...r, name: e.target.value }))} placeholder="Nome"
            className="bg-slate-900 border border-slate-700 px-3 py-2 text-white text-sm outline-none" />
          <input value={newRanger.email} onChange={e => setNewRanger(r => ({ ...r, email: e.target.value }))} placeholder="E-mail" type="email"
            className="bg-slate-900 border border-slate-700 px-3 py-2 text-white text-sm outline-none" />
          <input value={newRanger.password} onChange={e => setNewRanger(r => ({ ...r, password: e.target.value }))} placeholder="Senha (mín. 6)" type="password"
            className="bg-slate-900 border border-slate-700 px-3 py-2 text-white text-sm outline-none" />
        </div>
        <button onClick={createRanger} disabled={actionBusy || !newRanger.name || !newRanger.email || newRanger.password.length < 6}
          className="kop-chamfer bg-yellow-500 hover:bg-yellow-400 text-black font-arcade uppercase tracking-widest px-4 py-2 flex items-center gap-2 disabled:opacity-50">
          <Plus className="w-4 h-4" /> {pendingAction === "ranger-create" ? "Criando..." : "Criar Ranger"}
        </button>
        <div className="mt-4 space-y-2">
          {rangers.length === 0 && (
            <div className="text-slate-500 text-xs font-display uppercase tracking-widest">Nenhum Ranger cadastrado</div>
          )}
          {rangers.map(r => (
            <div key={r.id} className="border border-slate-800 p-2 flex flex-wrap items-center gap-3">
              <div className="min-w-0">
                <div className="text-white font-display uppercase text-sm truncate">{r.name}</div>
                <div className="text-slate-500 text-[10px] font-mono-num truncate">{r.email}</div>
              </div>
              <span className={`text-[10px] px-1.5 py-0.5 border font-display uppercase tracking-widest ${r.active ? "border-green-500/50 text-green-400" : "border-red-500/50 text-red-400"}`}>
                {r.active ? "Ativo" : "Inativo"}
              </span>
              <button onClick={() => toggleRanger(r)} disabled={actionBusy}
                className="ml-auto text-xs font-display uppercase tracking-widest text-slate-300 hover:text-white disabled:opacity-50">
                {r.active
                  ? <><UserX className="w-3 h-3 inline mr-1" />Desativar</>
                  : <><UserCheck className="w-3 h-3 inline mr-1" />Ativar</>}
              </button>
            </div>
          ))}
        </div>
      </section>

      {editing && (
        <PlayerEditModal
          player={editing}
          onClose={() => setEditing(null)}
          onSaved={(updated) => {
            setPlayers(ps => ps.map(x => x.id === updated.id ? { ...x, ...updated } : x));
            setEditing(null);
            load().catch(() => toast.error("Inscrito salvo, mas não foi possível atualizar os dados"));
          }}
        />
      )}

      <section className="bg-black/60 border border-red-900/50 kop-chamfer p-5">
        <h2 className="font-display text-xl text-white uppercase tracking-widest mb-3">Partidas ({matches.length})</h2>
        {bracketStatus?.stale && (
          <div data-testid="bracket-warning" className="mb-3 border border-red-500/60 bg-red-950/40 kop-chamfer p-3 flex items-start gap-2 text-xs text-red-300">
            <AlertTriangle className="w-4 h-4 shrink-0" />
            <span><strong>Mata-mata possivelmente inválido:</strong> {bracketStatus.reason} Revise o chaveamento antes de continuar.</span>
          </div>
        )}
        <div className="grid sm:grid-cols-2 gap-2">
          {matches.map(m => {
            const ta = teams.find(t => t.id === m.team_a);
            const tb = teams.find(t => t.id === m.team_b);
            const isPinned = live.match_id === m.id;
            return (
              <div key={m.id} className={`border p-2 flex items-center gap-2 text-sm ${isPinned ? "border-cyan-400 bg-cyan-500/10" : "border-slate-800"}`}>
                <span className="font-mono-num text-xs text-red-400">#{m.number}</span>
                <span className="text-xs text-slate-500 uppercase">{m.phase}{m.group ? "-" + m.group : ""}</span>
                <span className="flex-1 text-white truncate">{ta?.name} vs {tb?.name}</span>
                <span className={`text-xs uppercase ${m.status === "ENCERRADA" ? "text-green-400" : m.status === "EM_ANDAMENTO" ? "text-red-400 animate-kop-pulse" : "text-yellow-400"}`}>{m.status}</span>
                <button data-testid={`pin-live-${m.id}`} onClick={() => pinMatch(m.id)} disabled={actionBusy} title="Fixar no telão" className={`${isPinned ? "text-cyan-300" : "text-slate-500 hover:text-cyan-300"} disabled:opacity-50`}><Tv className="w-3 h-3" /></button>
                <Link to={`/matches/${m.id}`} data-testid={`match-open-${m.id}`} className="text-cyan-300 text-xs uppercase font-display">Abrir</Link>
                {m.status === "ENCERRADA" && (
                  <button data-testid={`match-redo-${m.id}`} onClick={() => { setRedoMatch(m); setRedoReason(""); }} disabled={actionBusy}
                    title="Refazer partida" className="text-amber-500 hover:text-amber-300 disabled:opacity-50">
                    <RotateCcw className="w-3 h-3" />
                  </button>
                )}
                <button data-testid={`match-history-${m.id}`} onClick={() => openHistory(m)} disabled={actionBusy}
                  title="Histórico e restauração" className="text-slate-500 hover:text-cyan-300 disabled:opacity-50">
                  <History className="w-3 h-3" />
                </button>
                <button data-testid={`match-lock-${m.id}`} onClick={() => toggleLock(m.id)} disabled={actionBusy} className="text-slate-400 disabled:opacity-50">{m.locked ? <Lock className="w-3 h-3 text-red-400" /> : <Unlock className="w-3 h-3" />}</button>
              </div>
            );
          })}
        </div>
        {redoMatch && (
          <div data-testid="redo-confirm" className="mt-3 border border-amber-500/60 kop-chamfer p-3 flex flex-wrap items-center gap-2">
            <span className="text-xs text-amber-300 font-display uppercase tracking-widest">
              Refazer MATCH {String(redoMatch.number).padStart(2, "0")}? O resultado atual será arquivado.
            </span>
            <input value={redoReason} onChange={e => setRedoReason(e.target.value)} placeholder="Motivo (opcional)"
              className="bg-slate-900 border border-slate-700 px-3 py-1.5 text-white text-sm outline-none" />
            <button onClick={runRedo} disabled={actionBusy}
              className="kop-chamfer bg-amber-500 hover:bg-amber-400 text-black font-arcade uppercase tracking-widest px-3 py-2 disabled:opacity-50">
              Confirmar
            </button>
            <button onClick={() => setRedoMatch(null)} disabled={actionBusy}
              className="kop-chamfer border-2 border-slate-700 text-slate-400 px-3 py-2">
              Cancelar
            </button>
          </div>
        )}

        {historyMatch && (
          <div className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4"
            onClick={() => setHistoryMatch(null)}>
            <div data-testid="history-modal"
              className="w-full max-w-2xl max-h-[80vh] overflow-auto bg-slate-950 border-2 border-cyan-500/50 kop-chamfer p-4"
              onClick={e => e.stopPropagation()}>
              <div className="flex items-center justify-between mb-3">
                <h3 className="font-display text-cyan-300 uppercase tracking-widest text-sm">
                  Histórico — MATCH {String(historyMatch.number).padStart(2, "0")}
                </h3>
                <button onClick={() => setHistoryMatch(null)} className="text-slate-400 hover:text-white text-xs uppercase">Fechar</button>
              </div>
              {historyBusy ? (
                <div className="text-slate-400 text-xs uppercase">Carregando histórico...</div>
              ) : historyDocs.length === 0 ? (
                <div className="text-slate-500 text-xs uppercase">Nenhum snapshot arquivado para esta partida.</div>
              ) : historyDocs.map(h => {
                const isRecalc = h.kind === "RECALCULATION" || (h.reason || "").toLowerCase().includes("recálculo");
                return (
                  <div key={h.id} className="border border-slate-800 p-2 mb-2 text-xs text-slate-300">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="text-white font-mono-num">
                        {h.snapshot?.points_a ?? "—"} × {h.snapshot?.points_b ?? "—"}
                      </span>
                      <span className="text-slate-500">{h.archived_at}</span>
                    </div>
                    <div className="mt-1 text-slate-400">
                      {isRecalc ? "Snapshot de recálculo" : h.kind === "RESTORE" ? "Snapshot de restauração" : "Snapshot"}
                      {h.reason ? ` · ${h.reason}` : ""} · versão {h.snapshot?.scoring_version ?? "legado"}
                    </div>
                    {h.restored_at ? (
                      <div className="mt-1 text-green-400 uppercase">Restaurado em {h.restored_at}</div>
                    ) : isRecalc ? (
                      confirmRestore?.id === h.id ? (
                        <div className="mt-2 flex flex-wrap items-center gap-2 border border-amber-500/60 p-2">
                          <span className="text-amber-300">Restaurar este snapshot? A partida volta ao resultado anterior ao recálculo.</span>
                          <button onClick={() => runRestore(h)} disabled={actionBusy}
                            className="kop-chamfer bg-amber-500 text-black font-arcade uppercase px-2 py-1 disabled:opacity-50">
                            Confirmar
                          </button>
                          <button onClick={() => setConfirmRestore(null)} disabled={actionBusy}
                            className="kop-chamfer border border-slate-700 text-slate-400 px-2 py-1">
                            Cancelar
                          </button>
                        </div>
                      ) : (
                        <button onClick={() => setConfirmRestore(h)} disabled={actionBusy}
                          className="mt-2 kop-chamfer border border-cyan-500/60 text-cyan-300 hover:bg-cyan-500 hover:text-black font-arcade uppercase px-2 py-1 disabled:opacity-50">
                          Restaurar este snapshot
                        </button>
                      )
                    ) : (
                      <div className="mt-1 text-slate-600 uppercase">Somente leitura</div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
