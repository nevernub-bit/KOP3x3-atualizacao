# Backend KOP 3x3 — imagem de produção (FastAPI + Uvicorn)
# Serve apenas a API. O frontend React é publicado separadamente como estático.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    FORWARDED_ALLOW_IPS=*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

EXPOSE 8000

# --proxy-headers/--forwarded-allow-ips: o host faz TLS e envia X-Forwarded-For;
# o backend usa esse IP no rate limit de login/inscrição.
CMD ["sh", "-c", "exec uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"]
