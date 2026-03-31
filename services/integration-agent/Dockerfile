# ── Stage 1: build wheels (needs C++ toolchain for chroma-hnswlib) ──
FROM python:3.12-slim AS builder

RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential cmake && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN python -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

COPY requirements.txt .
# Install heavy packages first (chromadb, motor, numpy) so Docker layer-cache
# means a network retry only re-downloads the layer that actually failed.
# --retries 5  — retry each package download up to 5 times on network errors
# --timeout 300 — per-operation socket timeout (connect + read) in seconds
RUN pip install --no-cache-dir --timeout 300 --retries 5 \
        chromadb==0.5.3 motor==3.5.0 pymongo==4.8.0
RUN pip install --no-cache-dir --timeout 300 --retries 5 -r requirements.txt

# ── Stage 2: slim runtime (no compilers) ──
FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl libgl1 libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /app/venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "3003", "--log-level", "info"]
