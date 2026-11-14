import { jsPDF } from "jspdf";

/**
 * Official draw record.
 *
 * Everything below is rendered from the objects the API just returned
 * (/tournament, /teams, /players, /matches): the document is a transcript of the
 * saved draw, never a snapshot of the animation on screen. Nothing is written
 * back and the generator never calls the draw endpoint.
 */

const INK = [11, 13, 18];
const RED = [255, 46, 76];
const GOLD = [234, 179, 8];
const CYAN = [0, 229, 255];
const GREY = [125, 134, 148];
const PAPER = [26, 31, 45];
const TEXT = [238, 242, 247];
const MUTED = [205, 212, 222];

const pad2 = (n) => String(n).padStart(2, "0");

const asDate = (value) => {
  if (!value) return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
};

// The official record always speaks in the event's time zone, so a PDF made on
// a laptop abroad still carries the same date and time as one made on site.
const TIME_ZONE = "America/Sao_Paulo";

const fmtDate = (value) => {
  const d = asDate(value);
  return d
    ? d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric", timeZone: TIME_ZONE })
    : "-";
};

const fmtTime = (value) => {
  const d = asDate(value);
  return d
    ? d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", timeZone: TIME_ZONE })
    : "-";
};

/** Dashes and fancy spaces are outside the PDF standard font set. */
const safe = (s) => String(s ?? "").replace(/[\u2014\u2013]/g, "-").replace(/\u00a0/g, " ");

/**
 * Moment the current draw was persisted. The draw recreates the group matches,
 * so the oldest `created_at` among them marks the saved draw; when there is no
 * match to read the caller falls back to the emission time.
 */
export function drawnAt({ matches = [] } = {}) {
  const stamps = matches
    .map((m) => asDate(m?.created_at))
    .filter(Boolean)
    .map((d) => d.getTime());
  if (!stamps.length) return null;
  return new Date(Math.min(...stamps));
}

/** A record only exists when the draw is saved and has players in teams. */
export function drawIsRecordable({ tournament, teams = [], players = [] } = {}) {
  if (!tournament?.draw_done) return false;
  const known = new Set(players.map((p) => p.id));
  return teams.some((t) => (t?.players || []).some((pid) => known.has(pid)));
}

/**
 * @param {object} input
 * @param {object} input.tournament persisted tournament document
 * @param {Array}  input.teams      persisted teams (with player ids)
 * @param {Array}  input.players    persisted confirmed players
 * @param {Array}  input.matches    persisted matches (used only to date the draw)
 * @param {string} input.logo       data URL of the KOP logo (optional)
 * @param {string} input.scope      "TEST" when the record comes from the simulation
 * @returns {{ blob: Blob, filename: string }}
 */
export function buildDrawPdf({ tournament, teams = [], players = [], matches = [], logo = "", scope = "REAL" } = {}) {
  const byId = new Map(players.map((p) => [p.id, p]));
  const ordered = teams
    .filter((t) => (t?.players || []).length > 0)
    .sort((a, b) => (a.order ?? 0) - (b.order ?? 0));

  const perTeam = Number(tournament?.players_per_team || ordered[0]?.players?.length || 0);
  const totalPlayers = ordered.reduce((n, t) => n + (t.players || []).length, 0);
  const savedAt = drawnAt({ matches });
  const emittedAt = new Date();

  const doc = new jsPDF({ unit: "mm", format: "a4", compress: true });
  const W = doc.internal.pageSize.getWidth();
  const H = doc.internal.pageSize.getHeight();
  const M = 14;
  const CONTENT = W - M * 2;
  // Room kept free at the bottom for the "sorteio concluido" band + footer.
  const BOTTOM = H - 44;

  const fill = ([r, g, b]) => doc.setFillColor(r, g, b);
  const ink = ([r, g, b]) => doc.setTextColor(r, g, b);

  let pageIndex = 1;

  /** Cuts a single line of text with an ellipsis when it is too wide. */
  const clip = (text, width) => {
    const value = safe(text);
    if (doc.getTextWidth(value) <= width) return value;
    let cut = value;
    while (cut.length > 1 && doc.getTextWidth(`${cut}...`) > width) cut = cut.slice(0, -1);
    return `${cut}...`;
  };

  const header = (compact = false) => {
    const h = compact ? 20 : 42;
    fill(INK); doc.rect(0, 0, W, h, "F");
    fill(RED); doc.rect(0, h, W, 1.4, "F");
    fill(RED); doc.rect(0, 0, 3, h, "F");

    let left = M;
    if (logo) {
      const size = compact ? 12 : 21;
      try {
        doc.addImage(logo, "PNG", M, (h - size) / 2, size, size);
        left = M + size + 5;
      } catch { /* the logo is decorative: the text identity still renders */ }
    }

    ink([255, 255, 255]);
    doc.setFont("helvetica", "bold");
    doc.setFontSize(compact ? 9 : 14);
    doc.text(safe("KINGS OF PAINTBALL"), left, compact ? h / 2 + 0.5 : 15);
    doc.setFontSize(compact ? 6.5 : 8);
    ink(compact ? GREY : RED);
    doc.text(safe("KOP 3x3"), left, compact ? h / 2 + 4.6 : 20);

    if (compact) {
      ink(GREY);
      doc.setFont("helvetica", "normal");
      doc.setFontSize(6.5);
      doc.text(safe("RESULTADO OFICIAL DO SORTEIO"), W - M, h / 2 + 2, { align: "right" });
    } else {
      ink([255, 255, 255]);
      doc.setFont("helvetica", "bold");
      doc.setFontSize(17);
      doc.text(safe("RESULTADO OFICIAL DO SORTEIO"), left, 31);
      ink(GREY);
      doc.setFont("helvetica", "normal");
      doc.setFontSize(7.2);
      doc.text(safe("KOP 3x3 - KINGS OF PAINTBALL"), left, 36.5);
    }
  };

  const footer = (concluded = false) => {
    if (concluded) {
      const bandY = H - 40;
      fill(INK); doc.rect(M, bandY, CONTENT, 12, "F");
      fill(GOLD); doc.rect(M, bandY, 2.2, 12, "F");
      ink(GOLD);
      doc.setFont("helvetica", "bold");
      doc.setFontSize(9.5);
      doc.text(safe("SORTEIO CONCLUIDO"), M + 6, bandY + 5.2);
      ink(GREY);
      doc.setFont("helvetica", "normal");
      doc.setFontSize(6.6);
      doc.text(safe("Equipes e jogadores acima refletem o resultado gravado no sistema."), M + 6, bandY + 9.4);
    }
    doc.setDrawColor(58, 64, 78);
    doc.setLineWidth(0.2);
    doc.line(M, H - 12, W - M, H - 12);
    ink(GREY);
    doc.setFont("helvetica", "normal");
    doc.setFontSize(6.4);
    doc.text(safe("KOP 3x3 - Kings of Paintball  |  Documento oficial do sorteio de equipes"), M, H - 8);
    doc.text(safe(`pagina ${pageIndex}`), W - M, H - 8, { align: "right" });
  };

  header(false);
  let y = 52;

  // ---------- identification: event line + one strip of key figures ----------
  const eventName = safe(tournament?.name || "KOP 3x3 - KINGS OF PAINTBALL");
  fill(PAPER); doc.rect(M, y, CONTENT, 11, "F");
  fill(RED); doc.rect(M, y, 1.6, 11, "F");
  ink(GREY);
  doc.setFont("helvetica", "normal");
  doc.setFontSize(6.4);
  doc.text(safe("EVENTO"), M + 5, y + 4);
  ink(TEXT);
  doc.setFont("helvetica", "bold");
  doc.setFontSize(9.4);
  doc.text(clip(eventName, CONTENT - 12), M + 5, y + 8.4);
  y += 11 + 3.5;

  const stats = [
    ["DATA", savedAt ? fmtDate(savedAt) : "nao registrada"],
    ["HORARIO (BRT)", savedAt ? fmtTime(savedAt) : "-"],
    ["EQUIPES", String(ordered.length)],
    ["POR EQUIPE", String(perTeam)],
    ["TOTAL", String(totalPlayers)],
    ["EMITIDO EM", `${fmtDate(emittedAt)} ${fmtTime(emittedAt)}`],
  ];
  const gap = 3;
  const boxW = (CONTENT - gap * (stats.length - 1)) / stats.length;
  stats.forEach(([label, value], i) => {
    const x = M + i * (boxW + gap);
    fill(PAPER); doc.rect(x, y, boxW, 12.5, "F");
    ink(CYAN);
    doc.setFont("helvetica", "normal");
    doc.setFontSize(5.9);
    doc.text(clip(label, boxW - 4), x + 2, y + 4.2);
    ink(TEXT);
    doc.setFont("helvetica", "bold");
    doc.setFontSize(8.2);
    doc.text(clip(value, boxW - 4), x + 2, y + 9.6);
  });
  y += 12.5 + 5.5;

  if (scope === "TEST") {
    fill(GOLD); doc.rect(M, y, CONTENT, 6.5, "F");
    ink([18, 18, 18]);
    doc.setFont("helvetica", "bold");
    doc.setFontSize(7);
    doc.text(safe("MODO TESTE - DADOS FICTICIOS (NAO E O EVENTO REAL)"), M + 3, y + 4.3);
    y += 10;
  }

  // ---------- teams ----------
  ink(RED);
  doc.setFont("helvetica", "bold");
  doc.setFontSize(10.5);
  doc.text(safe("EQUIPES FORMADAS"), M, y + 2);
  doc.setDrawColor(255, 46, 76);
  doc.setLineWidth(0.4);
  doc.line(M, y + 4, M + 32, y + 4);
  y += 9;

  // Both columns start at the same height; only a new page resets to the top.
  const teamsTop = y;
  const cols = ordered.length > 4 ? 2 : 1;
  const gapX = 6;
  const colW = (CONTENT - gapX * (cols - 1)) / cols;
  let col = 0;
  let cursor = teamsTop;

  const nextColumn = () => {
    col += 1;
    if (col >= cols) {
      footer();
      doc.addPage();
      pageIndex += 1;
      header(true);
      col = 0;
      cursor = 52;
      return;
    }
    cursor = teamsTop;
  };

  ordered.forEach((team, i) => {
    const roster = (team.players || []).map((pid) => byId.get(pid)).filter(Boolean);
    const blockH = 9.5 + Math.max(1, roster.length) * 5.4 + 1.5;

    if (cursor + blockH > BOTTOM) nextColumn();

    const x = M + col * (colW + gapX);
    fill(PAPER); doc.rect(x, cursor - 3.5, colW, blockH, "F");
    fill(i % 2 ? CYAN : RED); doc.rect(x, cursor - 3.5, 1.4, blockH, "F");

    ink(TEXT);
    doc.setFont("helvetica", "bold");
    doc.setFontSize(cols === 2 ? 8.2 : 10);
    const teamNo = pad2(team.order != null ? team.order + 1 : i + 1);
    doc.text(clip(`TEAM ${teamNo} - ${team.name || ""}`, colW - 8), x + 4.5, cursor + 1.4);

    doc.setFont("helvetica", "normal");
    doc.setFontSize(cols === 2 ? 7.8 : 8.4);
    ink(MUTED);
    roster.forEach((p, k) => {
      const name = p.nickname ? `${p.name} "${p.nickname}"` : p.name;
      doc.text(clip(`${k + 1}. ${name}`, colW - 9), x + 4.5, cursor + 6.6 + k * 5.4);
    });
    if (!roster.length) {
      ink(GREY);
      doc.text(safe("sem jogadores"), x + 4.5, cursor + 6.6);
    }

    cursor += blockH + 2.2;
  });

  footer(true);

  const stamp = savedAt || emittedAt;
  const day = fmtDate(stamp).replace(/\//g, "");
  const time = fmtTime(stamp).replace(/[^0-9]/g, "");
  const filename = `KOP-3x3-sorteio-${day}-${time}${scope === "TEST" ? "-teste" : ""}.pdf`;
  return { blob: doc.output("blob"), filename };
}

/** Downloads the PDF blob (desktop and mobile browsers). */
export function downloadPdf(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

/** True when the device can share an actual file (mostly phones). */
export function canSharePdf(blob, filename) {
  try {
    const file = new File([blob], filename, { type: "application/pdf" });
    return !!(navigator.canShare && navigator.canShare({ files: [file] }));
  } catch {
    return false;
  }
}

/** Shares the PDF through the system sheet; resolves false when unavailable. */
export async function sharePdf(blob, filename, title) {
  try {
    const file = new File([blob], filename, { type: "application/pdf" });
    if (!navigator.canShare || !navigator.canShare({ files: [file] })) return false;
    await navigator.share({ files: [file], title, text: title });
    return true;
  } catch {
    return false;
  }
}

/** Reads the KOP logo shipped in `public/` as a data URL for the PDF header. */
export function loadKopLogo() {
  return fetch(`${process.env.PUBLIC_URL || ""}/kop-logo.png`, { cache: "force-cache" })
    .then((res) => (res.ok ? res.blob() : null))
    .then((blob) => new Promise((resolve) => {
      if (!blob) return resolve("");
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ""));
      reader.onerror = () => resolve("");
      reader.readAsDataURL(blob);
    }))
    .catch(() => "");
}
