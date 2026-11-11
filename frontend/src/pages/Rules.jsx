import React, { useEffect, useState } from "react";
import { api } from "../api";
import { BookOpen } from "lucide-react";

function Blocks({ content }) {
  const lines = (content || "").split("\n");
  return lines.map((line, i) => {
    const key = `rule-${i}`;
    if (line.startsWith("### ")) {
      return <h3 key={key} className="font-display text-base text-white uppercase tracking-widest mt-4 mb-1">{line.slice(4)}</h3>;
    }
    if (line.startsWith("## ")) {
      return <h2 key={key} className="font-display text-lg text-cyan-300 uppercase tracking-widest mt-6 mb-2">{line.slice(3)}</h2>;
    }
    if (line.startsWith("# ")) {
      return <h1 key={key} className="font-arcade text-2xl text-red-500 uppercase mt-6 mb-3">{line.slice(2)}</h1>;
    }
    if (line.startsWith("- ")) {
      return (
        <div key={key} className="flex gap-2 text-sm text-slate-300 leading-relaxed mb-1">
          <span className="text-red-500 shrink-0">▸</span>
          <span>{line.slice(2)}</span>
        </div>
      );
    }
    if (/^\d+\.\s/.test(line)) {
      return (
        <div key={key} className="flex gap-2 text-sm text-slate-300 leading-relaxed mb-1">
          <span className="text-cyan-300 font-mono-num shrink-0">{line.split(".")[0]}.</span>
          <span>{line.replace(/^\d+\.\s/, "")}</span>
        </div>
      );
    }
    if (!line.trim()) return <div key={key} className="h-2" />;
    return <p key={key} className="text-sm text-slate-300 leading-relaxed mb-2">{line}</p>;
  });
}

export default function Rules() {
  const [rules, setRules] = useState(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    api.get("/rules")
      .then(r => setRules(r.data))
      .catch(() => setError(true));
  }, []);

  return (
    <div className="max-w-3xl mx-auto px-4 py-8">
      <div className="mb-6">
        <div className="flex items-center gap-2 font-display text-cyan-300 text-xs tracking-[0.4em] uppercase">
          <BookOpen className="w-4 h-4" /> Regulamento oficial
        </div>
        <h1 data-testid="rules-title" className="font-arcade text-3xl text-red-500 uppercase">Regras KOP 3x3</h1>
        {rules?.version && (
          <div className="text-slate-500 text-[10px] mt-1 font-display tracking-widest uppercase">
            Versão {rules.version}{rules.updated_at ? ` · atualizada em ${new Date(rules.updated_at).toLocaleDateString("pt-BR")}` : ""}
          </div>
        )}
      </div>

      <div data-testid="rules-content" className="bg-black/60 border-2 border-red-900/40 kop-chamfer p-5">
        {error && <div className="text-red-400 text-sm">Não foi possível carregar as regras.</div>}
        {!error && !rules && <div className="text-slate-500 text-sm">Carregando...</div>}
        {rules && <Blocks content={rules.content} />}
      </div>
    </div>
  );
}
