#!/bin/sh
repo=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec sh "$repo/start-virea.sh" "$@"
