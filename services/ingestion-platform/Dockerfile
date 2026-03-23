FROM python:3.11-slim

WORKDIR /app

# Install system deps for Playwright + Docling
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright Chromium (headless browser for HTML collector)
RUN playwright install chromium --with-deps 2>/dev/null || true

COPY . .

EXPOSE 4006

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "4006"]
