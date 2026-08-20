FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system autoflow && adduser --system --ingroup autoflow autoflow

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=autoflow:autoflow app ./app
COPY --chown=autoflow:autoflow migrations ./migrations
COPY --chown=autoflow:autoflow run.py celery_worker.py ./
RUN mkdir -p /app/uploads && chown autoflow:autoflow /app/uploads

USER autoflow
EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/health', timeout=3)"

CMD ["gunicorn", "--workers", "3", "--threads", "2", "--timeout", "90", "--bind", "0.0.0.0:5000", "run:app"]
