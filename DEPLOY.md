# Deploy externo — KOP 3x3

Este documento descreve como publicar a aplicação **fora do Freebuff**. Nada aqui
foi executado: nenhum deploy, nenhuma migração de dados e nenhuma alteração de
banco foi feita.

## Arquitetura

```
Navegador
   │  HTTPS
   ▼
Frontend estático (Cloudflare Pages / Netlify / Vercel)
   │  fetch https://<api>/api/...  (CORS)
   ▼
Backend FastAPI + Uvicorn (Docker, ex.: Render / Railway / Fly.io / VPS)
   │  MONGO_URL (TLS)
   ▼
MongoDB (cluster existente — sem migração)
```

Duas unidades de deploy, porque são duas tecnologias diferentes:

| Parte | O que é | Precisa de |
| --- | --- | --- |
| `frontend/` | build estático do CRA (`yarn build` → `build/`) | host de estático + SPA rewrite |
| `backend/` | processo Python de longa duração (`uvicorn server:app`) | host de container/processo Python |

O backend **não** pode ser publicado em host estático nem em runtime serverless
que não rode um processo Python contínuo: ele mantém conexão com o MongoDB via
Motor e o rate limit em memória do processo.

## Arquivos de deploy neste repositório

- `backend/Dockerfile` — imagem do backend (Python 3.11, Uvicorn em `$PORT`).
- `backend/.dockerignore` — mantém `.env`, testes e caches fora da imagem.
- `backend/.env.example` — nomes das variáveis exigidas pelo backend.
- `frontend/.env.example` — variável de build do frontend.
- `frontend/public/_redirects` — SPA rewrite (Cloudflare Pages e Netlify leem
  este arquivo; faz `/*` cair em `index.html` para as rotas do react-router).

## Variáveis de ambiente

### Backend (obrigatórias — o processo não sobe sem elas)

| Variável | Para que serve |
| --- | --- |
| `MONGO_URL` | string de conexão do MongoDB existente |
| `DB_NAME` | nome do banco já usado pela aplicação |
| `JWT_SECRET` | assinatura dos tokens de login (`openssl rand -hex 32`) |
| `ADMIN_EMAIL` | e-mail do administrador do torneio |
| `ADMIN_PASSWORD` | senha do administrador (aplicada no startup) |
| `CORS_ORIGINS` | origem do frontend, exatamente como o navegador envia |

Opcional: `PORT` (definida pelo host; o `Dockerfile` já usa `8000` como padrão).

### Frontend (build)

| Variável | Para que serve |
| --- | --- |
| `REACT_APP_BACKEND_URL` | URL pública do backend, sem barra final |

Essa variável é embutida no bundle: **defina antes do build** e refaça o build se
a URL do backend mudar.

## Regras de configuração

- `CORS_ORIGINS` deve ser a origem exata do frontend, sem barra final
  (`https://kop.exemplo.com`). Para mais de uma, separe por vírgula. Deixar em
  branco cai no padrão `*`, que é amplo demais para produção.
- `REACT_APP_BACKEND_URL` deve ser HTTPS e apontar para o domínio do backend
  (o cliente monta `${REACT_APP_BACKEND_URL}/api`).
- `DB_NAME` deve continuar sendo o banco atual: o backend cria índices e faz
  backfill de campos estruturais no startup. Isso é o comportamento normal do app,
  não uma migração nova — mas **aponte para o banco real**, nunca para um vazio.
- `JWT_SECRET` e `ADMIN_PASSWORD` de produção precisam ser novos e fortes: a senha
  do admin é reaplicada a cada boot a partir de `ADMIN_PASSWORD`.

## Passo a passo

### 1. Backend (container)

1. Publique o diretório `backend/` no host escolhido (build a partir do
   `Dockerfile`; contexto = `backend/`).
2. Configure todas as variáveis da tabela do backend.
3. Libere a saída para o MongoDB: no Atlas, inclua o IP de saída do host na
   access list (ou `0.0.0.0/0` apenas se aceitar o risco).
4. Verifique a saúde em `GET https://<api>/` → `{"app": "KOP 3x3", "status": "running"}`.

Alternativa sem Docker (host com runtime Python): comando de start
`uvicorn server:app --host 0.0.0.0 --port $PORT --proxy-headers`, com
`pip install -r requirements.txt` no build.

### 2. Frontend (estático)

1. Defina `REACT_APP_BACKEND_URL` no host.
2. Build: `cd frontend && yarn install --frozen-lockfile && yarn build`.
3. Publique o diretório `frontend/build` (Cloudflare Pages: build `yarn build`,
   saída `build`; o `_redirects` já cobre as rotas).
4. Abra a URL pública e confirme login e carregamento de jogadores/partidas.

### 3. Ordem importa

Publique o backend primeiro: a URL dele é necessária para o build do frontend, e a
origem do frontend é necessária em `CORS_ORIGINS`. Se a URL do frontend mudar,
atualize `CORS_ORIGINS` no backend e reinicie o serviço.

## Alterações de código necessárias

**Nenhuma.** O código já respeita o contrato de produção:

- backend lê tudo de variáveis de ambiente e falha rápido se faltar alguma;
- CORS é configurável por `CORS_ORIGINS`;
- frontend lê `REACT_APP_BACKEND_URL` no build;
- as fotos continuam em base64 no documento MongoDB (sem depender de disco local).

Pontos de atenção (não bloqueiam o deploy, não foram alterados):

- o rate limit é em memória e por processo — com vários workers/instâncias o limite
  efetivo é multiplicado;
- fotos base64 dentro dos documentos aumentam o tamanho do banco e o tráfego da
  listagem do telão;
- o `frontend/craco.config.js` tem proxy de `/api` apenas para desenvolvimento.
