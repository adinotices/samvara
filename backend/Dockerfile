# Portable single-container API. Runs identically on DigitalOcean, Fly, Render,
# a bare VPS, or your laptop — nothing here is host-specific.
FROM python:3.12-slim

WORKDIR /app

# System certs for outbound HTTPS to Beeminder and Postgres; nothing else needed.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY migrations ./migrations
COPY alembic.ini .

# SQLite fallback path when DATABASE_URL is unset — set DATABASE_URL to a
# postgresql+psycopg://... URL for production (see deploy/README.md); SQLite's
# single-writer model and lack of real row locking don't hold up multi-tenant.
# If you do run on SQLite, mount a volume at /data (see deploy/ compose + fly
# configs). NOTE: the mounted volume must be writable by uid 1000 — chown it
# once from a root shell if the volume predates the non-root switch.
ENV SAMVARA_DB=/data/samvara.db
VOLUME ["/data"]

RUN useradd --uid 1000 --no-create-home samvara && \
    mkdir -p /data && chown samvara:samvara /data
USER samvara

EXPOSE 8000

# Migrate BEFORE the app starts — and before it, not after: Store.__init__
# also calls metadata.create_all() as a dev/test convenience (so a fresh
# `pip install && uvicorn app.main:app` works with zero setup), and that's
# idempotent AFTER alembic has stamped the schema, but if it ran FIRST on a
# brand new database, the tables would exist with no alembic_version row —
# leaving every future `alembic upgrade` unable to tell what's applied.
# Running migrations here first means create_all() only ever sees a schema
# alembic already owns.
#
# ONE worker on purpose, still. The transactional row-locking in store.py
# (commitment_lock, used by every charging path) is real on Postgres and
# would make multiple workers safe there — but that's unverified beyond this
# port's own test suite (which exercises it via a single in-process
# TestClient, not real concurrent OS processes). Don't raise this without
# real multi-worker load testing against Postgres first.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1"]
