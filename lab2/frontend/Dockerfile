FROM nginx:1.27.2-alpine

COPY html/ /usr/share/nginx/html/
COPY conf.d/default.conf /etc/nginx/conf.d/default.conf

HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -qO- http://127.0.0.1/ >/dev/null || exit 1
