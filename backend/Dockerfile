FROM node:22-bookworm-slim AS agentmail
RUN npm install -g --ignore-scripts @tencent-qqmail/agently-cli@1.0.18 \
    && mkdir /out \
    && cp "$(node -p 'require("/usr/local/lib/node_modules/@tencent-qqmail/agently-cli/scripts/run.js").getBinaryPath()')" /out/agently-cli

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY --from=agentmail /out/agently-cli /usr/local/bin/agently-cli
COPY --from=agentmail /usr/local/lib/node_modules/@tencent-qqmail/agently-cli/LICENSE /usr/local/share/licenses/agently-cli/LICENSE
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client curl && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini
COPY plugins ./plugins
RUN useradd --create-home --uid 10001 qbot && mkdir -p /data /backups && chown -R qbot:qbot /app /data /backups
USER qbot
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
