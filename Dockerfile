FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 TZ=Europe/Berlin PATH="/root/.local/bin:${PATH}"
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && rm -rf /var/lib/apt/lists/*
# Claude Code CLI (für die Entscheidungsquelle "Claude-Abo"): offizieller Installer
RUN curl -fsSL https://claude.ai/install.sh | bash
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && playwright install --with-deps chromium
COPY . .
EXPOSE 8080
CMD ["python", "-m", "dashboard.app"]
