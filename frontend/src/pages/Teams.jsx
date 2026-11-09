import React, { useEffect, useState } from "react";
import { api } from "../api";
import { PlayerCard } from "../components/PlayerCard";

const GROUP_COLORS = [
  "text-red-400", "text-cyan-300", "text-yellow-400", "text-green-400",
  "text-orange-400", "text-purple-300",
];

export default function Teams() {
  const [teams, setTeams] = useState([]);
  const [players, setPlayers] = useState([]);
  const [tour, setTour] = useState(null);
  useEffect(() => {
    Promise.all([api.get("/teams"), api.get("/players"), api.get("/tournament")]).then(([t, p, c]) => {
      setTeams(t.data); setPlayers(p.data); setTour(c.data);
    });
  }, []);
  const byId = Object.fromEntries(players.map(p => [p.id, p]));

  const perTeam = Math.max(1, tour?.players_per_team || 3);
  const slots = Array.from({ length: perTeam }, (_, i) => i);
  const teamGroups = [...new Set(teams.map(t => t.group || "A"))].sort();
  const groupColor = (g) => GROUP_COLORS[teamGroups.indexOf(g) % GROUP_COLORS.length];

  const TeamBlock = ({ t }) => (
    <div className="bg-black/70 border-2 border-slate-800 kop-chamfer p-3" data-testid={`team-block-${t.id}`}>
      <div className="flex items-center justify-between mb-2">
        <div className={`font-arcade text-lg ${groupColor(t.group || "A")} uppercase tracking-wider truncate`}>{t.name}</div>
        <div className="text-xs text-slate-500 font-mono-num">GRP {t.group || "—"}</div>
      </div>
      <div className="grid grid-cols-3 gap-2">
        {slots.map(i => {
          const p = byId[t.players?.[i]];
          return p ? <PlayerCard key={i} player={p} size="sm" showLevel={false} /> : (
            <div key={i} className="w-full aspect-[3/4] kop-chamfer border-2 border-dashed border-slate-800 flex items-center justify-center text-slate-700 font-arcade text-2xl">?</div>
          );
        })}
      </div>
    </div>
  );

  return (
    <div className="max-w-6xl mx-auto px-4 py-8 space-y-8">
      <div>
        <div className="font-display text-cyan-300 text-xs tracking-[0.4em] uppercase">Teams & Groups</div>
        <h1 className="font-arcade text-3xl text-red-500 uppercase">Equipes KOP 3x3</h1>
        <div className="text-slate-500 font-mono-num text-xs mt-1 uppercase tracking-widest">
          {teams.length} equipes · {perTeam} jogadores por equipe · {teamGroups.length} grupo(s)
        </div>
      </div>
      {teamGroups.map((g) => (
        <div key={g}>
          <div className={`font-arcade text-2xl ${groupColor(g)} mb-3 uppercase`}>Grupo {g}</div>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {teams.filter(t => (t.group || "A") === g).map(t => <TeamBlock key={t.id} t={t} />)}
          </div>
        </div>
      ))}
    </div>
  );
}
