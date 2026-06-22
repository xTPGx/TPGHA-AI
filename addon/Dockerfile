# Home Assistant Add-on image (scaffold).
ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.12
FROM ${BUILD_FROM}

ENV PYTHONUNBUFFERED=1 \
    CONFIG_DIR=/config/tpg_homeai \
    DATABASE_URL=sqlite:////data/tpg_homeai.db

WORKDIR /app

# Copy backend source from the repo (build context = repo root).
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app

# Seed default config into the add-on config dir on first run via run.sh.
COPY config /defaults/config

COPY addon/run.sh /run.sh
RUN chmod a+x /run.sh

EXPOSE 8088
CMD ["/run.sh"]
