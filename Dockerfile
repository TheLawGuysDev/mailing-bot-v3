FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Docker Compose overrides via .env (e.g. sqlite:////data/...).
# Cloud Run / no env: app defaults to sqlite:////tmp/mailing_bot.db in config.py.
ENV DATABASE_URL=sqlite:////data/mailing_bot.db
ENV APP_ENV=local
ENV PORT=8080

RUN mkdir -p /data

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts

EXPOSE 8080

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
