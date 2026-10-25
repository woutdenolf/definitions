#!/bin/bash
# Regenerate the generated files of every phase example with nxds_tools.
# Run from anywhere; PYTHON may name the interpreter.
set -e
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
python="${PYTHON:-python3}"
nxds() { nice -n 19 "$python" -m nxds_tools "$@"; }
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

for phase in phase0 phase1 phase2 phase3 phase4; do
    rm -rf "$here/$phase/generated"
    options=()
    case "$phase" in
        phase2) options=(--legacy "$here/$phase/generated/legacy" --phase 2);;
        phase3) options=(--legacy "$here/$phase/generated/legacy");;
    esac
    nxds build --definitions "$repo" --extra "$here/$phase" --only-extra \
        --out "$here/$phase/generated" --docs "$here/$phase/generated/docs" "${options[@]}"
done

# phase 1: documentation rendered from the bundle, an HDF5 file and its findings
nxds docs --definitions "$repo" --extra "$here/phase1" --only-extra --out "$here/phase1/generated/rst"
nxds build --definitions "$repo" --extra "$here/phase1" --out "$tmp/out" \
    --bundle "$tmp/bundle.zip" --no-round-trip
"$python" "$here/phase1/make_files.py" "$here/phase1"
cd "$here/phase1"
nxds validate demo_phase1.h5 --json --bundle "$tmp/bundle.zip" > generated/findings.jsonl || true
nxds validate demo_phase1_partial.h5 --json --bundle "$tmp/bundle.zip" --partial --all \
    > generated/findings_partial.jsonl || true
nxds validate demo_phase1_partial.h5 --json --bundle "$tmp/bundle.zip" \
    > generated/findings_partial_normal_mode.jsonl || true
