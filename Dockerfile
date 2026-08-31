FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends jdupes \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY app.py /app/app.py
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data/scan \
    && chown -R appuser:appuser /app /data
USER appuser
ENV SCAN_ROOT=/data/scan WEB_HOST=0.0.0.0 WEB_PORT=8080 JDUPES_BIN=jdupes
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz')"
CMD ["python", "/app/app.py"]
