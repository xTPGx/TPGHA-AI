# Home Assistant add-on image for the TPG HomeAI Orchestrator.
#
# IMPORTANT: Home Assistant builds an add-on with the build context set to THIS
# folder (tpg_homeai/), not the repo root. So we cannot COPY ../backend. Instead
# we fetch the application from the public repo at build time. Only run.sh is
# taken from the local build context.
#
# Stage 1: clone the repo + build the React frontend.
# Stage 2: install the FastAPI backend on a Home Assistant Python base image.

# ---- Stage 1: source + frontend build ----
FROM node:20-alpine AS build
RUN apk add --no-cache git
ARG REPO=https://github.com/xTPGx/TPGHA-AI
ARG REF=main
RUN git clone --depth 1 --branch "${REF}" "${REPO}" /src
WORKDIR /src/frontend
RUN npm install && npm run build

# ---- Stage 2: backend runtime ----
# Explicit base image (Supervisor no longer injects a default BUILD_FROM). The
# per-arch image is supplied by build.yaml; the default keeps standalone builds
# working on amd64.
ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.12
FROM ${BUILD_FROM}

ENV PYTHONUNBUFFERED=1 \
    STATIC_DIR=/app/static \
    CONFIG_DIR=/config \
    DATABASE_URL=sqlite:////config/tpg_homeai.db

WORKDIR /app

# Backend dependencies + code (from the cloned source in stage 1).
COPY --from=build /src/backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY --from=build /src/backend/app /app/app

# Built SPA + starter config templates.
COPY --from=build /src/frontend/dist /app/static
COPY --from=build /src/config /app/config_template

# Entrypoint comes from the local add-on folder (it IS in the build context).
COPY run.sh /run.sh
RUN chmod a+x /run.sh

LABEL \
  io.hass.name="TPG HomeAI Orchestrator" \
  io.hass.type="app" \
  io.hass.version="0.1.1" \
  io.hass.arch="amd64|aarch64"

EXPOSE 8088
CMD ["/run.sh"]
