FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DOCQA_DATA_DIR=/data

WORKDIR /app

# Dependencies first, so code edits do not invalidate the wheel cache.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY web ./web
COPY scripts ./scripts
COPY samples ./samples

# Run as a non-root user; /data is the only writable path the app needs.
RUN useradd --create-home --uid 10001 docqa \
    && mkdir -p /data \
    && chown -R docqa:docqa /data /app
USER docqa

VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
