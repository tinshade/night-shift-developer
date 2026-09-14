FROM python:3.12-slim

WORKDIR /app

COPY force-error.py .

RUN pip install --no-cache-dir requests \
    && apt-get update \
    && apt-get install -y --no-install-recommends cron \
    && rm -rf /var/lib/apt/lists/*

COPY crontab /etc/cron.d/force-error-cron

RUN chmod 0644 /etc/cron.d/force-error-cron \
    && printf '\n' >> /etc/cron.d/force-error-cron \
    && crontab /etc/cron.d/force-error-cron

CMD ["cron", "-f"]