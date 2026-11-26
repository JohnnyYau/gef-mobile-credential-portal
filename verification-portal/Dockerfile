# Runtime image for the credential verification portal (U8.3).
#
# Layers are ordered so a code change only busts the last layer: OS/pip
# config, then the CPU-only torch wheel (optional), then the pinned
# requirements, then app code. Nothing heavier than the ML stack sits above
# the requirements layer, which is what makes rebuilds fast.
#
# CPU-only: torch is installed from the CPU wheel index. Never let pip resolve
# the default CUDA wheels here — that is a multi-GB download plus a
# driver-specific image for a service that does CPU embeddings.
#
# INSTALL_ML=0 (default) ships the lean image: the chat answers with the
# hashing embedder + numpy search. INSTALL_ML=1 adds sentence-transformers and
# faiss-cpu for the better retrieval path, at ~10x the image size.

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

ARG INSTALL_ML=0
WORKDIR /app

# Layer 1 — pinned runtime dependency set (requirements-lock.txt). The lock
# file is the reproducible install; requirements.txt is the loose range file
# kept for humans.
COPY requirements-lock.txt ./
RUN pip install --no-cache-dir -r requirements-lock.txt

# Layer 2 — optional CPU-only ML extras. Separate layer so INSTALL_ML=0 users
# never download torch, and INSTALL_ML=1 users do not re-run the layer above.
COPY requirements.txt ./
RUN if [ "$INSTALL_ML" = "1" ]; then \
      pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
      pip install --no-cache-dir "sentence-transformers>=3.0" "faiss-cpu>=1.9" "scikit-learn>=1.3"; \
    fi

# Layer 3 — application code. Everything above is cacheable across code edits.
COPY app ./app
COPY static ./static

ENV CHAIN_DIR=/app/data/demo-chain \
    SQLITE_PATH=/app/data/portal.sqlite3

RUN useradd --create-home --uid 10001 portal \
 && mkdir -p /app/data \
 && chown -R portal:portal /app/data
USER portal

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
