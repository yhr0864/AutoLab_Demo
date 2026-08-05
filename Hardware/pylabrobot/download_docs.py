"""
Download PyLabRobot documentation sources from docs.pylabrobot.org
and merge into grouped search files for keyword-based retrieval.

Usage: python pylabrobot/download_docs.py

Output: pylabrobot/search/ directory with 7 merged .txt files grouped by topic.
         pylabrobot/search/raw/ directory with individual downloaded source files.

Docs source URL pattern (Sphinx):
  https://docs.pylabrobot.org/stable/_sources/{path}.{md|rst}.txt
  (ipynb files are processed by myst_nb, try .ipynb.txt if .md.txt fails)
"""

import shutil
import sys
import urllib.request
from pathlib import Path

BASE_URL = "https://docs.pylabrobot.org/dev/_sources"
ROOT_DIR = Path(__file__).resolve().parent  # pylabrobot/ dir
SEARCH_DIR = ROOT_DIR / "search"
RAW_DIR = SEARCH_DIR / "raw"

# -- Page Manifest (grouped into 7 search files) --
# All paths are relative to docs.pylabrobot.org/stable/_sources/
# Extensions are detected automatically via HTTP HEAD.
# Excludes api/ (auto-generated) and _templates/ (internal).

GROUPS: dict[str, list[str]] = {
    "01-user-guide-core": [
        # Guide index
        "user_guide/index",
        # Getting started
        "user_guide/getting-started/installation",
        "user_guide/getting-started/rpi",
        "user_guide/getting-started/units",
        # Supported machines & definitions
        "user_guide/machines",
        "user_guide/definitions",
        # Configuration
        "user_guide/configuration",
        # Liquid handling guide + tutorials
        "user_guide/00_liquid-handling/_liquid-handling",
        "user_guide/00_liquid-handling/moving-channels-around",
        "user_guide/00_liquid-handling/tutorial_tip_inventory_consolidation",
        "user_guide/00_liquid-handling/mixing",
        "user_guide/00_liquid-handling/container_no_go_zones",
        # Machine-agnostic features
        "user_guide/machine-agnostic-features/writing-robot-agnostic-protocols",
        "user_guide/machine-agnostic-features/using-the-simulator",
        "user_guide/machine-agnostic-features/using-the-visualizer",
        "user_guide/machine-agnostic-features/using-trackers",
        "user_guide/machine-agnostic-features/tip-spot-generators",
        "user_guide/machine-agnostic-features/sila-discovery",
        "user_guide/machine-agnostic-features/error-handling-general",
        "user_guide/machine-agnostic-features/logging-and-validation/logging-and-validation",
        "user_guide/machine-agnostic-features/logging-and-validation/logging",
        "user_guide/machine-agnostic-features/logging-and-validation/validation",
    ],
    "02-user-guide-manufacturers": [
        # --- Agilent ---
        "user_guide/agilent/index",
        # --- Azenta ---
        "user_guide/azenta/index",
        "user_guide/azenta/fluidx/intellixcap96/hello-world",
        # --- Big Bear ---
        "user_guide/big_bear/index",
        "user_guide/big_bear/orbital-shaker/hello-world",
        # --- Brooks ---
        "user_guide/brooks/index",
        "user_guide/brooks/precise_flex/hello-world",
        # --- Byonoy ---
        "user_guide/byonoy/index",
        "user_guide/byonoy/absorbance_96/hello-world",
        "user_guide/byonoy/luminescence_96/hello-world",
        "user_guide/byonoy/luminescence_96/led_bar",
        # --- Cole-Parmer ---
        "user_guide/cole_parmer/index",
        "user_guide/cole_parmer/genogrinder/hello-world",
        # --- Curiox ---
        "user_guide/curiox/index",
        "user_guide/curiox/curiox-ht2000/hello-world",
        # --- Hamilton ---
        "user_guide/hamilton/index",
        "user_guide/hamilton/star/index",
        "user_guide/hamilton/star/debug",
        "user_guide/hamilton/star/hardware/index",
        "user_guide/hamilton/star/hardware/adjusting-iswap",
        "user_guide/hamilton/star/hardware/adjusting-iswap-gripper-parrallelity",
        "user_guide/hamilton/star/hardware/adjusting-robot",
        "user_guide/hamilton/star/hardware/replacing-iswap",
        # --- HighRes ---
        "user_guide/high_res/index",
        "user_guide/high_res/lid-valet/hello-world",
        # --- Inheco ---
        "user_guide/inheco/index",
        "user_guide/inheco/cpac/hello-world",
        "user_guide/inheco/incubator_shaker/hello-world",
        "user_guide/inheco/odtc/hello-world",
        "user_guide/inheco/scila/hello-world",
        "user_guide/inheco/thermoshake/hello-world",
        # --- KBioscience ---
        "user_guide/kbioscience/index",
        "user_guide/kbioscience/kube/hello-world",
        # --- KBiosystems ---
        "user_guide/kbiosystems/index",
        "user_guide/kbiosystems/ultraseal-epro/hello-world",
        "user_guide/kbiosystems/ultraseal-pro/hello-world",
        "user_guide/kbiosystems/ultraseal-xt-pro/hello-world",
        # --- Mettler Toledo ---
        "user_guide/mettler_toledo/index",
        "user_guide/mettler_toledo/wxs205sdu/hello-world",
        # --- Molecular Devices ---
        "user_guide/molecular_devices/index",
        "user_guide/molecular_devices/spectramax/hello-world",
        "user_guide/molecular_devices/imageXpress/pico",
        # --- QInstruments ---
        "user_guide/qinstruments/index",
        "user_guide/qinstruments/bioshake/hello-world",
        # --- Sartorius ---
        "user_guide/sartorius/index",
        "user_guide/sartorius/entris2/hello-world",
        # --- Thermo Fisher ---
        "user_guide/thermo_fisher/index",
        "user_guide/thermo_fisher/alps/index",
        "user_guide/thermo_fisher/alps/alps300/hello-world",
        "user_guide/thermo_fisher/alps/alps3000/hello-world",
        "user_guide/thermo_fisher/alps/alps5000/hello-world",
        # --- UFACTORY ---
        "user_guide/ufactory/index",
        "user_guide/ufactory/xarm6/hello-world",
    ],
    "03-resources-ontology": [
        # Resource type system overview + custom resources
        "resources/index",
        "resources/introduction",
        "resources/custom-resources",
        # Carriers
        "resources/carrier/carrier",
        "resources/carrier/mfx-carrier/mfx_carrier",
        "resources/carrier/plate-carrier/plate_carrier",
        "resources/carrier/tip-carrier/tip-carrier",
        "resources/carrier/trough-carrier/trough-carrier",
        "resources/carrier/tube-carrier/tube-carrier",
        # Containers
        "resources/container/container",
        "resources/container/petri-dish/petri-dish",
        "resources/container/trough/trough",
        "resources/container/tube/tube",
        "resources/container/well/well",
        # Deck
        "resources/deck/deck",
        # Itemized resources (Plate, TipRack)
        "resources/itemized-resource/itemized-resource",
        "resources/itemized-resource/plate/plate",
        "resources/itemized-resource/plate/definition-plate",
        "resources/itemized-resource/plate/plate-quadrants",
        "resources/itemized-resource/tiprack/tiprack",
        # Resource holder
        "resources/resource-holder/resource-holder",
        "resources/resource-holder/plate-holder",
        # Plate adapter
        "resources/plate-adapter/plate-adapter",
        # Resource stack
        "resources/resource-stack/resource-stack",
    ],
    "04-resources-library": [
        "resources/library/agenbio",
        "resources/library/agilent",
        "resources/library/alpaqua",
        "resources/library/azenta",
        "resources/library/bioer",
        "resources/library/biorad",
        "resources/library/boekel",
        "resources/library/celltreat",
        "resources/library/cellvis",
        "resources/library/corning",
        "resources/library/eppendorf",
        "resources/library/falcon",
        "resources/library/greiner",
        "resources/library/hamilton",
        "resources/library/imcs",
        "resources/library/nest",
        "resources/library/opentrons",
        "resources/library/perkin_elmer",
        "resources/library/pioreactor",
        "resources/library/porvair",
        "resources/library/revvity",
        "resources/library/sergi",
        "resources/library/thermo_fisher",
        "resources/library/vwr",
        "resources/library/diy/index",
        "resources/library/diy/davidnedrud",
        "resources/library/diy/grindbio",
    ],
    "05-contributor-guide": [
        "contributor_guide/index",
        "contributor_guide/contributing",
        "contributor_guide/how-to-open-source",
        "contributor_guide/contributing-to-docs",
        "contributor_guide/device-driver-guide",
        "contributor_guide/contributing-new-resources",
        "contributor_guide/visualizer",
        "contributor_guide/adding-coookbook-recipes",
    ],
    "06-cookbook": [
        "cookbook/index",
        "cookbook/star_movement_plate_to_alpaqua_core",
        "cookbook/slack_notifications",
    ],
    "07-community-and-index": [
        "index",
        "community-protocols/index",
    ],
}

# Extensions to try, in order (ipynb is last because it's less common)
EXTENSIONS_TO_TRY = (".md.txt", ".rst.txt", ".ipynb.txt")


def guess_extension(slug: str) -> str | None:
    """Try HTTP HEAD to find the correct source extension for a doc page."""
    for ext in EXTENSIONS_TO_TRY:
        url = f"{BASE_URL}/{slug}{ext}"
        try:
            req = urllib.request.Request(url, method="HEAD")
            req.add_header("User-Agent", "pylabrobot-doc-downloader/1.0")
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status == 200:
                    return ext
        except Exception:
            continue
    return None


def download_one(slug: str, ext: str) -> bool:
    """Download a single source file into RAW_DIR. Returns True on success."""
    url = f"{BASE_URL}/{slug}{ext}"
    out_path = RAW_DIR / f"{slug}{ext}"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "pylabrobot-doc-downloader/1.0")
        with urllib.request.urlopen(req, timeout=30) as resp:
            content = resp.read()

        with open(out_path, "wb") as f:
            f.write(content)
        return True
    except Exception as e:
        print(f"    FAIL [{slug}{ext}]: {e}")
        return False


def merge_group(group_name: str, slugs: list[str], ext_map: dict[str, str]) -> int:
    """Merge downloaded source files into a single group .txt file. Returns line count."""
    group_title = group_name.split("-", 1)[1].replace("-", " ").title()
    out_path = SEARCH_DIR / f"{group_name}.txt"
    doc_count = 0

    with open(out_path, "w", encoding="utf-8") as out:
        out.write(f"# {group_title}\n")
        out.write(f"# Group: {group_name}\n")
        out.write(f"# Source: {BASE_URL}/\n\n")

        for slug in slugs:
            ext = ext_map.get(slug)
            if not ext:
                continue
            src_path = RAW_DIR / f"{slug}{ext}"
            if not src_path.exists():
                continue

            source_url = f"{BASE_URL}/{slug}{ext}"
            out.write(f"\n{'=' * 70}\n")
            out.write(f"DOC: {slug}\n")
            out.write(f"SOURCE: https://docs.pylabrobot.org/dev/{slug}.html\n")
            out.write(f"RAW: {source_url}\n")
            out.write(f"{'=' * 70}\n\n")

            try:
                with open(src_path, encoding="utf-8", errors="replace") as f:
                    out.write(f.read())
            except Exception as e:
                out.write(f"[Error reading source: {e}]\n")

            out.write("\n")
            doc_count += 1

    lines = sum(1 for _ in open(out_path, encoding="utf-8", errors="replace"))
    print(f"  {group_name}.txt: {doc_count} docs, {lines} lines")
    return lines


def main() -> None:
    # Clean and recreate directories
    if SEARCH_DIR.exists():
        print("Cleaning existing search/ directory...")
        shutil.rmtree(SEARCH_DIR)
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    # Collect all unique slugs
    all_slugs: list[str] = []
    seen: set[str] = set()
    for slugs in GROUPS.values():
        for slug in slugs:
            if slug not in seen:
                seen.add(slug)
                all_slugs.append(slug)

    print(f"Total unique pages to download: {len(all_slugs)}")
    print(f"Docs source: {BASE_URL}/\n")

    # --- Phase 1: Discover extensions ---
    print("=" * 60)
    print("Phase 1: Discovering file extensions (HEAD requests)...")
    print("=" * 60)
    ext_map: dict[str, str] = {}
    unknown: list[str] = []

    for i, slug in enumerate(all_slugs):
        ext = guess_extension(slug)
        if ext:
            ext_map[slug] = ext
        else:
            unknown.append(slug)
            print(f"  ? UNKNOWN: {slug} (tried: {', '.join(EXTENSIONS_TO_TRY)})")

        if (i + 1) % 20 == 0:
            print(f"  ... {i + 1}/{len(all_slugs)} checked")

    print(f"\nExtension discovery done: {len(ext_map)} found, {len(unknown)} unknown")
    if unknown:
        print("Unknown pages (will be skipped):")
        for slug in unknown:
            print(f"  - {slug}")

    # --- Phase 2: Download ---
    print(f"\n{'=' * 60}")
    print("Phase 2: Downloading source files...")
    print("=" * 60)
    success = 0
    fail = 0

    for i, (slug, ext) in enumerate(sorted(ext_map.items())):
        ok = download_one(slug, ext)
        if ok:
            success += 1
        else:
            fail += 1

        if (i + 1) % 20 == 0:
            print(f"  ... {i + 1}/{len(ext_map)} downloaded ({success} ok, {fail} fail)")

    print(f"\nDownload done: {success} ok, {fail} fail out of {len(ext_map)}")

    # --- Phase 3: Merge ---
    print(f"\n{'=' * 60}")
    print("Phase 3: Merging into group search files...")
    print("=" * 60)
    total_lines = 0
    total_docs = 0
    for group_name, slugs in GROUPS.items():
        lines = merge_group(group_name, slugs, ext_map)
        total_lines += lines
        total_docs += sum(1 for s in slugs if ext_map.get(s) and (RAW_DIR / f"{s}{ext_map[s]}").exists())

    print(f"\n{'=' * 60}")
    print(f"Done! {total_docs} documents merged into {len(GROUPS)} search files")
    print(f"Total lines: {total_lines}")
    print(f"Search files in: {SEARCH_DIR}")
    print(f"Raw sources in: {RAW_DIR}")


if __name__ == "__main__":
    main()
