# Home Assistant add-on image for the TPG HomeAI Orchestrator.
#
# IMPORTANT: Home Assistant builds an add-on with the build context set to THIS
# folder (tpg_homeai/), not the repo root. So we cannot COPY ../backend. Instead
# we fetch the application from the public repo at build time. Only run.sh is
# taken from the local build context.
#
# The base image is resolved from BUILD_ARCH (the Supervisor always passes it),
# so no build.yaml is required. Declared as a GLOBAL arg so it is usable in the
# stage-2 FROM line.

ARG BUILD_ARCH=amd64

# ---- Stage 1: source + frontend build ----
FROM node:20-alpine AS build
RUN apk add --no-cache git
ARG REPO=https://github.com/xTPGx/TPGHA-AI
ARG REF=main
# BUILD_VERSION (passed by the Supervisor) busts the Docker layer cache so an
# auto-update rebuild ALWAYS re-clones the latest code instead of reusing a
# stale cached clone. Bump config.yaml `version` on every release.
ARG BUILD_VERSION=dev
RUN echo "Building TPG HomeAI ${BUILD_VERSION}" \
    && git clone --depth 1 --branch "${REF}" "${REPO}" /src
WORKDIR /src/frontend
RUN npm install && npm run build

# ---- Stage 2: backend runtime on a Home Assistant Python base image ----
# HA base-python tags are "<py>-alpine<ver>"; a bare ":3.12" tag does not exist.
FROM ghcr.io/home-assistant/${BUILD_ARCH}-base-python:3.12-alpine3.21

ENV PYTHONUNBUFFERED=1 \
    STATIC_DIR=/app/static \
    CONFIG_DIR=/config/tpg_homeai \
    DATABASE_URL=sqlite:////config/tpg_homeai/tpg_homeai.db

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
  io.hass.version="1.0.23" \
  io.hass.arch="amd64|aarch64"

EXPOSE 8088
CMD ["/run.sh"]
