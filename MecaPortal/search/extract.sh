#!/bin/bash
# Extract Meca500 manuals to searchable text
# Usage: bash extract.sh
# Run this script whenever either PDF is updated.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Programming Manual
PM_PDF="$SCRIPT_DIR/../mc-pm-meca500.pdf"
PM_OUT="$SCRIPT_DIR/manual.txt"
# User Manual
UM_PDF="$SCRIPT_DIR/../mc-um-meca500.pdf"
UM_OUT="$SCRIPT_DIR/user_manual.txt"

if [ -f "$PM_PDF" ]; then
    pdftotext -layout "$PM_PDF" "$PM_OUT"
    echo "Extracted: $(wc -l < "$PM_OUT") lines -> $PM_OUT"
else
    echo "WARNING: Programming Manual not found at $PM_PDF"
fi

if [ -f "$UM_PDF" ]; then
    pdftotext -layout "$UM_PDF" "$UM_OUT"
    echo "Extracted: $(wc -l < "$UM_OUT") lines -> $UM_OUT"
else
    echo "WARNING: User Manual not found at $UM_PDF"
fi
