# Rationale.AI — one image, two entrypoints (Streamlit client, or the API).
#
# The dataset and the recorded fixtures are baked in deliberately: the demo has
# to run with no network and no API key, and a fresh clone must reason over the
# same corpus as the dev laptop (data/state is gitignored, so the ledger is
# seeded at boot instead of shipped).
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MOCK_MODE=1

WORKDIR /app

# Dependencies first so image layers cache across code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir "fastapi>=0.115,<1" "uvicorn[standard]>=0.30,<1"

COPY . .

# Fail the BUILD, not the demo, if the engine is broken. Runs entirely offline
# on fixtures and takes a few seconds.
RUN python -m pytest tests/unit tests/integration -q

EXPOSE 8501 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8501/_stcore/health',timeout=4).status==200 else 1)"

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
