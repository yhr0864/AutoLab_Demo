"""
Download NATS official documentation from docs.nats.io
and merge into grouped search files for keyword-based retrieval.

Usage: python Hardware/nats/download_docs.py

Output: Hardware/nats/search/ directory with 10 merged .txt files grouped by topic.
         Hardware/nats/search/raw/ directory with individual downloaded .md files.

Docs source: https://docs.nats.io/
Page index: https://docs.nats.io/llms.txt
"""

import re
import shutil
import sys
import urllib.request
from pathlib import Path

BASE_URL = "https://docs.nats.io"
LLMS_URL = f"{BASE_URL}/llms.txt"
ROOT_DIR = Path(__file__).resolve().parent  # Hardware/nats/
SEARCH_DIR = ROOT_DIR / "search"
RAW_DIR = SEARCH_DIR / "raw"

# -- Group definitions: group_name -> list of doc path prefixes or exact paths --
# Pages are auto-assigned from llms.txt based on their section hierarchy.
# The keys below define the 10 output groups and which sections they pull from.

GROUP_DEFS: list[tuple[str, str, list[tuple[str, str | None]]]] = [
    # (file_prefix, display_title, [(h2_section, h3_subsection or None), ...])
    ("01-concepts", "Core Concepts", [
        ("concepts", "ecosystem"),
        ("concepts", "getting-started"),
        ("concepts", "intro"),
        ("concepts", "pub-sub-basics"),
        ("concepts", "queue-groups"),
        ("concepts", "request-reply"),
        ("concepts", "subjects"),
        ("concepts", "what-is-nats"),
        ("concepts", "topologies"),
    ]),
    ("02-jetstream", "JetStream", [
        ("concepts", "jetstream"),
        ("learn", "jetstream"),
        ("reference", "jetstream"),
    ]),
    ("03-core-nats", "Core NATS Deep Dive", [
        ("learn", "core-nats"),
    ]),
    ("04-clustering-deployment", "Clustering, Deployment & Topologies", [
        ("learn", "clustering"),
        ("learn", "deployment"),
        ("learn", "topologies"),
    ]),
    ("05-security", "Security", [
        ("concepts", "security"),
        ("learn", "security"),
    ]),
    ("06-services-api", "Services API / Microservices", [
        ("learn", "services"),
        ("reference", "services"),
    ]),
    ("07-kv-object-store", "KV Store & Object Store", [
        ("learn", "key-value"),
        ("learn", "object-store"),
    ]),
    ("08-monitoring-resilience", "Monitoring, MQTT, WebSocket & Resilience", [
        ("learn", "monitoring"),
        ("learn", "mqtt"),
        ("learn", "websocket"),
        ("learn", "resilient-clients"),
    ]),
    ("09-reference", "Reference", [
        ("reference", "config"),
        ("reference", "protocols"),
        ("reference", "system"),
    ]),
    ("10-tutorials", "Tutorials", [
        ("tutorials", "build-an-app"),
        ("tutorials", "first-stream"),
        ("tutorials", "hello-nats"),
        ("tutorials", "key-value"),
        ("tutorials", "request-reply"),
        ("tutorials", "stream-consumer"),
        ("tutorials", "work-queue"),
    ]),
]


def fetch_llms_txt() -> str:
    """Download and return the llms.txt content."""
    req = urllib.request.Request(LLMS_URL)
    req.add_header("User-Agent", "nats-doc-downloader/1.0")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8")


def parse_llms(content: str) -> dict[str, dict[str, list[str]]]:
    """
    Parse llms.txt into nested dict: {h2_section: {h3_subsection: [paths]}}
    Also handles top-level pages under each h2 with key '_top'.
    """
    sections: dict[str, dict[str, list[str]]] = {}
    current_h2: str | None = None
    current_h3: str | None = None

    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("## "):
            current_h2 = line[3:]
            if current_h2 not in sections:
                sections[current_h2] = {"_top": []}
            current_h3 = None
        elif line.startswith("### "):
            current_h3 = line[4:]
            if current_h2 and current_h3 not in sections[current_h2]:
                sections[current_h2][current_h3] = []
        elif line.startswith("- ["):
            m = re.search(r"\]\(([^)]+\.md)\)", line)
            if m:
                path = m.group(1)
                if current_h3 and current_h2:
                    sections[current_h2][current_h3].append(path)
                elif current_h2:
                    sections[current_h2]["_top"].append(path)

    return sections


def build_groups(
    sections: dict[str, dict[str, list[str]]],
) -> dict[str, list[str]]:
    """Map GROUP_DEFS to flat dict: group_filename -> [page_paths]."""
    groups: dict[str, list[str]] = {}

    for file_prefix, _title, selectors in GROUP_DEFS:
        pages: list[str] = []
        seen: set[str] = set()
        for h2, h3 in selectors:
            h2_data = sections.get(h2, {})
            if h3:
                for p in h2_data.get(h3, []):
                    if p not in seen:
                        pages.append(p)
                        seen.add(p)
            else:
                # Take all pages under this h2
                for sub_pages in h2_data.values():
                    for p in sub_pages:
                        if p not in seen:
                            pages.append(p)
                            seen.add(p)
        groups[file_prefix] = pages

    return groups


def download_one(page_path: str) -> bool:
    """Download a single .md page into RAW_DIR. Returns True on success."""
    url = f"{BASE_URL}{page_path}"
    # Preserve path structure under raw/
    rel_path = page_path.lstrip("/")
    out_path = RAW_DIR / rel_path
    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "nats-doc-downloader/1.0")
        with urllib.request.urlopen(req, timeout=30) as resp:
            content = resp.read()

        with open(out_path, "wb") as f:
            f.write(content)
        return True
    except Exception as e:
        print(f"    FAIL [{page_path}]: {e}")
        return False


def merge_group(
    group_name: str,
    pages: list[str],
) -> int:
    """Merge downloaded .md files into a single group .txt file. Returns line count."""
    group_title = group_name.split("-", 1)[1].replace("-", " ").title()
    out_path = SEARCH_DIR / f"{group_name}.txt"
    doc_count = 0

    with open(out_path, "w", encoding="utf-8") as out:
        out.write(f"# {group_title}\n")
        out.write(f"# Group: {group_name}\n")
        out.write(f"# Source: {BASE_URL}/\n")
        out.write(f"# Index: {LLMS_URL}\n\n")

        for page_path in pages:
            rel_path = page_path.lstrip("/")
            src_path = RAW_DIR / rel_path
            if not src_path.exists():
                continue

            source_url = f"{BASE_URL}{page_path}"
            out.write(f"\n{'=' * 70}\n")
            out.write(f"DOC: {page_path}\n")
            out.write(f"SOURCE: {source_url}\n")
            out.write(f"{'=' * 70}\n\n")

            try:
                with open(src_path, encoding="utf-8", errors="replace") as f:
                    content = f.read()
                # Strip YAML frontmatter if present (--- at start)
                if content.startswith("---"):
                    end = content.find("---", 3)
                    if end != -1:
                        content = content[end + 3 :].lstrip()
                out.write(content)
            except Exception as e:
                out.write(f"[Error reading source: {e}]\n")

            out.write("\n")
            doc_count += 1

    lines = sum(1 for _ in open(out_path, encoding="utf-8", errors="replace"))
    print(f"  {group_name}.txt: {doc_count} docs, {lines} lines")
    return lines


def report_coverage(
    groups: dict[str, list[str]], success_set: set[str], fail_set: set[str]
) -> None:
    """Print which pages were missed per group."""
    for group_name, pages in groups.items():
        missed = [p for p in pages if p in fail_set]
        if missed:
            print(f"\n  ⚠ {group_name}: {len(missed)} pages failed:")
            for p in missed[:10]:
                print(f"      - {p}")
            if len(missed) > 10:
                print(f"      ... and {len(missed) - 10} more")


def main() -> None:
    # Clean and recreate directories
    if SEARCH_DIR.exists():
        print("Cleaning existing search/ directory...")
        shutil.rmtree(SEARCH_DIR)
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    # --- Phase 0: Fetch and parse llms.txt ---
    print("=" * 60)
    print("Phase 0: Fetching page index from llms.txt...")
    print("=" * 60)
    try:
        llms_content = fetch_llms_txt()
        print(f"  Downloaded: {len(llms_content)} bytes")
    except Exception as e:
        print(f"FATAL: Could not fetch {LLMS_URL}: {e}")
        sys.exit(1)

    sections = parse_llms(llms_content)
    print(f"  Parsed: {len(sections)} top-level sections")
    for h2, data in sections.items():
        total = len(data["_top"]) + sum(len(v) for v in data.values() if not isinstance(v, str))
        sub_count = sum(1 for k in data if k != "_top")
        print(f"    {h2}: {total} pages in {sub_count} subsections")

    groups = build_groups(sections)
    total_grouped = sum(len(v) for v in groups.values())
    all_pages = set()
    for pages in groups.values():
        all_pages.update(pages)
    print(f"\n  Grouped: {total_grouped} pages into {len(groups)} groups")
    print(f"  Unique pages: {len(all_pages)}")

    # --- Phase 1: Download all pages ---
    print(f"\n{'=' * 60}")
    print(f"Phase 1: Downloading {len(all_pages)} pages from {BASE_URL}/...")
    print("=" * 60)
    success_set: set[str] = set()
    fail_set: set[str] = set()

    for i, page_path in enumerate(sorted(all_pages)):
        ok = download_one(page_path)
        if ok:
            success_set.add(page_path)
        else:
            fail_set.add(page_path)

        if (i + 1) % 50 == 0:
            print(f"  ... {i + 1}/{len(all_pages)} ({len(success_set)} ok, {len(fail_set)} fail)")

    print(f"\nDownload done: {len(success_set)} ok, {len(fail_set)} fail out of {len(all_pages)}")

    # --- Phase 2: Merge into group files ---
    print(f"\n{'=' * 60}")
    print("Phase 2: Merging into group search files...")
    print("=" * 60)
    total_lines = 0
    total_docs = 0
    for group_name, pages in groups.items():
        lines = merge_group(group_name, pages)
        total_lines += lines
        total_docs += sum(1 for p in pages if p in success_set)

    # --- Report ---
    print(f"\n{'=' * 60}")
    print(f"Done! {total_docs} documents merged into {len(groups)} search files")
    print(f"Total lines: {total_lines}")
    print(f"Search files in: {SEARCH_DIR}")
    print(f"Raw sources in: {RAW_DIR}")

    if fail_set:
        print(f"\n⚠ Warning: {len(fail_set)} pages failed to download.")
        report_coverage(groups, success_set, fail_set)


if __name__ == "__main__":
    main()
