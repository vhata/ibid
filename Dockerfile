FROM python:3.13-slim AS builder
WORKDIR /app
RUN pip install --no-cache-dir --upgrade pip build
COPY pyproject.toml README.md COPYING ./
COPY src ./src
RUN pip install --no-cache-dir .

FROM python:3.13-slim
RUN groupadd -r ibid && useradd -r -g ibid -d /app -s /sbin/nologin ibid
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin/ibid /usr/local/bin/ibid
USER ibid
ENV IBID_CONFIG=/app/ibid.toml
ENTRYPOINT ["ibid", "run"]
