FROM python:3.12-slim-bookworm
ARG VCS_REF=development
LABEL org.opencontainers.image.title="NorthStar application" \
      org.opencontainers.image.revision=$VCS_REF
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    BUILD_REVISION=$VCS_REF NORTHSTAR_REQUIRE_POSTGRES=1 \
    NORTHSTAR_SEED_DEMO=0 NORTHSTAR_DATA_DIR=/tmp/northstar
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && mkdir -p /etc/ssl/certs/rds \
    && python -c "import urllib.request; urllib.request.urlretrieve('https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem', '/etc/ssl/certs/rds/global-bundle.pem')" \
    && groupadd --gid 10001 northstar \
    && useradd --uid 10001 --gid northstar --no-create-home northstar
COPY --chown=10001:10001 server.py database.py catalog.py wsgi.py gunicorn.conf.py ./
COPY --chown=10001:10001 scripts/ ./scripts/
COPY --chown=10001:10001 templates/ ./templates/
COPY --chown=10001:10001 static/ ./static/
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"]
ENTRYPOINT ["/bin/sh", "/app/scripts/entrypoint.sh"]
CMD ["gunicorn", "--config", "gunicorn.conf.py", "wsgi:application"]
