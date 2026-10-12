# NutriScan AI backend — CPU-only image
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/data/hf-cache \
    STORAGE_DIR=/data/uploads \
    APP_ENV=prod

WORKDIR /app

# CPU-only PyTorch first (avoids pulling multi-GB CUDA wheels), then the rest.
COPY requirements.txt .
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install -r requirements.txt

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY scripts ./scripts
COPY frontend ./frontend
COPY docker/entrypoint.sh /entrypoint.sh

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data/hf-cache /data/uploads \
    && chown -R appuser:appuser /data /app \
    && chmod +x /entrypoint.sh
USER appuser

VOLUME ["/data"]
EXPOSE 8000

# The first start downloads the ~350 MB classifier into HF_HOME, hence the long start period.
HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4).status == 200 else 1)"

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
