import React, { useEffect, useState } from "react";
import { api } from "../api";

export default function Standings() {
  const [s, setS] = useState({});
  const [qpg, setQpg] = useState(2);
  useEffect(() => {
    Promise.all([api.get("/standings"), api.get("/tournament")]).then(([r, t]) => {
      setS(r.data || {});
      setQpg(t.data?.qualifiers_per_group || 2);
    });
  }, []);

  const groups = Object.keys(s).sort();
  const pendingTiebreak = Object.values(s).some(rows =>
    (rows || []).some(r => r.tiebreak_pending));

  const Table = ({ rows, name, color }) => (
    <div className="mb-8">
      <div className={`font-arcade text-2xl ${color} uppercase mb-2 tracking-widest`}>Grupo {name}</div>
      <div className="overflow-auto border border-slate-800 kop-chamfer">
        <table className="w-full text-sm">
          <thead className="bg-black/70 text-slate-500 uppercase text-xs">
            <tr>
              <th className="p-2 text-left">POS</th>
              <th className="p-2 text-left">Equipe</th>
              <th className="p-2 text-right">J</th>
              <th className="p-2 text-right">V</th>
              <th className="p-2 text-right">E</th>
              <th className="p-2 text-right">D</th>
              <th className="p-2 text-right">ELIMS</th>
              <th className="p-2 text-right">SAL</th>
              <th className="p-2 text-right">PF</th>
              <th className="p-2 text-right">Pts</th>
            </tr>
          </thead>
          <tbody>
            {(rows || []).map((r, i) => (
              <tr key={r.team_id} data-testid={`standing-row-${r.team_id}`} className={`border-t border-slate-800 ${i < qpg ? "bg-red-500/10" : ""}`}>
                <td className="p-2 font-mono-num text-red-400">{i === 0 ? "🥇" : i === 1 ? "🥈" : i === 2 ? "🥉" : `${i + 1}º`}</td>
                <td className="p-2 font-display uppercase text-white">{r.team_name}</td>
                <td className="p-2 text-right font-mono-num">{r.played}</td>
                <td className="p-2 text-right font-mono-num text-green-400">{r.wins}</td>
                <td className="p-2 text-right font-mono-num text-cyan-300">{r.draws}</td>
                <td className="p-2 text-right font-mono-num text-red-400">{r.losses}</td>
                <td className="p-2 text-right font-mono-num text-cyan-300">{r.elims_for}/{r.elims_against}</td>
                <td className={`p-2 text-right font-mono-num ${r.diff > 0 ? "text-green-400" : r.diff < 0 ? "text-red-400" : "text-slate-400"}`}>{r.diff > 0 ? "+" : ""}{r.diff}</td>
                <td className="p-2 text-right font-mono-num text-amber-400">{r.perfects || 0}</td>
                <td className="p-2 text-right font-arcade text-yellow-400">{r.points}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );

  return (
    <div className="max-w-5xl mx-auto px-4 py-8">
      <div className="mb-6">
        <div className="font-display text-cyan-300 text-xs tracking-[0.4em] uppercase">Ranking</div>
        <h1 className="font-arcade text-3xl text-red-500 uppercase">Classificação</h1>
        <div className="text-slate-500 text-xs mt-1 font-display tracking-widest uppercase">
          Pts = pontos (1 por eliminação + 2 de bônus) · V = vitórias · E = empates · D = derrotas · SAL = saldo de eliminações · PF = PERFECTs
        </div>
        <div className="text-cyan-300/80 text-[10px] mt-1 font-display tracking-widest uppercase">
          {qpg} classificado(s) por grupo · Desempate: pontos, vitórias, saldo, PERFECTs, confronto direto
        </div>
        {pendingTiebreak && (
          <div data-testid="tiebreak-pending" className="text-amber-300/90 text-[10px] mt-1 font-display tracking-widest uppercase">
            Empate ainda não resolvido após o confronto direto. Critérios 6 e 7 aguardam definição da organização.
          </div>
        )}
      </div>
      {groups.length === 0 && (
        <div className="text-slate-500 text-center py-20 font-display uppercase tracking-widest">Aguardando sorteio</div>
      )}
      {groups.map((g, i) => (
        <Table key={g} rows={s[g]} name={g} color={i % 2 === 0 ? "text-red-400" : "text-cyan-300"} />
      ))}
    </div>
  );
}
