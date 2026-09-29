FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 TZ=Europe/Berlin
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && playwright install --with-deps chromium
COPY . .
EXPOSE 8080
CMD ["python", "-m", "dashboard.app"]
