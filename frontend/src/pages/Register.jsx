import React, { useState, useRef, useEffect } from "react";
import { Link } from "react-router-dom";
import { api, formatErr } from "../api";
import { toast } from "sonner";
import { PlayerCard } from "../components/PlayerCard";
import { Camera, Volume2, VolumeX } from "lucide-react";
import { sfx, isMuted, setMuted as setGlobalMute } from "../sound";

const LEVELS = ["INICIANTE", "INTERMEDIÁRIO", "PROFISSIONAL"];

async function fileToBase64(file) {
  const bitmap = await createImageBitmap(file);
  const max = 800;
  const scale = Math.min(1, max / Math.max(bitmap.width, bitmap.height));
  const w = Math.round(bitmap.width * scale);
  const h = Math.round(bitmap.height * scale);
  const canvas = document.createElement("canvas");
  canvas.width = w; canvas.height = h;
  canvas.getContext("2d").drawImage(bitmap, 0, 0, w, h);
  return canvas.toDataURL("image/jpeg", 0.82);
}

// Uses shared sound library

// --- STAGE 1: Arcade splash / START screen ---
function StartScreen({ onStart, muted, setMuted }) {
  // Deterministic particles so they don't jitter on rerender
  const particles = React.useMemo(() => (
    Array.from({ length: 22 }).map((_, i) => ({
      left: (i * 47) % 100,
      top: (i * 73) % 100,
      size: 2 + ((i * 13) % 5),
      delay: (i % 10) * 0.4,
      duration: 6 + ((i * 7) % 8),
      color: i % 3 === 0 ? "#ff2e4c" : i % 3 === 1 ? "#00e5ff" : "#ffd000",
    }))
  ), []);

  return (
    <div className="fixed inset-0 z-50 bg-black overflow-hidden">
      {/* Background layers */}
      <div className="absolute inset-0 kop-grid-bg opacity-40" />
      <div className="absolute inset-0 kop-diag-bg" />
      <div className="scanlines absolute inset-0 opacity-70" />
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background:
            "radial-gradient(ellipse at 30% 20%, rgba(255,46,76,0.28) 0%, transparent 55%), radial-gradient(ellipse at 70% 80%, rgba(0,229,255,0.22) 0%, transparent 55%), radial-gradient(circle at 50% 50%, transparent 40%, rgba(0,0,0,0.85) 100%)",
        }}
      />

      {/* Floating particles */}
      {particles.map((p, i) => (
        <span
          key={i}
          className="absolute rounded-full"
          style={{
            left: `${p.left}%`,
            top: `${p.top}%`,
            width: p.size,
            height: p.size,
            background: p.color,
            boxShadow: `0 0 12px ${p.color}`,
            opacity: 0.85,
            animation: `kop-float ${p.duration}s ease-in-out ${p.delay}s infinite alternate`,
          }}
        />
      ))}

      {/* Corner brackets — arcade UI accent */}
      <div className="absolute top-4 left-4 w-10 h-10 border-l-2 border-t-2 border-red-500/70" />
      <div className="absolute top-4 right-4 w-10 h-10 border-r-2 border-t-2 border-red-500/70" />
      <div className="absolute bottom-4 left-4 w-10 h-10 border-l-2 border-b-2 border-cyan-500/70" />
      <div className="absolute bottom-4 right-4 w-10 h-10 border-r-2 border-b-2 border-cyan-500/70" />

      {/* Sound toggle */}
      <button
        data-testid="sound-toggle"
        onClick={() => { const n = !muted; setMuted(n); setGlobalMute(n); if (!n) sfx.select(); }}
        className="absolute top-4 right-16 sm:right-20 z-20 text-slate-400 hover:text-white p-2 border border-slate-700/60 kop-chamfer"
        aria-label="Alternar som"
      >
        {muted ? <VolumeX className="w-4 h-4" /> : <Volume2 className="w-4 h-4" />}
      </button>

      {/* Home escape (small, discreet) */}
      <Link
        to="/"
        data-testid="start-back-home"
        className="absolute top-5 left-4 z-20 text-[10px] font-display uppercase tracking-[0.35em] text-slate-600 hover:text-slate-300"
      >
        ← exit
      </Link>

      {/* Content */}
      <div className="relative z-10 min-h-screen flex flex-col items-center justify-center px-6 text-center">
        <div className="font-display text-xs sm:text-sm tracking-[0.5em] text-cyan-300 uppercase mb-3 animate-kop-flicker">
          Player Invitation
        </div>

        <h1
          data-testid="start-title"
          className="font-arcade text-4xl sm:text-6xl lg:text-7xl text-red-500 uppercase leading-none animate-kop-pulse"
          style={{ textShadow: "0 0 24px rgba(255,46,76,0.9), 0 0 60px rgba(255,46,76,0.35)" }}
        >
          Kings of Paintball
        </h1>

        <div className="mt-2 font-display text-2xl sm:text-4xl text-slate-100 tracking-widest">
          KOP <span className="text-red-500">3×3</span>
        </div>

        <div className="mt-8 max-w-lg font-display text-base sm:text-lg text-slate-300 leading-snug uppercase tracking-wider">
          Sua jornada no <span className="text-cyan-300">Paintball Arcade</span> começa agora.
        </div>

        <div className="mt-4 font-mono-num text-[10px] sm:text-xs text-slate-500 tracking-[0.5em] uppercase">
          Insert Coin · 1 Player · Ready
        </div>

        {/* START Button */}
        <button
          data-testid="start-button"
          onClick={onStart}
          className="group relative overflow-hidden mt-10 sm:mt-12 kop-chamfer bg-gradient-to-b from-red-500 to-red-800 hover:from-red-400 hover:to-red-700 active:scale-95 text-white font-arcade uppercase tracking-[0.4em] text-2xl sm:text-4xl px-12 sm:px-20 py-5 sm:py-6 kop-glow-red animate-kop-pulse transition-transform border-2 border-red-300/40"
          style={{ minWidth: "min(88vw, 22rem)" }}
        >
          <span className="relative z-10">▶ Press Start</span>
          <span
            className="absolute inset-0 kop-chamfer pointer-events-none"
            style={{
              background:
                "linear-gradient(120deg, transparent 30%, rgba(255,255,255,0.35) 50%, transparent 70%)",
              animation: "kop-sheen 2.6s linear infinite",
            }}
          />
        </button>

        <div className="mt-4 font-display text-[10px] sm:text-xs tracking-[0.5em] text-slate-600 uppercase">
          © KOP · 3 Players · 1 Team · 1 Champion
        </div>
      </div>

      {/* Local keyframes just for this splash */}
      <style>{`
        @keyframes kop-float {
          0%   { transform: translate(0, 0);       opacity: 0.9; }
          100% { transform: translate(20px, -30px); opacity: 0.3; }
        }
        @keyframes kop-sheen {
          0%   { transform: translateX(-120%); }
          100% { transform: translateX(120%); }
        }
      `}</style>
    </div>
  );
}

// --- STAGE 2: Cinematic transition ---
function Transition() {
  return (
    <div className="fixed inset-0 z-50 bg-black overflow-hidden flex items-center justify-center">
      <div className="scanlines absolute inset-0" />
      <div className="absolute inset-0 kop-grid-bg opacity-40" />
      <div
        className="absolute inset-0"
        style={{
          background:
            "radial-gradient(circle at center, rgba(255,46,76,0.6) 0%, transparent 60%)",
          animation: "kop-zoom 0.9s ease-out forwards",
        }}
      />
      <div className="relative animate-kop-slam">
        <div
          className="font-arcade text-6xl sm:text-9xl text-white uppercase tracking-widest"
          style={{ textShadow: "0 0 40px rgba(255,46,76,1)" }}
        >
          READY?
        </div>
      </div>
      <style>{`
        @keyframes kop-zoom {
          0%   { transform: scale(0.2); opacity: 0; }
          50%  { transform: scale(1);   opacity: 1; }
          100% { transform: scale(3);   opacity: 0; }
        }
      `}</style>
    </div>
  );
}

// --- STAGE 3: Form ---
function RegistrationForm({ onSubmitted }) {
  const [name, setName] = useState("");
  const [nickname, setNickname] = useState("");
  const [level, setLevel] = useState("INTERMEDIÁRIO");
  const [whatsapp, setWhatsapp] = useState("");
  const [notes, setNotes] = useState("");
  const [photo, setPhoto] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const fileRef = useRef();

  const onFile = async (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    try {
      const b64 = await fileToBase64(f);
      setPhoto(b64);
    } catch { toast.error("Não foi possível processar a foto"); }
  };

  const submit = async (e) => {
    e.preventDefault();
    if (!name.trim()) return toast.error("Informe seu nome");
    if (!photo) return toast.error("Envie sua foto");
    setSubmitting(true);
    try {
      const r = await api.post("/players/register", {
        name, nickname: nickname || null, level, photo,
        whatsapp: whatsapp || null, notes: notes || null,
      });
      sfx.success();
      toast.success("Inscrição enviada! Aguardando aprovação do organizador.");
      onSubmitted(r.data);
    } catch (err) {
      toast.error(formatErr(err.response?.data?.detail) || "Falha no envio");
    } finally { setSubmitting(false); }
  };

  return (
    <div className="min-h-screen relative overflow-hidden animate-kop-slam">
      <div className="absolute inset-0 kop-grid-bg opacity-20 pointer-events-none" />
      <div className="relative max-w-2xl mx-auto px-4 py-8">
        <div className="text-center mb-6">
          <div className="font-display text-cyan-300 text-xs tracking-[0.4em] uppercase">Player Registration</div>
          <h1 className="font-arcade text-3xl sm:text-4xl text-red-500 uppercase animate-kop-pulse">Inscrição KOP 3x3</h1>
          <div className="font-display text-xs text-slate-500 tracking-widest uppercase mt-1">Preencha seus dados de combate</div>
        </div>
        <form onSubmit={submit} className="space-y-4 bg-black/60 border border-red-900/50 kop-chamfer p-5 sm:p-8">
          <div className="flex flex-col items-center gap-3">
            <div
              onClick={() => fileRef.current?.click()}
              data-testid="photo-upload-box"
              className="relative w-40 h-40 kop-chamfer border-2 border-dashed border-red-500/60 bg-slate-900 flex items-center justify-center cursor-pointer overflow-hidden hover:border-red-500"
            >
              {photo ? <img src={photo} alt="preview" className="w-full h-full object-cover" /> : (
                <div className="text-center text-slate-500">
                  <Camera className="w-8 h-8 mx-auto mb-1" />
                  <div className="text-xs font-display uppercase tracking-widest">Enviar Foto</div>
                </div>
              )}
            </div>
            <input ref={fileRef} data-testid="photo-input" type="file" accept="image/*" onChange={onFile} className="hidden" />
          </div>

          <div>
            <label className="text-xs font-display uppercase tracking-widest text-slate-400">Nome Completo *</label>
            <input data-testid="name-input" value={name} onChange={e => setName(e.target.value)} className="w-full mt-1 bg-slate-900 border border-slate-700 focus:border-red-500 px-3 py-2 text-white outline-none" />
          </div>

          <div>
            <label className="text-xs font-display uppercase tracking-widest text-slate-400">Apelido</label>
            <input data-testid="nickname-input" value={nickname} onChange={e => setNickname(e.target.value)} className="w-full mt-1 bg-slate-900 border border-slate-700 focus:border-red-500 px-3 py-2 text-white outline-none" />
          </div>

          <div>
            <label className="text-xs font-display uppercase tracking-widest text-slate-400">Nível *</label>
            <div className="grid grid-cols-3 gap-2 mt-1">
              {LEVELS.map(l => (
                <button
                  key={l}
                  type="button"
                  data-testid={`level-${l}`}
                  onClick={() => setLevel(l)}
                  className={`kop-chamfer border-2 px-2 py-2 font-display uppercase text-xs sm:text-sm tracking-widest transition ${level === l ? "border-red-500 bg-red-500/20 text-red-400" : "border-slate-700 text-slate-400 hover:border-slate-500"}`}
                >{l}</button>
              ))}
            </div>
          </div>

          <div>
            <label className="text-xs font-display uppercase tracking-widest text-slate-400">WhatsApp (opcional)</label>
            <input data-testid="whatsapp-input" value={whatsapp} onChange={e => setWhatsapp(e.target.value)} className="w-full mt-1 bg-slate-900 border border-slate-700 focus:border-red-500 px-3 py-2 text-white outline-none" />
          </div>
          <div>
            <label className="text-xs font-display uppercase tracking-widest text-slate-400">Observação (opcional)</label>
            <textarea data-testid="notes-input" value={notes} onChange={e => setNotes(e.target.value)} rows={2} className="w-full mt-1 bg-slate-900 border border-slate-700 focus:border-red-500 px-3 py-2 text-white outline-none" />
          </div>

          <button
            type="submit"
            data-testid="submit-register-btn"
            disabled={submitting}
            className="w-full kop-chamfer bg-red-600 hover:bg-red-500 disabled:opacity-50 text-white font-arcade uppercase tracking-widest py-3 kop-glow-red transition"
          >
            {submitting ? "Enviando..." : "▶ Confirmar Inscrição"}
          </button>
        </form>
      </div>
    </div>
  );
}

// --- STAGE 4: Submitted (waiting for the organizer's approval) ---
function SubmittedScreen({ player }) {
  return (
    <div className="min-h-screen flex items-center justify-center px-4 py-10 animate-kop-slam">
      <div className="max-w-md w-full text-center">
        <div className="font-arcade text-cyan-300 text-sm tracking-widest uppercase mb-2 animate-kop-flicker">
          ✓ Inscrição Enviada
        </div>
        <h1 className="font-arcade text-3xl text-red-500 mb-6 animate-kop-pulse">AGUARDANDO APROVAÇÃO</h1>
        <div className="flex justify-center mb-4">
          <PlayerCard player={player} size="xl" testId="confirmed-card" />
        </div>
        <div className="font-display text-2xl text-white uppercase mt-2">{player.name}</div>
        {player.nickname && <div className="text-cyan-300 uppercase text-sm tracking-widest">"{player.nickname}"</div>}
        <div className="mt-4 inline-block border border-yellow-500/60 text-yellow-400 px-3 py-1 font-display text-xs uppercase tracking-widest">
          STATUS: PENDENTE
        </div>
        <div className="mt-6 text-slate-500 text-sm">
          O organizador vai analisar sua inscrição. A foto e os dados só ficam públicos
          depois da confirmação.
        </div>
      </div>
    </div>
  );
}

// --- Root ---
export default function Register() {
  const [stage, setStage] = useState("start"); // start | transition | form | done
  const [muted, setMuted] = useState(isMuted());
  const [confirmed, setConfirmed] = useState(null);

  useEffect(() => {
    // preload transition
  }, []);

  const handleStart = () => {
    sfx.confirm();
    setStage("transition");
    setTimeout(() => setStage("form"), 900);
  };

  if (stage === "start") return <StartScreen onStart={handleStart} muted={muted} setMuted={setMuted} />;
  if (stage === "transition") return <Transition />;
  if (stage === "done" && confirmed) return <SubmittedScreen player={confirmed} />;
  return (
    <RegistrationForm onSubmitted={(p) => { setConfirmed(p); setStage("done"); }} />
  );
}
