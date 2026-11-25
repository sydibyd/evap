# Disposable SIL execution environment: only Python + pytest, non-root, no tools.
FROM python:3.11-slim
RUN pip install --no-cache-dir pytest==8.3.4 \
 && groupadd -g 10001 sandbox && useradd -u 10001 -g 10001 -M -s /usr/sbin/nologin sandbox \
 && mkdir -p /work && chown 10001:10001 /work
USER 10001:10001
WORKDIR /work
CMD ["python", "-c", "print('EVAP sandbox image')"]
