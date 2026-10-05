#!/usr/bin/env bash
# Komfort-Einstieg: ./install.sh  ==  scripts/install.sh
exec "$(cd "$(dirname "$0")" && pwd)/scripts/install.sh" "$@"
