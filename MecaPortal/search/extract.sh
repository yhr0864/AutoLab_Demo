#!/bin/bash
# Extract Meca500 programming manual to searchable text
# Usage: bash extract.sh
# Run this script whenever mc-pm-meca500.pdf is updated.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PDF="$SCRIPT_DIR/../mc-pm-meca500.pdf"
OUT="$SCRIPT_DIR/manual.txt"

if [ ! -f "$PDF" ]; then
    echo "ERROR: PDF not found at $PDF"
    exit 1
fi

pdftotext -layout "$PDF" "$OUT"
echo "Extracted: $(wc -l < "$OUT") lines -> $OUT"
