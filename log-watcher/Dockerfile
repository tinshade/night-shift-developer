FROM python:3.12-slim

WORKDIR /app

RUN pip install requests --no-cache-dir

COPY log-watcher.py .

RUN apt-get update \
    && apt-get install -y --no-install-recommends cron \
    && rm -rf /var/lib/apt/lists/*

COPY crontab /etc/cron.d/log-watcher-cron

RUN chmod 0644 /etc/cron.d/log-watcher-cron \
    && crontab /etc/cron.d/log-watcher-cron

CMD ["cron", "-f"]