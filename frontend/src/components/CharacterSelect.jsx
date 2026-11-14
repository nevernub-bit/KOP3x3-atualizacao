import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

const LEVEL_STYLES = {
  "INICIANTE": "bg-blue-500/25 text-blue-200 border-blue-400/70",
  "INTERMEDIÁRIO": "bg-amber-500/25 text-amber-200 border-amber-400/70",
  "PROFISSIONAL": "bg-red-500/25 text-red-200 border-red-400/70",
};

const pad2 = (n) => String(n).padStart(2, "0");

/**
 * One "character" card. Pure presentation: it only reads the player object
 * that already exists in the API payload — never writes anything.
 */
export function SelectCard({ player, index, state = "idle", rounded = false, testId, style, nameSize, metaSize }) {
  const highlight = state === "highlight";
  const selected = state === "selected";
  const dimmed = state === "dimmed";

  const frame = selected
    ? "border-yellow-400 kop-glow-gold scale-[1.04] z-20"
    : highlight
      ? "border-red-400 animate-kop-select scale-[1.03] z-10"
      : "border-slate-700/80";

  return (
    <div
      data-testid={testId}
      data-state={state}
      className={`relative kop-chamfer border-2 overflow-hidden bg-slate-950 transition-all duration-150 ${rounded ? "rounded-md" : ""} ${frame} ${dimmed ? "opacity-40 saturate-50" : ""}`}
      style={{ aspectRatio: style?.width && style?.height ? undefined : "3 / 4", ...style }}
    >
      {player?.photo ? (
        <img
          src={player.photo}
          alt={player?.name || "Jogador"}
          loading="lazy"
          decoding="async"
          className="absolute inset-0 h-full w-full object-cover"
        />
      ) : (
        <div className="absolute inset-0 flex items-center justify-center bg-slate-800 text-slate-500 font-arcade text-3xl">?</div>
      )}

      <div className="absolute inset-0 bg-gradient-to-t from-black via-black/45 to-transparent" />

      <div
        className="absolute top-1 left-1 font-mono-num text-[9px] sm:text-[10px] tracking-widest text-white/80 bg-black/70 px-1 py-0.5 border border-white/10"
        style={metaSize ? { fontSize: metaSize, padding: "0 2px", lineHeight: 1.3 } : undefined}
      >
        P{pad2((index ?? 0) + 1)}
      </div>

      {player?.level && (
        <div className={`absolute top-1 right-1 text-[8px] sm:text-[9px] font-bold uppercase tracking-widest px-1 py-0.5 border ${LEVEL_STYLES[player.level] || "bg-slate-700/40 text-slate-200 border-slate-500/60"}`}>
          {player.level.slice(0, 3)}
        </div>
      )}

      <div className="absolute bottom-0 inset-x-0 px-1.5 pb-1.5 pt-3">
        <div
          className="font-display text-[11px] sm:text-sm leading-tight text-white uppercase truncate"
          style={nameSize ? { fontSize: nameSize, lineHeight: 1.05 } : undefined}
        >
          {player?.name || "—"}
        </div>
        {player?.nickname && (
          <div
            className="font-mono-num text-[8px] sm:text-[9px] text-cyan-300 uppercase tracking-widest truncate"
            style={metaSize ? { fontSize: metaSize, lineHeight: 1.15 } : undefined}
          >
            "{player.nickname}"
          </div>
        )}
      </div>

      {highlight && (
        <>
          <div className="absolute inset-0 bg-red-500/10 mix-blend-screen pointer-events-none" />
          <div className="absolute inset-x-0 h-1/3 animate-kop-scan bg-gradient-to-b from-transparent via-red-400/40 to-transparent pointer-events-none" />
        </>
      )}

      {selected && (
        <div className="absolute inset-0 border-2 border-yellow-300/70 pointer-events-none" />
      )}
    </div>
  );
}

/**
 * Home band: a continuous right-to-left marquee of the registered players,
 * repeated so the loop has no visible restart. An independent random selector
 * highlights one player at a time wherever that copy happens to be.
 *
 * Purely visual: reads existing player fields, writes nothing, and has no
 * connection to the official draw.
 */
export function PlayerSelectStrip({ players = [], className = "" }) {
  const trackRef = useRef(null);
  // Random offset into the loop, so returning visitors do not all land on the
  // same frame. The animation is paused until it is applied (see below).
  const warmup = useRef(Math.random() * 30);
  const lastPick = useRef(-1);
  // The chosen player is random; `slot` only says which repeated copy is on
  // screen so a single card is highlighted instead of every copy.
  const [focus, setFocus] = useState({ slot: -1, name: "" });
  const [running, setRunning] = useState(false);

  // The marquee starts paused on a random offset and only runs once the CSS
  // animation is really applied, so the strip never snaps back to frame zero.
  useEffect(() => {
    if (players.length === 0) return;
    let first = 0;
    let second = 0;
    first = requestAnimationFrame(() => {
      second = requestAnimationFrame(() => {
        const name = trackRef.current && getComputedStyle(trackRef.current).animationName;
        if (name && name !== "none") setRunning(true);
      });
    });
    return () => { cancelAnimationFrame(first); cancelAnimationFrame(second); };
  }, [players]);

  // Independent random selector: any registered player can be picked, never
  // the same one twice in a row. It does not look at the center of the band,
  // never moves the strip and never repositions the card.
  useEffect(() => {
    if (players.length === 0) return;
    let timer = 0;
    let cancelled = false;

    const pick = () => {
      if (cancelled) return;
      let index = Math.floor(Math.random() * players.length);
      if (players.length > 1 && index === lastPick.current) {
        index = (index + 1 + Math.floor(Math.random() * (players.length - 1))) % players.length;
      }
      lastPick.current = index;

      // Any player can be drawn. The repeated copies are only a loop detail, so
      // one of the visible copies is picked at random — the highlight is not
      // tied to the center of the band.
      let slot = index;
      const wrap = trackRef.current?.parentElement;
      if (wrap) {
        const box = wrap.getBoundingClientRect();
        const center = box.left + box.width / 2;
        const copiesOfPlayer = [];
        wrap.querySelectorAll("[data-slot-index]").forEach((el) => {
          const raw = Number(el.getAttribute("data-slot-index"));
          if (raw % players.length !== index) return;
          const rect = el.getBoundingClientRect();
          copiesOfPlayer.push({ raw, middle: rect.left + rect.width / 2 });
        });
        const visible = copiesOfPlayer.filter((c) => c.middle > box.left + 24 && c.middle < box.right - 24);
        if (visible.length) {
          slot = visible[Math.floor(Math.random() * visible.length)].raw;
        } else if (copiesOfPlayer.length) {
          copiesOfPlayer.sort((a, b) => Math.abs(a.middle - center) - Math.abs(b.middle - center));
          slot = copiesOfPlayer[0].raw;
        }
      }

      setFocus({ slot, name: (players[index].name || "").split(" ")[0] });
      const hold = 1800 + Math.random() * 1600;
      const gap = 300 + Math.random() * 500;
      timer = window.setTimeout(pick, hold + gap);
    };

    timer = window.setTimeout(pick, 900);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [players]);

  if (players.length === 0) return null;

  // About half the previous speed: one full pass now takes ~2.6s per player.
  const duration = Math.max(20, players.length * 2.6);
  // Enough copies per half to fill the band on any screen. Computed up front
  // (never after the first paint), so the track width — and therefore the
  // -50% loop point — never changes while the strip is moving.
  const halfCopies = Math.max(1, Math.ceil(1400 / (players.length * 64)));
  const blocks = Array.from({ length: halfCopies * 2 }, (_, k) => k);

  return (
    <div data-testid="player-select-strip" className={`relative ${className}`}>
      <div className="kop-mask-x overflow-hidden h-[128px] sm:h-[168px] md:h-[176px] flex items-center">
        <div
          ref={trackRef}
          className={`flex w-max animate-kop-marquee ${running ? "is-running" : ""}`}
          style={{ animationDuration: `${duration}s`, animationDelay: `-${warmup.current}s` }}
        >
          {blocks.map((copy) => (
            <div
              key={copy}
              data-marquee-block
              aria-hidden={copy === 0 ? undefined : "true"}
              className="flex items-center gap-2 sm:gap-2.5 pr-2 sm:pr-2.5"
            >
              {players.map((p, i) => {
                const slot = copy * players.length + i;
                const selected = focus.slot === slot;
                return (
                  <div
                    key={`${copy}-${p.id}`}
                    data-testid={`player-slot-${copy}-${p.id}`}
                    data-slot-index={slot}
                    className="relative shrink-0 w-[40px] h-[56px] sm:w-[48px] sm:h-[66px] md:w-[56px] md:h-[74px]"
                  >
                    <div
                      data-selected={selected ? "true" : "false"}
                      className={`absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 overflow-hidden kop-chamfer border-2 bg-slate-950 transition-all duration-300 ease-out ${selected
                        ? "z-20 border-yellow-400 kop-glow-gold w-[90px] h-[118px] sm:w-[106px] sm:h-[138px] md:w-[120px] md:h-[152px] opacity-100 grayscale-0"
                        : "z-0 w-full h-full border-slate-700/70 opacity-80 grayscale-[45%]"}`}
                    >
                      {p.photo ? (
                        <img
                          src={p.photo}
                          alt={p.name || "Jogador"}
                          loading="lazy"
                          decoding="async"
                          className="absolute inset-0 h-full w-full object-cover"
                        />
                      ) : (
                        <div className="absolute inset-0 flex items-center justify-center bg-slate-800 text-slate-500 font-arcade text-base">?</div>
                      )}

                      <div className="absolute inset-0 bg-gradient-to-t from-black/90 via-black/15 to-transparent" />

                      <div className="absolute top-0.5 left-0.5 font-mono-num text-[7px] sm:text-[8px] tracking-widest text-white/85 bg-black/70 px-1 border border-white/10">
                        P{pad2(i + 1)}
                      </div>

                      {selected && (
                        <>
                          <div className="absolute inset-0 border border-yellow-300/60 pointer-events-none" />
                          <div className="pointer-events-none absolute inset-x-0 h-1/3 animate-kop-scan bg-gradient-to-b from-transparent via-red-400/35 to-transparent" />
                          <div className="absolute inset-x-0 bottom-0 px-1 pb-1 pt-4">
                            <div className="font-display text-[10px] sm:text-xs leading-tight text-white uppercase truncate">
                              {selected ? focus.name || (p.name || "—").split(" ")[0] : (p.name || "—").split(" ")[0]}
                            </div>
                            {p.nickname && (
                              <div className="font-mono-num text-[8px] sm:text-[9px] text-cyan-300 uppercase tracking-widest truncate">
                                "{p.nickname}"
                              </div>
                            )}
                            {p.level && (
                              <div className="mt-0.5 inline-block text-[7px] font-bold uppercase tracking-widest px-1 border border-white/20 bg-black/60 text-slate-200">
                                {p.level.slice(0, 3)}
                              </div>
                            )}
                          </div>
                        </>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/**
 * Best fit for `n` cards of aspect 3/4 inside a `W × H` box: tries every column
 * count and keeps the one with the largest card that still fits both axes.
 */
export function fitGrid(n, W, H, gap = 8, maxCardWidth = 190) {
  const empty = { cols: 1, rows: 1, cardW: 0, cardH: 0 };
  if (!n || W <= 0 || H <= 0) return empty;
  let best = empty;
  let bestArea = 0;
  for (let cols = 1; cols <= n; cols++) {
    const rows = Math.ceil(n / cols);
    const cellW = (W - gap * (cols - 1)) / cols;
    const cellH = (H - gap * (rows - 1)) / rows;
    if (cellW <= 0 || cellH <= 0) continue;
    const cardW = Math.min(cellW, cellH * (3 / 4), maxCardWidth);
    const cardH = cardW * (4 / 3);
    if (cardH * rows + gap * (rows - 1) > H + 0.5) continue;
    const area = cardW * cardH;
    if (area > bestArea) { bestArea = area; best = { cols, rows, cardW, cardH }; }
  }
  return best;
}

/**
 * Arcade "character select" wall: every participant visible at once.
 *
 * The card size is computed from the box it lives in, so 8 and 30 players both
 * fill the screen without a vertical scrollbar. Only the highlighted card grows,
 * in place, and it can never push the others out of the box.
 */
export function PlayerSelectWall({
  players = [],
  highlightId = null,
  selectedId = null,
  revealCount = null,
  gap = 8,
  maxCardWidth = 190,
  className = "",
  testId = "player-select-wall",
}) {
  const boxRef = useRef(null);
  const [box, setBox] = useState({ w: 0, h: 0 });

  useLayoutEffect(() => {
    const el = boxRef.current;
    if (!el) return undefined;
    const measure = () => {
      const rect = el.getBoundingClientRect();
      setBox({ w: rect.width, h: rect.height });
    };
    measure();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", measure);
      return () => window.removeEventListener("resize", measure);
    }
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
    // Re-observes when the roster arrives: the first render happens before the
    // players load, when the measured box does not exist yet.
  }, [players.length]);

  const layout = useMemo(
    () => fitGrid(players.length, box.w, box.h, gap, maxCardWidth),
    [players.length, box.w, box.h, gap, maxCardWidth],
  );

  if (!players.length) {
    return (
      <div className="text-center py-10 font-display uppercase tracking-[0.4em] text-slate-500 text-xs sm:text-sm">
        Aguardando inscrições…
      </div>
    );
  }

  const ready = layout.cardW > 0;
  const nameSize = Math.max(7.5, Math.min(13, layout.cardW * 0.125));
  const metaSize = Math.max(6, Math.min(9.5, layout.cardW * 0.085));

  return (
    <div
      ref={boxRef}
      data-testid={testId}
      data-cols={layout.cols}
      className={`w-full h-full flex items-center justify-center overflow-hidden ${className}`}
    >
      {ready && (
        <div
          className="flex flex-wrap justify-center content-center"
          style={{ gap, maxWidth: layout.cols * (layout.cardW + gap) }}
        >
          {players.map((p, i) => {
            const shown = revealCount == null || i < revealCount;
            const state = selectedId === p.id ? "selected" : highlightId === p.id ? "highlight" : shown ? "idle" : "dimmed";
            return (
              <SelectCard
                key={p.id}
                player={p}
                index={i}
                state={state}
                testId={`wall-card-${p.id}`}
                style={{ width: layout.cardW, height: layout.cardH }}
                nameSize={nameSize}
                metaSize={metaSize}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}

/**
 * Responsive roster. Works with any number of registered players — no fixed
 * layout and no placeholder players are ever created.
 */
export function PlayerRoster({
  players = [],
  highlightId = null,
  selectedId = null,
  revealCount = null,
  dense = false,
  className = "",
}) {
  if (!players.length) {
    return (
      <div className="text-center py-16 font-display uppercase tracking-[0.4em] text-slate-500 text-xs sm:text-sm">
        Aguardando inscrições…
      </div>
    );
  }

  const grid = dense
    ? "grid-cols-3 xs:grid-cols-4 sm:grid-cols-5 md:grid-cols-6 lg:grid-cols-8 xl:grid-cols-10"
    : "grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6";

  return (
    <div className={`grid ${grid} gap-2 sm:gap-3 ${className}`}>
      {players.map((p, i) => {
        const shown = revealCount == null || i < revealCount;
        const state =
          selectedId === p.id
            ? "selected"
            : highlightId === p.id
              ? "highlight"
              : shown
                ? "idle"
                : "dimmed";
        return <SelectCard key={p.id} player={p} index={i} state={state} testId={`player-card-${p.id}`} />;
      })}
    </div>
  );
}
