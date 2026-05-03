#!/bin/sh
set -eu

# Append host overrides if writable. On read-only /etc/hosts mounts (or when
# running as non-root without write access) this silently no-ops, and
# Compose-level extra_hosts (Task 14) is expected to cover the case.
if [ -w /etc/hosts ] && [ -f /etc/hosts.append ]; then
    while read -r entry; do
        host_alias=$(echo "$entry" | cut -d' ' -f1)
        ip=$(getent hosts "$host_alias" | awk '{print $1}')
        rest=$(echo "$entry" | cut -d' ' -f2-)
        [ -n "$ip" ] && echo "$ip $rest" >> /etc/hosts
    done < /etc/hosts.append
fi

exec "$@"
