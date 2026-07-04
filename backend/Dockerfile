# Portable single-container API. Runs identically on DigitalOcean, Fly, Render,
# a bare VPS, or your laptop — nothing here is host-specific.
FROM python:3.12-slim

WORKDIR /app

# System certs for outbound HTTPS to Beeminder; nothing else needed.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# SQLite lives here; mount a volume at /data in production so it survives
# restarts and redeploys (see deploy/ compose + fly configs).
# NOTE: the mounted volume must be writable by uid 1000 — chown it once from a
# root shell if the volume predates the non-root switch.
ENV SAMVARA_DB=/data/samvara.db
VOLUME ["/data"]

RUN useradd --uid 1000 --no-create-home samvara && \
    mkdir -p /data && chown samvara:samvara /data
USER samvara

EXPOSE 8000

# ONE worker on purpose: the store serializes user actions and /tick with a
# process-level lock, which only holds within a single process. Scale out with
# a shared database instead of more workers (swap the Store implementation).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
