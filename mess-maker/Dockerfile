FROM python:3.12-slim

WORKDIR /app

RUN pip install requests --no-cache-dir

COPY force_error.py .

RUN apt-get update \
    && apt-get install -y --no-install-recommends cron \
    && rm -rf /var/lib/apt/lists/*

COPY crontab /etc/cron.d/force-error-cron

RUN chmod 0644 /etc/cron.d/force-error-cron \
    && crontab /etc/cron.d/force-error-cron

CMD ["cron", "-f"]