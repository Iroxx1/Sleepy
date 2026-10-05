# Optionaler Container-Betrieb (Docker/Podman). Die Standardinstallation läuft ohne Docker.
FROM node:22-bookworm-slim AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 SLEEPY_DATA_DIR=/data SLEEPY_FRONTEND_DIST=/app/frontend/dist TMPDIR=/data/tmp
WORKDIR /app
COPY parser/ parser/
COPY backend/ backend/
RUN pip install --no-cache-dir ./parser ./backend && useradd -r -u 10001 sleepy && mkdir -p /data/tmp && chown -R sleepy /data
COPY --from=frontend /src/frontend/dist /app/frontend/dist
USER sleepy
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=60s --timeout=5s CMD ["sleepy", "healthcheck"]
CMD ["sleepy", "serve"]
