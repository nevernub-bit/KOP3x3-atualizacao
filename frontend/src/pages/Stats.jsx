import React, { useEffect, useState } from "react";
import { api } from "../api";

export default function Stats() {
  const [players, setPlayers] = useState([]);
  const [tstats, setTstats] = useState([]);
  useEffect(() => {
    Promise.all([api.get("/stats/players"), api.get("/stats/teams")]).then(([p, t]) => {
      setPlayers(p.data); setTstats(t.data);
    });
  }, []);

  return (
    <div className="max-w-6xl mx-auto px-4 py-8 space-y-10">
      <div>
        <div className="font-display text-cyan-300 text-xs tracking-[0.4em] uppercase">Kop Stats</div>
        <h1 className="font-arcade text-3xl text-red-500 uppercase">Estatísticas</h1>
        <div className="text-xs text-slate-500 font-display tracking-widest uppercase mt-1">
          Ranking individual: vitórias da equipe · perfects · sobrevivências · menos eliminado
        </div>
      </div>

      <section>
        <div className="font-arcade text-xl text-red-400 uppercase mb-3">Ranking Individual</div>
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {players.map((p, i) => (
            <div key={p.player_id} data-testid={`stat-player-${p.player_id}`} className="bg-black/60 border border-slate-800 kop-chamfer p-3 flex items-center gap-3">
              <div className="font-arcade text-2xl text-yellow-400 w-8 text-center">{i + 1}</div>
              {p.photo && <img src={p.photo} className="w-12 h-12 object-cover rounded border-2 border-red-500/50" alt={p.name} />}
              <div className="flex-1 min-w-0">
                <div className="font-display uppercase text-white truncate">{p.name}</div>
                <div className="text-xs text-slate-500 uppercase truncate">{p.team_name || "—"}</div>
                <div className="text-[10px] font-mono-num text-slate-400 mt-1">
                  <span className="text-green-400">V{p.team_wins}</span>
                  {" · "}<span className="text-cyan-300">E{p.team_draws}</span>
                  {" · "}<span className="text-red-400">D{p.team_losses}</span>
                  {" · "}<span className="text-orange-400">P{p.perfects}</span>
                </div>
              </div>
              <div className="text-right">
                <div className="font-arcade text-red-400 text-xs">{p.times_eliminated}✝</div>
                <div className="text-[10px] text-slate-500 uppercase">eliminado</div>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section>
        <div className="font-arcade text-xl text-cyan-300 uppercase mb-3">Estatísticas das Equipes</div>
        <div className="overflow-auto border border-slate-800 kop-chamfer">
          <table className="w-full text-sm">
            <thead className="bg-black/70 text-slate-500 uppercase text-xs">
              <tr>
                <th className="p-2 text-left">Equipe</th>
                <th className="p-2 text-right">J</th><th className="p-2 text-right">V</th>
                <th className="p-2 text-right">E</th><th className="p-2 text-right">D</th>
                <th className="p-2 text-right">Pts</th><th className="p-2 text-right">Elims</th>
                <th className="p-2 text-right">Streak</th><th className="p-2 text-right">Perf</th>
              </tr>
            </thead>
            <tbody>
              {tstats.map(t => (
                <tr key={t.team_id} className="border-t border-slate-800">
                  <td className="p-2 font-display uppercase text-white">{t.team_name}</td>
                  <td className="p-2 text-right font-mono-num">{t.played}</td>
                  <td className="p-2 text-right font-mono-num text-green-400">{t.wins}</td>
                  <td className="p-2 text-right font-mono-num text-cyan-300">{t.draws}</td>
                  <td className="p-2 text-right font-mono-num text-red-400">{t.losses}</td>
                  <td className="p-2 text-right font-arcade text-yellow-400">{t.points}</td>
                  <td className="p-2 text-right font-mono-num text-cyan-300">{t.elims_for}/{t.elims_against}</td>
                  <td className="p-2 text-right font-mono-num">{t.best_streak}</td>
                  <td className="p-2 text-right font-mono-num text-orange-400">{t.perfects}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
