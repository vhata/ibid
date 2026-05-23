FROM python:3.13-slim AS builder
WORKDIR /app
RUN pip install --no-cache-dir --upgrade pip build
COPY pyproject.toml README.md COPYING ./
COPY src ./src
RUN pip install --no-cache-dir .

FROM python:3.13-slim

# gosu lets the entrypoint drop privileges to the ``ibid`` user cleanly
# after fixing /data ownership. ~1MB; nothing else in the runtime image
# needs apt.
RUN apt-get update \
 && apt-get install -y --no-install-recommends gosu \
 && rm -rf /var/lib/apt/lists/*

RUN groupadd -r ibid && useradd -r -g ibid -d /app -s /sbin/nologin ibid
WORKDIR /app

# Default config baked into the image — sane defaults; secrets land via env.
# Override paths/contents by mounting your own ibid.toml at /app/ibid.toml.
COPY ibid.example.toml /app/ibid.toml

# /data is the conventional persistent-volume mount point on fly.io and
# friends. The entrypoint chowns it on each start so files dropped in via
# `fly ssh sftp put` (which lands them as root) become ibid-owned before
# the bot tries to open them.
RUN mkdir -p /data && chown ibid:ibid /data
ENV IBID_CONFIG=/app/ibid.toml \
    IBID_DB_URL=sqlite+aiosqlite:////data/ibid.db

COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin/ibid /usr/local/bin/ibid
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Note: we run as root here on purpose. The entrypoint drops to the ibid
# user via gosu before exec'ing the bot — see docker-entrypoint.sh.
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["run"]
