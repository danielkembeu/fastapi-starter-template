# --- Étape 1 : dépendances (couche mise en cache tant que les requirements ne changent pas)
FROM python:3.15-slim AS builder
WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements*.txt ./
# Dépendances optionnelles, à la demande :
#   docker build --build-arg EXTRAS="storage mongo" .      (→ requirements-storage.txt, requirements-mongo.txt)
ARG EXTRAS=""
RUN pip install --no-cache-dir -r requirements.txt \
    && for extra in $EXTRAS; do pip install --no-cache-dir -r "requirements-$extra.txt"; done

# --- Étape 2 : image d'exécution minimale, sans outils de build, sans secrets
FROM python:3.15-slim
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ENVIRONMENT=production \
    APP_HOST=0.0.0.0 \
    APP_PORT=8000

RUN useradd --system --create-home --uid 10001 app
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app . .
USER app

EXPOSE 8000

# `live` ne teste aucune dépendance : un hoquet de la base ne doit pas faire redémarrer le conteneur.
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
    CMD python -c "import os,sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:%s/health/live' % os.environ.get('APP_PORT', '8000'), timeout=2).status == 200 else 1)"

# WEB_CONCURRENCY : nombre de workers (≈ 1 par cœur dédié à l'API).
# Règle : WEB_CONCURRENCY x (DB_POOL_SIZE + DB_MAX_OVERFLOW) doit rester sous max_connections de PostgreSQL.
# --proxy-headers : l'IP cliente vient du reverse proxy ; FORWARDED_ALLOW_IPS limite à qui on fait confiance.
CMD ["sh", "-c", "exec uvicorn app.server:server --host ${APP_HOST} --port ${APP_PORT} --workers ${WEB_CONCURRENCY:-2} --proxy-headers --no-access-log --forwarded-allow-ips=\"${FORWARDED_ALLOW_IPS:-127.0.0.1}\" --no-server-header"]
