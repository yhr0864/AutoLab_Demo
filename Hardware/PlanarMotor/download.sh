#!/bin/bash
# Download PlanarMotor documentation from docs.planarmotor.com
# Usage: bash download.sh
# Run this script to initially download or refresh all docs.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE_URL="https://docs.planarmotor.com"
PAGETREE_URL="${BASE_URL}/tech-portal/__pagetree.json"

echo "Fetching page tree..."
curl -sL "$PAGETREE_URL" -o "$SCRIPT_DIR/pagetree_temp.json"

if [ ! -s "$SCRIPT_DIR/pagetree_temp.json" ]; then
    echo "ERROR: Failed to fetch page tree"
    exit 1
fi

echo "Downloading docs as .md files..."
python3 << 'PYEOF'
import json, os, sys

base_dir = os.environ.get("SCRIPT_DIR", os.path.dirname(os.path.abspath(__file__)))
os.chdir(base_dir)

with open("pagetree_temp.json") as f:
    data = json.load(f)

# Collect all doc paths
paths = []
def walk(node):
    p = node.get("path", "")
    t = node.get("title", "")
    if p and p.startswith("/tech-portal/"):
        paths.append(p)
    for child in node.get("children", []):
        walk(child)

for item in data:
    walk(item)

# Define 10 logical groups based on page tree hierarchy
GROUPS = {
    "Safety": "01-safety",
    "Getting Started": "02-getting-started",
    "Hardware Specifications": "03-hardware-specs",
    "Software Manual": "04-software-manual",
    "Planar Motor Libraries": "05-libraries",
    "Planar Motor Tool": "06-planar-motor-tool",
    "Application Notes": "07-application-notes",
    "Training": "08-training",
    "Troubleshooting": "09-troubleshooting",
    "Downloads": "10-downloads",
}

# Walk tree to assign groups
group_docs = {}
def walk_group(node, current_group=None):
    title = node.get("title", "")
    path = node.get("path", "")
    if current_group is None and title in GROUPS:
        current_group = GROUPS[title]
    if path and path.startswith("/tech-portal/") and current_group:
        slug = path.replace("/tech-portal/", "")
        if current_group not in group_docs:
            group_docs[current_group] = []
        group_docs[current_group].append((slug, title))
    for child in node.get("children", []):
        child_title = child.get("title", "")
        if child_title in GROUPS:
            walk_group(child, GROUPS[child_title])
        else:
            walk_group(child, current_group)

for item in data:
    walk_group(item)

# Download individual .md files
import urllib.request
import shutil

if os.path.exists("docs"):
    shutil.rmtree("docs")
os.makedirs("docs")

total = len(paths)
success = 0
for i, path in enumerate(paths):
    slug = path.replace("/tech-portal/", "")
    dir_path = os.path.join("docs", os.path.dirname(slug))
    os.makedirs(dir_path, exist_ok=True)
    url = f"https://docs.planarmotor.com{path}.md"
    out_file = os.path.join("docs", f"{slug}.md")
    try:
        urllib.request.urlretrieve(url, out_file)
        success += 1
    except Exception as e:
        print(f"  FAIL: {slug} ({e})")
    if (i + 1) % 100 == 0:
        print(f"  Downloaded: {i+1}/{total}")

print(f"Downloaded: {success}/{total} individual .md files")

# Build per-group search files
if os.path.exists("search"):
    shutil.rmtree("search")
os.makedirs("search")

for group in sorted(group_docs.keys()):
    group_name = group.split("-", 1)[1]
    out_path = f"search/{group}.txt"
    with open(out_path, "w", encoding="utf-8") as out:
        out.write(f"# {group_name.replace('-', ' ').title()}\n\n")
        for slug, title in group_docs[group]:
            md_path = f"docs/{slug}.md"
            if os.path.exists(md_path):
                out.write(f"\n{'='*70}\n")
                out.write(f"TITLE: {title}\n")
                out.write(f"SLUG: {slug}\n")
                out.write(f"{'='*70}\n\n")
                with open(md_path, encoding="utf-8", errors="replace") as f:
                    out.write(f.read())
                out.write("\n")

    lines = sum(1 for _ in open(out_path, encoding="utf-8", errors="replace"))
    print(f"  {group}: {len(group_docs[group])} docs, {lines} lines")

print(f"\nDone! {total} docs in {len(group_docs)} groups")
PYEOF

rm -f "$SCRIPT_DIR/pagetree_temp.json"
echo "Done."
