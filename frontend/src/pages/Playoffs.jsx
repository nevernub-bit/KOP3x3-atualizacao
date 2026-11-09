import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";

const PHASES = [
  ["R16", "Oitavas de Final", "text-red-400"],
  ["QF", "Quartas de Final", "text-red-400"],
  ["SEMI", "Semifinais", "text-red-400"],
  ["FINAL", "🏆 GRANDE FINAL", "text-yellow-400"],
  ["THIRD", "🥉 3º Lugar", "text-orange-400"],
];

export default function Playoffs() {
  const [matches, setMatches] = useState([]);
  const [teams, setTeams] = useState([]);
  useEffect(() => {
    Promise.all([api.get("/playoffs"), api.get("/teams")]).then(([p, t]) => {
      setMatches(p.data); setTeams(t.data);
    });
  }, []);
  const tname = id => teams.find(t => t.id === id)?.name || "TBD";

  const Card = ({ m, label, color }) => m ? (
    <Link to={`/matches/${m.id}`} className="block bg-black/70 border-2 border-slate-800 hover:border-red-500 kop-chamfer p-4 transition">
      <div className={`font-arcade text-xs ${color} tracking-widest uppercase mb-2`}>{label}</div>
      <div className="flex items-center justify-between font-display uppercase text-white">
        <span className={m.winner_team_id === m.team_a ? "text-yellow-400" : ""}>{tname(m.team_a)}</span>
        <span className="text-red-400 font-arcade">VS</span>
        <span className={m.winner_team_id === m.team_b ? "text-yellow-400" : ""}>{tname(m.team_b)}</span>
      </div>
      {m.status === "ENCERRADA" && <div className="text-center mt-2 text-cyan-300 font-mono-num text-sm">{m.points_a} · {m.points_b}</div>}
    </Link>
  ) : (
    <div className="bg-black/40 border-2 border-dashed border-slate-800 kop-chamfer p-4 text-center text-slate-600 font-display uppercase tracking-widest text-xs">
      {label} — Aguardando
    </div>
  );

  const present = PHASES.filter(([phase]) => matches.some(m => m.phase === phase));

  return (
    <div className="max-w-5xl mx-auto px-4 py-8">
      <div className="mb-6 text-center">
        <div className="font-display text-cyan-300 text-xs tracking-[0.4em] uppercase">Elimination Round</div>
        <h1 className="font-arcade text-4xl text-red-500 uppercase animate-kop-pulse">Mata-Mata</h1>
      </div>

      {present.length === 0 && (
        <div className="bg-black/40 border-2 border-dashed border-slate-800 kop-chamfer p-8 text-center text-slate-600 font-display uppercase tracking-widest text-xs">
          Aguardando o fim da fase de grupos
        </div>
      )}

      <div className="space-y-8">
        {present.map(([phase, label, color]) => (
          <section key={phase} data-testid={`playoff-${phase.toLowerCase()}`}>
            <div className={`font-arcade text-xl ${color} uppercase tracking-widest mb-3 text-center`}>{label}</div>
            <div className="grid sm:grid-cols-2 gap-4">
              {matches
                .filter(m => m.phase === phase)
                .sort((a, b) => a.number - b.number)
                .map(m => (
                  <Card key={m.id} m={m} color={color}
                    label={`MATCH ${String(m.number).padStart(2, "0")}`} />
                ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}
