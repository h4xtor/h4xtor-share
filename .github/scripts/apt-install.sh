#!/usr/bin/env bash
# Installs apt packages on a GitHub Linux runner:  apt-install.sh python3-tk xvfb
#
# The runner fetches packages from GitHub's own Ubuntu mirror (azure.archive.ubuntu.com).
# When that mirror cannot be reached, every Linux job dies in its first step, the release
# included. So: if the mirror does not answer, or an install through it fails, the runner
# is pointed at Ubuntu's own archive and the install is tried once more.
set -u

MIRRORS=/etc/apt/apt-mirrors.txt

install() {
    sudo apt-get update -o Acquire::Retries=1 \
        && sudo apt-get install --yes -o Acquire::Retries=1 "$@"
}

use_ubuntu_archive() {
    echo "::warning::GitHub's Ubuntu mirror is unreachable; using archive.ubuntu.com instead"
    if [ -f "$MIRRORS" ]; then
        printf 'http://archive.ubuntu.com/ubuntu/\thttps://security.ubuntu.com/ubuntu/\n' \
            | tr '\t' '\n' | sudo tee "$MIRRORS" > /dev/null
    fi
    sudo sed -i 's|azure\.archive\.ubuntu\.com|archive.ubuntu.com|g' \
        /etc/apt/sources.list /etc/apt/sources.list.d/* 2> /dev/null || true
}

switched=no
if [ -f "$MIRRORS" ] && grep -q azure.archive.ubuntu.com "$MIRRORS" \
        && ! timeout 15 getent hosts azure.archive.ubuntu.com > /dev/null; then
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
