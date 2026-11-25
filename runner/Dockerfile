FROM python:3.11-slim
ARG RUNNER_UID=1000
RUN apt-get update && apt-get install -y --no-install-recommends git openssh-client \
 && rm -rf /var/lib/apt/lists/* \
 && useradd -u ${RUNNER_UID} -m -s /usr/sbin/nologin runner \
 && mkdir -p /var/cache/evap/repos && chown -R runner /var/cache/evap
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY known_hosts runner.py ./
USER runner
CMD ["python", "-u", "runner.py"]
