FROM nginx:stable-alpine
ARG VCS_REF=development
LABEL org.opencontainers.image.title="NorthStar web" \
      org.opencontainers.image.revision=$VCS_REF
ENV APP_UPSTREAM=app:8000 TRUSTED_PROXY_CIDR=127.0.0.1/32
COPY docker/default.conf.template /etc/nginx/templates/default.conf.template
COPY templates/index.html /usr/share/nginx/html/index.html
COPY static/ /usr/share/nginx/html/static/
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=5 \
    CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
