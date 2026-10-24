# RecallGuard app image: API (default) and Streamlit UI share it. Owner: C.
# Everything installs at build time; nothing installs at runtime (AGENTS.md §9).
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN mkdir -p logs state && useradd --create-home --uid 1000 app && chown -R app:app /app
USER app

EXPOSE 8000 8501
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=5 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/health', timeout=4)"

# Binds 0.0.0.0:$PORT (see run.py --serve)
CMD ["python", "run.py", "--serve"]
