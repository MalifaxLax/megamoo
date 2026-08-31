#!/usr/bin/env bash
#
# Build PDFs from the MegaMOO manual markdown files.
# Requires: pandoc + weasyprint (HTML/CSS -> PDF engine).
#
#   ./make-pdfs.sh
#
# Outputs one PDF per chapter into ./pdf/, plus a combined
# megamoo-developer-manual.pdf containing all chapters in order.

set -euo pipefail
cd "$(dirname "$0")"

CSS="assets/manual.css"
OUT="pdf"
HL="tango"          # syntax-highlight style
mkdir -p "$OUT"

# Reading order (basename, no extension)
FILES=(README 01-architecture 02-writing-verbs 03-building-worlds \
       04-operations 05-engine-systems 06-object-prototypes 07-help-system)

common=(--standalone --css="$CSS" --pdf-engine=weasyprint \
        --highlight-style="$HL" --metadata title="")

echo "Building per-chapter PDFs..."
# Standalone chapter PDFs: flatten every link to a LOCAL file (other chapters,
# ../../LICENSE, etc.) to plain text. A cross-file link in a PDF resolves to a
# machine-specific absolute file:// path that errors when the PDF is moved or
# shared, so we drop the link and keep the text. Same-file #anchor links and
# external http(s) links are kept and work normally. Use the combined PDF for
# cross-chapter navigation.
flatten_local='s{\[([^\]]+)\]\((?!#|https?://)[^)]+\)}{$1}g'
for f in "${FILES[@]}"; do
  perl -pe "$flatten_local" "$f.md" \
    | pandoc -o "$OUT/$f.pdf" "${common[@]}"
  echo "  -> $OUT/$f.pdf"
done

echo "Building combined manual..."
# Concatenate the sources with a hard page break between each chapter.
# Rewrite ALL inter-chapter links to internal anchors so they navigate within
# the single document:
#   ](chapter.md#anchor) -> ](#anchor)
#   ](chapter.md)        -> ](#doc-chapter)   (top-of-chapter anchor we inject)
tmp="$(mktemp -t megamoo-manual).md"
trap 'rm -f "$tmp"' EXIT
first=1
for f in "${FILES[@]}"; do
  if [ "$first" -eq 0 ]; then
    printf '\n\n<div class="page-break"></div>\n\n' >> "$tmp"
  fi
  printf '<a id="doc-%s"></a>\n\n' "$f" >> "$tmp"
  # 1) chapter.md#anchor -> #anchor   2) chapter.md -> #doc-chapter
  # 3) flatten any remaining local-file link (e.g. ../../LICENSE) to plain text
  perl -pe '
    s{\]\(([0-9A-Za-z_-]+)\.md(#[a-z0-9-]+)\)}{](\2)}g;
    s{\]\(([0-9A-Za-z_-]+)\.md\)}{](#doc-\1)}g;
    s{\[([^\]]+)\]\((?!#|https?://)[^)]+\)}{$1}g;
  ' "$f.md" >> "$tmp"
  first=0
done
pandoc "$tmp" -o "$OUT/megamoo-developer-manual.pdf" \
  --standalone --css="$CSS" --pdf-engine=weasyprint \
  --highlight-style="$HL" --metadata title="MegaMOO Developer Manual"
echo "  -> $OUT/megamoo-developer-manual.pdf"

echo "Done."
