import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";

export default function Matches() {
  const [matches, setMatches] = useState([]);
  const [teams, setTeams] = useState([]);
  useEffect(() => {
    Promise.all([api.get("/matches"), api.get("/teams")]).then(([m, t]) => {
      setMatches(m.data); setTeams(t.data);
    });
  }, []);
  const tname = id => teams.find(t => t.id === id)?.name || "—";

  const grouped = matches.reduce((acc, m) => {
    const key = m.phase === "GROUP" ? `Grupo ${m.group}` : m.phase;
    (acc[key] ||= []).push(m); return acc;
  }, {});

  return (
    <div className="max-w-6xl mx-auto px-4 py-8">
      <div className="mb-6">
        <div className="font-display text-cyan-300 text-xs tracking-[0.4em] uppercase">Fixtures</div>
        <h1 className="font-arcade text-3xl text-red-500 uppercase">Tabela de Partidas</h1>
      </div>
      {matches.length === 0 && <div className="text-slate-500 text-center py-20 font-display uppercase tracking-widest">Sem partidas ainda</div>}
      {Object.entries(grouped).map(([grp, ms]) => (
        <div key={grp} className="mb-6">
          <div className="font-arcade text-xl text-red-400 uppercase mb-2 tracking-widest">{grp}</div>
          <div className="grid sm:grid-cols-2 gap-3">
            {ms.map(m => (
              <Link to={`/matches/${m.id}`} key={m.id} data-testid={`match-item-${m.id}`}
                className="bg-black/60 border-2 border-slate-800 hover:border-red-500 kop-chamfer p-3 transition group">
                <div className="flex items-center justify-between text-xs mb-2">
                  <span className="font-arcade text-red-400">MATCH {String(m.number).padStart(2, "0")}</span>
                  <span className={`font-display uppercase tracking-widest ${m.status === "ENCERRADA" ? "text-green-400" : "text-yellow-400"}`}>{m.status}</span>
                </div>
                <div className="flex items-center justify-between font-display uppercase tracking-wider">
                  <div className={`flex-1 ${m.winner_team_id === m.team_a ? "text-red-400" : "text-slate-200"} truncate`}>{tname(m.team_a)}</div>
                  <div className="font-arcade text-cyan-300 px-3">VS</div>
                  <div className={`flex-1 text-right ${m.winner_team_id === m.team_b ? "text-red-400" : "text-slate-200"} truncate`}>{tname(m.team_b)}</div>
                </div>
                {m.status === "ENCERRADA" && (
                  <div className="mt-2 font-mono-num text-sm flex justify-between text-cyan-300">
                    <span>{m.points_a}</span>
                    <span className={m.wo ? "text-amber-400 font-display uppercase text-[10px] tracking-widest" : "text-slate-600"}>
                      {m.wo ? "W.O." : `${m.elims_a} × ${m.elims_b}`}
                    </span>
                    <span>{m.points_b}</span>
                  </div>
                )}
              </Link>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
