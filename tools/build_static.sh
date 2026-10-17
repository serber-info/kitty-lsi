#!/bin/sh
# Release build with stable source paths; no installation or publication.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
cd "$root/rust"
target=${CARGO_TARGET_DIR:-$root/rust/target}
next_target=no
for argument in "$@"; do
    if [ "$next_target" = yes ]; then target=$argument; next_target=no; continue; fi
    case "$argument" in
        --target-dir) next_target=yes ;;
        --target-dir=*) target=${argument#--target-dir=} ;;
    esac
done
target=$(realpath -m -- "$target")
sep=$(printf '\037')
CARGO_ENCODED_RUSTFLAGS="-C${sep}target-feature=+crt-static${sep}--remap-path-prefix=${CARGO_HOME:-$HOME/.cargo}=/cargo${sep}--remap-path-prefix=$root=/source${sep}--remap-path-prefix=$target=/target"
export CARGO_ENCODED_RUSTFLAGS
exec cargo build --locked --release --target x86_64-unknown-linux-musl "$@"
