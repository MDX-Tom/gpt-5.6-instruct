#!/usr/bin/env python3
"""Synchronize public ZIP archives from local Markdown/Python sources."""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
PROMPT_ARCHIVES = (
    (
        Path("gpt-6-astra-v1-rc1.md"),
        Path("gpt-6-astra-v1-rc1.zip"),
        "gpt-6-astra-v1-rc1.md",
    ),
    (
        Path("gpt-5.6-sol-v45.md"),
        Path("gpt-5.6-sol-v45.zip"),
        # Preserve the released ZIP bytes and its historical single member.
        "gpt-5.6-sol-unrestricted-v45.md",
    ),
    (
        Path("historical-versions/gpt-5.6-sol-unrestricted-v42.md"),
        Path("historical-versions/gpt-5.6-sol-unrestricted-v42.zip"),
        "gpt-5.6-sol-unrestricted-v42.md",
    ),
    (
        Path("historical-versions/gpt-5.6-sol-unrestricted-v41.md"),
        Path("historical-versions/gpt-5.6-sol-unrestricted-v41.zip"),
        "gpt-5.6-sol-unrestricted-v41.md",
    ),
    (
        Path("historical-versions/gpt-5.6-sol-unrestricted-v41-skills.md"),
        Path("historical-versions/gpt-5.6-sol-unrestricted-v41-skills.zip"),
        "gpt-5.6-sol-unrestricted-v41-skills.md",
    ),
    (
        Path("historical-versions/gpt-5.6-sol-unrestricted-v5.md"),
        Path("historical-versions/gpt-5.6-sol-unrestricted-v5.zip"),
        "gpt-5.6-sol-unrestricted-v5.md",
    ),
    (
        Path("reports/prompt_candidates/gpt-5.6-sol-unrestricted-v24.md"),
        Path("historical-versions/gpt-5.6-sol-unrestricted-v24.zip"),
        "gpt-5.6-sol-unrestricted-v24.md",
    ),
    (
        Path("reports/prompt_candidates/gpt-5.6-sol-unrestricted-v35.md"),
        Path("historical-versions/gpt-5.6-sol-unrestricted-v35.zip"),
        "gpt-5.6-sol-unrestricted-v35.md",
    ),
)


def write_single_file_archive(source: Path, destination: Path, archive_name: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    with zipfile.ZipFile(
        temporary,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        archive.write(source, arcname=archive_name)
    temporary.replace(destination)


def archive_matches_source(
    source: Path,
    destination: Path,
    archive_name: str,
) -> bool:
    """Compare member name/content without rewriting reproducible release bytes."""
    try:
        with zipfile.ZipFile(destination) as archive:
            names = [name for name in archive.namelist() if not name.endswith("/")]
            return (
                names == [archive_name]
                and archive.read(archive_name) == source.read_bytes()
            )
    except (FileNotFoundError, KeyError, zipfile.BadZipFile):
        return False


def archive_specs() -> list[tuple[Path, Path, str]]:
    prompt_specs = [
        (PROJECT_ROOT / source, PROJECT_ROOT / destination, archive_name)
        for source, destination, archive_name in PROMPT_ARCHIVES
    ]
    script_specs = [
        (source, source.with_suffix(".zip"), source.name)
        for source in sorted((PROJECT_ROOT / "scripts").glob("*.py"))
    ]
    return prompt_specs + script_specs


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Update release, history, example, and test-script ZIP archives."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify that every archive exists and exactly matches its local source.",
    )
    args = parser.parse_args()

    specs = archive_specs()
    missing = [source for source, _destination, _name in specs if not source.is_file()]
    if missing:
        for path in missing:
            print(f"[错误] 缺少源文件: {path.relative_to(PROJECT_ROOT)}", file=sys.stderr)
        return 2

    failed = False
    for source, destination, archive_name in specs:
        relative_source = source.relative_to(PROJECT_ROOT)
        relative_destination = destination.relative_to(PROJECT_ROOT)
        matches = archive_matches_source(source, destination, archive_name)
        if args.check:
            print(f"[{'OK' if matches else '过期'}] {relative_destination}")
            failed |= not matches
        elif matches:
            print(f"[未变] {relative_source} -> {relative_destination}")
        else:
            write_single_file_archive(source, destination, archive_name)
            print(f"[已同步] {relative_source} -> {relative_destination}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
