# Home Assistant Add-on image for the TPG HomeAI Orchestrator.
#
# Build context = the tpg-homeai repository ROOT (so backend/ and frontend/ are
# available). The Home Assistant builder is configured for this via build.yaml.
#
# Stage 1: build the React frontend into static assets.
# Stage 2: install the FastAPI backend and serve the assets via STATIC_DIR.

# ---- Stage 1: frontend build ----
FROM node:20-alpine AS frontend
WORKDIR /build
COPY frontend/package.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: backend runtime (Home Assistant base image) ----
ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.12
FROM ${BUILD_FROM}

ENV PYTHONUNBUFFERED=1 \
    STATIC_DIR=/app/static \
    DATABASE_URL=sqlite:////data/tpg_homeai.db

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app

# Built SPA from stage 1.
COPY --from=frontend /build/dist /app/static

# Seed default config (copied into the add-on config dir on first run).
COPY config /defaults/config

COPY addon-repository/tpg_homeai/run.sh /run.sh
RUN chmod a+x /run.sh

EXPOSE 8088
CMD ["/run.sh"]
