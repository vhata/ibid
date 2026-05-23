#!/bin/sh
# Container entrypoint.
#
# Runs as root so it can fix ownership of /data (the persistent volume —
# files dropped in via `fly ssh sftp put` arrive owned by root), then
# drops to the unprivileged `ibid` user before `exec`ing the bot.
set -e

if [ -d /data ]; then
    chown -R ibid:ibid /data 2>/dev/null || true
fi

exec gosu ibid:ibid /usr/local/bin/ibid "$@"
