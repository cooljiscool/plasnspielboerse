FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 TZ=Europe/Berlin PATH="/root/.local/bin:${PATH}"
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates git poppler-utils && rm -rf /var/lib/apt/lists/*
# Claude Code CLI (für die Entscheidungsquelle "Claude-Abo"): offizieller Installer
RUN curl -fsSL https://claude.ai/install.sh | bash
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && playwright install --with-deps firefox
COPY . .
# Optional: docker compose build --build-arg WITH_KRONOS=1 (PyTorch für CPU, ca. 1 GB mehr)
ARG WITH_KRONOS=0
RUN if [ "$WITH_KRONOS" = "1" ]; then sh scripts/setup_kronos.sh; fi
EXPOSE 8080
CMD ["python", "-m", "dashboard.app"]
