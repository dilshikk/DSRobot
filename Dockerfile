FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Бот не должен работать от root (issue #5).
RUN groupadd --system app && useradd --system --gid app --home-dir /app --no-create-home app

COPY --chown=app:app . .

USER app

CMD ["python", "-m", "bot.main"]
