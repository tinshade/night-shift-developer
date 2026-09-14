FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

ARG DOCKER_CLI_VERSION=27.3.1

RUN apt-get update \
	&& apt-get install -y --no-install-recommends curl ca-certificates git \
	&& curl -fsSL "https://download.docker.com/linux/static/stable/x86_64/docker-${DOCKER_CLI_VERSION}.tgz" \
	| tar -xz --strip-components=1 -C /usr/local/bin docker/docker \
	&& rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip \
	&& if [ -s requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi

COPY . .

CMD ["python", "main.py"]
