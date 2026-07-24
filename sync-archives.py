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
        Path("gpt-5.6-sol-unrestricted-v41.md"),
        Path("gpt-5.6-sol-unrestricted-v41.zip"),
        "gpt-5.6-sol-unrestricted-v41.md",
    ),
    (
        Path("gpt-5.6-sol-unrestricted-v41-skills.md"),
        Path("gpt-5.6-sol-unrestricted-v41-skills.zip"),
        "gpt-5.6-sol-unrestricted-v41-skills.md",
    ),
    (
        Path("examples/gpt-5.6-sol-unrestricted.md"),
        Path("examples/gpt-5.6-sol-unrestricted.zip"),
        "gpt-5.6-sol-unrestricted.md",
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


def expected_archive_contents() -> list[tuple[Path, str]]:
    """Map every committed archive to the single file it must contain.

    Unlike ``archive_specs``, this needs no local sources, so it can run in a
    clean CI checkout where the sensitive ``.md``/``scripts/*.py`` sources are
    git-ignored and absent. Prompt archives use the explicit PROMPT_ARCHIVES
    mapping; each ``scripts/<name>.zip`` must contain ``<name>.py``.
    """
    contents = [
        (PROJECT_ROOT / destination, archive_name)
        for _source, destination, archive_name in PROMPT_ARCHIVES
    ]
    contents.extend(
        (archive, f"{archive.stem}.py")
        for archive in sorted((PROJECT_ROOT / "scripts").glob("*.zip"))
    )
    return contents


def verify_archive_structure() -> int:
    """Check that every committed archive is a valid single-file ZIP.

    This guards against corruption, a wrong inner filename, or an accidental
    multi-file archive. It cannot detect content drift from the local source
    (that requires the git-ignored sources and is what ``--check`` is for).
    """
    failed = False
    for destination, archive_name in expected_archive_contents():
        relative = destination.relative_to(PROJECT_ROOT)
        try:
            with zipfile.ZipFile(destination) as archive:
                names = [name for name in archive.namelist() if not name.endswith("/")]
                ok = names == [archive_name]
        except FileNotFoundError:
            print(f"[缺失] {relative}", file=sys.stderr)
            failed = True
            continue
        except zipfile.BadZipFile:
            print(f"[损坏] {relative}", file=sys.stderr)
            failed = True
            continue
        if ok:
            print(f"[OK] {relative}")
        else:
            print(
                f"[结构错误] {relative} 应恰好包含 {archive_name}，实际为 {names}",
                file=sys.stderr,
            )
            failed = True
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Update release, history, example, and test-script ZIP archives."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify that every archive exists and exactly matches its local source.",
    )
    parser.add_argument(
        "--verify-archives",
        action="store_true",
        help=(
            "Source-free structural check: confirm every committed archive is a "
            "valid single-file ZIP with the expected inner name. Safe for CI."
        ),
    )
    args = parser.parse_args()

    if args.verify_archives:
        return verify_archive_structure()

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
        if args.check:
            try:
                with zipfile.ZipFile(destination) as archive:
                    names = [name for name in archive.namelist() if not name.endswith("/")]
                    matches = (
                        names == [archive_name]
                        and archive.read(archive_name) == source.read_bytes()
                    )
            except (FileNotFoundError, KeyError, zipfile.BadZipFile):
                matches = False
            print(f"[{'OK' if matches else '过期'}] {relative_destination}")
            failed |= not matches
        else:
            write_single_file_archive(source, destination, archive_name)
            print(f"[已同步] {relative_source} -> {relative_destination}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
