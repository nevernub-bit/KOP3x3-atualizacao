# KINGS OF PAINTBALL — KOP 3x3 (PRD)

## Original Problem Statement
Aplicativo web/mobile responsivo para organização de campeonato de paintball 3v3
com forte estética arcade fighting game (KOF). Nomes reais dos jogadores + fotos.
Nomes de equipes do universo KOF.

## Architecture
- Backend: FastAPI + MongoDB (Motor), JWT (HS256, PyJWT), bcrypt.
- Frontend: React 19 + Tailwind + shadcn primitives, react-router-dom v7, sonner.
- Photos: base64 stored in MongoDB (client-side compressed 800px JPEG @ .82).
- Sound: shared Web Audio library (no assets), global mute + volume em localStorage.
- All routes /api-prefixed. Auth via Bearer token em localStorage.

## Personas
- **Jogador** (público): inscreve-se, vê equipe, tabela, resultados, stats.
- **Organizador/Admin** (nevernub@gmail.com): CRUD, sorteio, cronômetro,
  registro de eliminações, bloqueio, MVP, set-winner (playoffs), reset.

## Official Rules (v3 — Feb 2026)
- 10 equipes × 3 jogadores. Grupos A/B (5 cada). 20 partidas round-robin.
- **Vitória** só acontece quando os **3 adversários são eliminados** (wipe total).
- **Empate** quando o cronômetro chega a 00:00 e ainda há jogador vivo nos DOIS lados
  — independentemente da contagem de eliminações.
- **Pontuação (v2 — Nov 2026)**:
  - Cada eliminação vale **1 ponto** para a equipe que eliminou.
  - **+2** de bônus apenas com vencedor único (3 adversários eliminados): **5 pts**.
  - Empate mantém os pontos das eliminações (2×1 = 2×1; 2×2 = 2×2; nunca 5×5).
  - Perdedor mantém os pontos das eliminações (3×1 = 5×1; 3×2 = 5×2).
- **PERFECT**: vitória 3×0 sem baixa própria; só critério de desempate, sem pontos extras.
- **Desempate**: pontos → vitórias → saldo → PERFECTs → confronto direto.
  - 2 equipes empatadas: resultado direto entre elas.
  - 3+ equipes empatadas: mini-tabela de pontos apenas nos jogos entre as empatadas.
  - Se a mini-tabela continuar empatada, o sistema **não inventa** critério: marca
    `tiebreak_pending` e aguarda a definição dos critérios 6/7 pela organização.
- **Rollback do recálculo**: admin pode restaurar um snapshot de recálculo por partida,
  com confirmação; a operação arquiva o estado anterior e é idempotente.
- **W.O.**: 5×0 administrativo, sem eliminações fictícias; não conta como PERFECT de campo.
- Cronômetro oficial: 5 min padrão (mín. 5s), START/PAUSE/RESUME/END, auto-end.
- **Registro simplificado**: apenas `eliminated_id`. Killer não é rastreado.

## Implemented Versions
### v1 — MVP completo (inscrição, sorteio, grupos, playoffs, podium, telão).
### v1.5 — Tela arcade PRESS START pública em /register.
### v2 — Motor de partida (timer, eliminações individuais, empates, PERFECT overlay, biblioteca de som).
### v3 — Regras oficiais (atual)
- Vitória só por wipe total (compute_result Rule A).
- Empate por tempo com jogadores vivos (Rule B), independente de elim count.
- Pontuação v2: 1 por eliminação + 2 de bônus; empate mantém eliminações.
- Campo "eliminado por" removido da UI + backend.
- Stats individuais: matches, V/E/D, times_eliminated, perfects, survivals
  (ranking por team_wins → perfects → survivals → -times_eliminated).
- Startup só preenche campos estruturais ausentes; resultados históricos não
  são recalculados. Recálculo é ação explícita do admin, com preview e backup.
- Perfil RANGER, regras públicas versionadas, banner e penalidades com auditoria.
- MatchDetail e Live com overlay ELIMINATED! (só vítima) e DRAW/WINNER/PERFECT.

## Test Coverage
- Iteration 1: 32/32 backend PASS.
- Iteration 2: 22/22 backend PASS (motor de partida v2).
- Iteration 3: **18/18 backend PASS** (regras oficiais v3).
- Arquivo autoritativo: `/app/backend/tests/test_tournament_v3.py`.

## Backlog (P1)
- Replay Cinemático (log de eliminações passo a passo pós-partida).
- Impressão/export PDF dos relatórios.
- QR code do link público no painel admin.
- Volume slider por categoria de som.
- Modularizar server.py (>1000 linhas).

## Backlog (P2)
- Perfil individual com histórico completo.
- Endpoint opcional para purgar jogadores no reset.
- Modo espectador em tempo real com atalhos de teclado.
