#!/usr/bin/env bash
# Installs apt packages on a GitHub Linux runner:  apt-install.sh python3-tk xvfb
#
# The runner fetches packages from GitHub's own Ubuntu mirror (azure.archive.ubuntu.com).
# Now and then the runner's name server cannot look up the ubuntu.com hosts at all (seen
# on 2026-11-11: every Linux job died in its first step, the release included). So when
# the mirror does not resolve, or an install through it fails, the runner is pointed at
# Ubuntu's own archive, and hosts its name server cannot find are looked up through a
# public one and written to /etc/hosts. Then the install is tried once more.
set -u

MIRRORS=/etc/apt/apt-mirrors.txt
IPV4='[0-9]+(\.[0-9]+){3}'

install() {
    sudo apt-get update -o Acquire::Retries=1 \
        && sudo apt-get install --yes -o Acquire::Retries=1 "$@"
}

resolves() {
    timeout 15 getent hosts "$1" > /dev/null
}

# The address of a host, asked of a public name server: first with dig, then over HTTPS.
public_address() {
    local found
    found="$(timeout 10 dig +short +time=3 +tries=1 @1.1.1.1 "$1" A 2> /dev/null \
        | grep -E "^${IPV4}\$" | head -n 1)"
    if [ -z "$found" ]; then
        found="$(timeout 15 curl -fsS -H 'accept: application/dns-json' \
            "https://1.1.1.1/dns-query?name=$1&type=A" 2> /dev/null \
            | grep -oE "\"data\":\"${IPV4}\"" | head -n 1 | grep -oE "${IPV4}")"
    fi
    echo "$found"
}

use_ubuntu_archive() {
    echo "::warning::GitHub's Ubuntu mirror is unreachable; using archive.ubuntu.com instead"
    if [ -f "$MIRRORS" ]; then
        printf '%s\n' 'http://archive.ubuntu.com/ubuntu/' 'https://security.ubuntu.com/ubuntu/' \
            | sudo tee "$MIRRORS" > /dev/null
    fi
    sudo sed -i 's|azure\.archive\.ubuntu\.com|archive.ubuntu.com|g' \
        /etc/apt/sources.list /etc/apt/sources.list.d/* 2> /dev/null || true
    local host address
    for host in archive.ubuntu.com security.ubuntu.com; do
        if resolves "$host"; then
            continue
        fi
        address="$(public_address "$host")"
        if [ -n "$address" ]; then
            echo "$address $host" | sudo tee -a /etc/hosts > /dev/null
            echo "The runner's name server cannot find $host; using $address (public DNS)"
        else
            echo "::warning::$host could not be looked up through a public name server either"
        fi
    done
}

switched=no
if [ -f "$MIRRORS" ] && grep -q azure.archive.ubuntu.com "$MIRRORS" \
        && ! resolves azure.archive.ubuntu.com; then
    use_ubuntu_archive
    switched=yes
fi
if install "$@"; then
    exit 0
fi
if [ "$switched" = yes ]; then
    exit 1
fi
use_ubuntu_archive
install "$@"
