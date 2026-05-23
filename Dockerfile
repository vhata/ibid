FROM python:3.13-slim AS builder
WORKDIR /app
RUN pip install --no-cache-dir --upgrade pip build
COPY pyproject.toml README.md COPYING ./
COPY src ./src
RUN pip install --no-cache-dir .

FROM python:3.13-slim
RUN groupadd -r ibid && useradd -r -g ibid -d /app -s /sbin/nologin ibid
WORKDIR /app

# Default config baked into the image — sane defaults; secrets land via env.
# Override paths/contents by mounting your own ibid.toml at /app/ibid.toml.
COPY ibid.example.toml /app/ibid.toml

# /data is the conventional persistent-volume mount point on fly.io and
# friends. We point the SQLite URL at it so the DB survives redeploys.
RUN mkdir -p /data && chown ibid:ibid /data
ENV IBID_CONFIG=/app/ibid.toml \
    IBID_DB_URL=sqlite+aiosqlite:////data/ibid.db

COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin/ibid /usr/local/bin/ibid

USER ibid
ENTRYPOINT ["ibid", "run"]
