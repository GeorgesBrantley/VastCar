FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# The league schedule uses America/New_York through Python's zoneinfo module.
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install --yes --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY auth.py league.py server.py ./
COPY public ./public
COPY docker-entrypoint.sh ./

# Fly should mount its persistent volume at /data. Keeping the database there
# prevents accounts and race results from disappearing on a redeploy.
RUN mkdir -p /data \
    && chmod +x /app/docker-entrypoint.sh \
    && python -c "from zoneinfo import ZoneInfo; ZoneInfo('America/New_York')"

EXPOSE 8080

STOPSIGNAL SIGTERM

CMD ["/app/docker-entrypoint.sh"]
