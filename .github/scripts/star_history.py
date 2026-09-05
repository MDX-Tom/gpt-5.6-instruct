#!/usr/bin/env python3
"""Maintain and render Star History without a hosted chart service.

The three subcommands form one pipeline:

* ``refresh-data`` extends the public date/count cache with one GitHub
  repository-metadata request;
* ``patch-upstream`` seeds a pinned official backend from that local cache;
* ``render`` validates and saves the official localhost-rendered SVG pair.

The official JSDOM, XYChart, xkcd styling, theme logic, and SVGO rendering path
remain unchanged.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


DEFAULT_BACKEND_URL = "http://127.0.0.1:8080"
DEFAULT_REPOSITORY = "mdx-tom/gpt-instruct"
SCHEMA_VERSION = 1
THEMES = ("light", "dark")

# One retry covers a short runner-local startup/readiness race. The backend is
# seeded from local data and therefore performs no stargazers API fan-out.
LOCAL_RENDER_ATTEMPTS = 2
# The fallback fetches the last-deployed pair from this project's Pages CDN,
# where retries usefully ride out short-lived network hiccups.
FALLBACK_RENDER_ATTEMPTS = 4

MAIN_PATH = Path("backend/main.ts")


class RepositoryMismatchError(ValueError):
    """The deployed cache belongs to a repository identity we must not merge."""

STARTUP_ORIGINAL = """const startServer = async () => {
  await initTokenFromEnv();
  initOgAssets();
  const repoStore = loadRepos();

  const app = new Hono();"""

STARTUP_PATCHED = """const startServer = async () => {
  const seedPath = process.env.STAR_HISTORY_DATA_PATH;
  if (!seedPath) {
    await initTokenFromEnv();
  }
  initOgAssets();
  const repoStore = loadRepos();

  if (seedPath) {
    const fs = await import("node:fs");
    const seed = JSON.parse(fs.readFileSync(seedPath, "utf8"));
    const repository = String(seed.repository || "").toLowerCase();
    const starRecords = seed.star_records;
    const logoUrl = String(seed.logo_url || "");
    if (!repository || !Array.isArray(starRecords) || starRecords.length === 0 || !logoUrl) {
      throw new Error("Invalid STAR_HISTORY_DATA_PATH payload");
    }
    cache.set(repository, {
      starRecords,
      starAmount: starRecords[starRecords.length - 1].count,
      logoUrl,
    });
    logger.info(`Loaded ${starRecords.length} local Star History records for ${repository}`);
  }

  const app = new Hono();"""


# ---------------------------------------------------------------------------
# Shared command-line interface
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    refresh = commands.add_parser(
        "refresh-data",
        help="Update the local date/count cache from GitHub repository metadata",
    )
    refresh.add_argument("--repository", default=DEFAULT_REPOSITORY)
    refresh.add_argument("--seed-file", type=Path, required=True)
    refresh.add_argument("--deployed-url")
    refresh.add_argument("--output", type=Path, required=True)
    refresh.add_argument(
        "--token-env",
        default="GITHUB_TOKEN",
        help="Environment variable containing a GitHub token",
    )

    patch_parser = commands.add_parser(
        "patch-upstream",
        help="Patch the pinned official backend to load the local cache",
    )
    patch_parser.add_argument(
        "--source-dir",
        type=Path,
        required=True,
        help="Path to the checked-out star-history/star-history source",
    )

    render = commands.add_parser(
        "render",
        help="Save light and dark SVGs produced by the local official backend",
    )
    render.add_argument(
        "--backend-url",
        default=os.environ.get("STAR_HISTORY_BACKEND_URL", DEFAULT_BACKEND_URL),
        help="Local official backend origin (default: %(default)s)",
    )
    render.add_argument(
        "--repository",
        default=os.environ.get("STAR_HISTORY_REPOSITORY", DEFAULT_REPOSITORY),
        help="GitHub repository in owner/name form (default: %(default)s)",
    )
    render.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".star-history-site"),
        help="Directory that receives the two SVG files (default: %(default)s)",
    )
    render.add_argument(
        "--fallback-base-url",
        default=os.environ.get("STAR_HISTORY_FALLBACK_BASE_URL"),
        help=(
            "Base URL containing this project's last deployed light/dark SVG pair"
        ),
    )
    return parser


# ---------------------------------------------------------------------------
# History data cache
# ---------------------------------------------------------------------------


def parse_record_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y/%m/%d %H:%M:%S").replace(
        tzinfo=timezone.utc
    )


def format_record_date(value: datetime) -> str:
    current = value.astimezone(timezone.utc)
    return "{0}/{1}/{2} {3}:{4}:{5}".format(
        current.year,
        current.month,
        current.day,
        current.hour,
        current.minute,
        current.second,
    )


def validate_data(payload: Any, repository: str) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Star History data must be a JSON object")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported Star History data schema")
    if str(payload.get("repository", "")).lower() != repository.lower():
        raise RepositoryMismatchError(
            "Star History data targets a different repository"
        )
    logo_url = payload.get("logo_url")
    if not isinstance(logo_url, str) or not logo_url.startswith("data:image/"):
        raise ValueError("Star History data is missing an embedded logo")

    records = payload.get("star_records")
    if not isinstance(records, list) or len(records) < 2:
        raise ValueError("Star History data requires at least two records")
    previous_date: Optional[datetime] = None
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("Star History record must be an object")
        date_value = record.get("date")
        if not isinstance(date_value, str):
            raise ValueError("Star History record date must be a string")
        date = parse_record_date(date_value)
        count = record.get("count")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError("Star History record count must be a non-negative integer")
        if previous_date is not None and date <= previous_date:
            raise ValueError("Star History records must be strictly chronological")
        previous_date = date
    return payload


def read_json_file(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def download_json(url: str) -> Dict[str, Any]:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("deployed data URL must use HTTPS")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "MDX-Tom/gpt-instruct Star History updater"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def load_best_data(
    *,
    repository: str,
    seed_file: Path,
    deployed_url: Optional[str],
) -> Tuple[Dict[str, Any], str]:
    if deployed_url:
        try:
            deployed = validate_data(download_json(deployed_url), repository)
            return deployed, "deployed Pages data"
        except RepositoryMismatchError:
            # A repository rename leaves the old Pages deployment reachable at
            # the new URL until this workflow publishes once. Never merge that
            # differently identified cache; bootstrap the renamed repository
            # from its committed, independently validated seed instead.
            print(
                "[data] deployed cache belongs to a previous repository "
                "identity; using repository seed"
            )
        except urllib.error.HTTPError as exc:
            try:
                status = exc.code
            finally:
                exc.close()
            if status != 404:
                raise RuntimeError(
                    "deployed Pages cache request failed; preserving the last "
                    "deployment: HTTP {0}".format(status)
                ) from exc
            print("[data] deployed cache not found; using repository seed")
        except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError) as exc:
            raise RuntimeError(
                "deployed Pages cache is unavailable or invalid; preserving "
                "the last deployment: {0}".format(exc)
            ) from exc
    seed = validate_data(read_json_file(seed_file), repository)
    return seed, "repository seed"


def fetch_repository_star_count(repository: str, token: str) -> int:
    url = "https://api.github.com/repos/{0}".format(repository)
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer {0}".format(token),
            "User-Agent": "MDX-Tom/gpt-instruct Star History updater",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    last_error: Optional[Exception] = None
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            count = payload.get("stargazers_count")
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise ValueError("GitHub metadata omitted stargazers_count")
            return count
        except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError) as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(attempt * 2)
    raise RuntimeError("GitHub repository metadata request failed: {0}".format(last_error))


def update_current_record(
    payload: Dict[str, Any],
    *,
    repository: str,
    star_count: int,
    current_time: datetime,
) -> Dict[str, Any]:
    updated = copy.deepcopy(payload)
    validate_data(updated, repository)
    current = current_time.astimezone(timezone.utc)
    record = {"date": format_record_date(current), "count": star_count}
    records = updated["star_records"]
    if parse_record_date(records[-1]["date"]).date() == current.date():
        if records[-1]["count"] == star_count:
            return updated
        records[-1] = record
    else:
        records.append(record)
    updated["updated_at"] = current.isoformat().replace("+00:00", "Z")
    validate_data(updated, repository)
    return updated


def atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix=path.name + ".",
        suffix=".tmp",
        dir=path.parent,
        delete=False,
    ) as temporary:
        temporary.write(content)
        temporary_path = Path(temporary.name)
    temporary_path.replace(path)
    path.chmod(0o644)


def refresh_data_command(args: argparse.Namespace) -> int:
    repository = args.repository.strip().lower()
    token = os.environ.get(args.token_env, "").strip()
    if repository.count("/") != 1:
        print("[error] repository must use owner/name format")
        return 1
    if not token:
        print("[error] GitHub token environment variable is empty")
        return 1
    try:
        payload, source = load_best_data(
            repository=repository,
            seed_file=args.seed_file,
            deployed_url=args.deployed_url,
        )
        count = fetch_repository_star_count(repository, token)
        updated = update_current_record(
            payload,
            repository=repository,
            star_count=count,
            current_time=datetime.now(timezone.utc),
        )
        atomic_write_json(args.output, updated)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print("[error] Star History data refresh failed: {0}".format(exc))
        return 1
    print(
        "[data] {0}: {1} stars from {2} ({3} records)".format(
            repository,
            count,
            source,
            len(updated["star_records"]),
        )
    )
    return 0


# ---------------------------------------------------------------------------
# Guarded official-backend patch
# ---------------------------------------------------------------------------


def replace_exactly_once(
    path: Path,
    original: str,
    replacement: str,
    description: str,
) -> bool:
    """Replace one pinned-upstream fragment and reject silent source drift."""
    source = path.read_text(encoding="utf-8")
    original_count = source.count(original)
    replacement_count = source.count(replacement)

    if original_count == 0 and replacement_count == 1:
        return False
    if original_count != 1 or replacement_count != 0:
        raise RuntimeError(
            "unexpected upstream implementation for {0} in {1} "
            "(original={2}, patched={3})".format(
                description,
                path,
                original_count,
                replacement_count,
            )
        )

    path.write_text(source.replace(original, replacement), encoding="utf-8")
    return True


def patch_upstream(source_dir: Path) -> List[Path]:
    """Patch the pinned checkout and return the files changed in this call."""
    path = source_dir / MAIN_PATH
    if not path.is_file():
        raise RuntimeError("missing pinned upstream file: {0}".format(path))
    changed = replace_exactly_once(
        path,
        STARTUP_ORIGINAL,
        STARTUP_PATCHED,
        "local data cache seed",
    )
    return [MAIN_PATH] if changed else []


def patch_upstream_command(args: argparse.Namespace) -> int:
    try:
        changed = patch_upstream(args.source_dir)
    except (OSError, RuntimeError) as exc:
        print("[error] Star History upstream patch failed: {0}".format(exc))
        return 1

    if changed:
        for path in changed:
            print("[patched] {0}".format(path))
    else:
        print("[current] Star History upstream patch is already applied")
    return 0


# ---------------------------------------------------------------------------
# Official localhost SVG rendering and pair fallback
# ---------------------------------------------------------------------------


def validate_local_backend_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value.rstrip("/"))
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("backend URL must point to a local HTTP server")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("backend URL must be an origin without a path or query")
    return value.rstrip("/")


def validate_fallback_base_url(value: str) -> str:
    normalized = value.rstrip("/")
    parsed = urllib.parse.urlsplit(normalized)
    is_local_http = parsed.scheme == "http" and parsed.hostname in {
        "127.0.0.1",
        "localhost",
    }
    if parsed.scheme != "https" and not is_local_http:
        raise ValueError("fallback URL must use HTTPS or local HTTP")
    if not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("fallback URL must contain a host without credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("fallback URL must not contain a query or fragment")
    return normalized


def chart_url(backend_url: str, repository: str, theme: str) -> str:
    params = {
        "repos": repository.lower(),
        "type": "date",
        "legend": "top-left",
    }
    if theme == "dark":
        params["theme"] = "dark"
    return "{0}/svg?{1}".format(backend_url, urllib.parse.urlencode(params))


def fallback_chart_url(base_url: str, theme: str) -> str:
    return "{0}/star-history-{1}.svg".format(base_url, theme)


def emit_github_warning(message: str) -> None:
    """Surface a degraded refresh as an Actions annotation."""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    single_line = message.replace("\r", " ").replace("\n", " ")
    print("::warning title=Star History::{0}".format(single_line))


def download_svg(url: str, attempts: int = 4) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "image/svg+xml",
            "User-Agent": "MDX-Tom/gpt-instruct local Star-History renderer",
        },
    )
    last_error: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                content_type = response.headers.get("Content-Type", "").lower()
                body = response.read()
            if "svg" not in content_type:
                raise ValueError(
                    "unexpected Content-Type: {0}".format(
                        content_type or "(missing)"
                    )
                )
            return body
        except urllib.error.HTTPError as exc:
            try:
                response_body = exc.read().decode("utf-8", errors="replace").strip()
            finally:
                exc.close()
            detail = "HTTP {0} {1}".format(exc.code, exc.reason)
            if response_body:
                detail += ": {0}".format(response_body)
            last_error = RuntimeError(detail)
            if attempt == attempts:
                break
            time.sleep(attempt * 2)
        except (OSError, ValueError, urllib.error.URLError) as exc:
            last_error = exc
            if attempt == attempts:
                break
            time.sleep(attempt * 2)
    raise RuntimeError("local Star History backend request failed: {0}".format(last_error))


def validate_svg(content: bytes, repository: str, theme: str) -> None:
    if len(content) < 10_000:
        raise ValueError("SVG is unexpectedly small: {0} bytes".format(len(content)))
    root = ET.fromstring(content)
    if root.tag.rsplit("}", 1)[-1] != "svg":
        raise ValueError("document root is not SVG: {0}".format(root.tag))
    if root.attrib.get("width") != "800" or root.attrib.get("height") != "533.333":
        raise ValueError(
            "official laptop chart dimensions changed: {0}x{1}".format(
                root.attrib.get("width"),
                root.attrib.get("height"),
            )
        )

    text = content.decode("utf-8")
    required_fragments = (
        "Star History",
        "GitHub Stars",
        repository.lower(),
        "xkcdify",
        "font-family:xkcd",
    )
    missing = [fragment for fragment in required_fragments if fragment not in text]
    if missing:
        raise ValueError(
            "SVG is missing official chart markers: {0}".format(", ".join(missing))
        )

    expected_background = "background:#0d1117" if theme == "dark" else "background:#fff"
    if expected_background not in text:
        raise ValueError("SVG does not contain the expected {0} theme".format(theme))


def atomic_write_svg(destination: Path, content: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb",
        prefix=destination.name + ".",
        suffix=".tmp",
        dir=destination.parent,
        delete=False,
    ) as temporary:
        temporary.write(content)
        temporary_path = Path(temporary.name)
    temporary_path.replace(destination)
    destination.chmod(0o644)
    print("[rendered] {0} ({1} bytes)".format(destination, len(content)))


def fetch_chart_pair(
    *,
    repository: str,
    url_for_theme,
    attempts: int,
) -> Dict[str, bytes]:
    charts = {}
    for theme in THEMES:
        content = download_svg(url_for_theme(theme), attempts=attempts)
        validate_svg(content, repository, theme)
        charts[theme] = content
    return charts


def render_command(args: argparse.Namespace) -> int:
    try:
        backend_url = validate_local_backend_url(args.backend_url)
        repository = args.repository.strip().lower()
        if repository.count("/") != 1:
            raise ValueError("repository must use owner/name format")

        try:
            charts = fetch_chart_pair(
                repository=repository,
                url_for_theme=lambda theme: chart_url(
                    backend_url,
                    repository,
                    theme,
                ),
                attempts=LOCAL_RENDER_ATTEMPTS,
            )
        except (RuntimeError, OSError, ValueError, ET.ParseError) as local_error:
            if not args.fallback_base_url:
                raise
            fallback_base_url = validate_fallback_base_url(args.fallback_base_url)
            warning = (
                "Local Star History refresh failed; reusing the last deployed "
                "chart pair: {0}".format(local_error)
            )
            print("[warning] {0}".format(warning), file=sys.stderr)
            emit_github_warning(warning)
            charts = fetch_chart_pair(
                repository=repository,
                url_for_theme=lambda theme: fallback_chart_url(
                    fallback_base_url,
                    theme,
                ),
                attempts=FALLBACK_RENDER_ATTEMPTS,
            )

        # Write only after both themes validate, preventing a mixed fresh/stale pair.
        for theme in THEMES:
            atomic_write_svg(
                args.output_dir / "star-history-{0}.svg".format(theme),
                charts[theme],
            )
    except (RuntimeError, OSError, ValueError, ET.ParseError) as exc:
        print("[error] Star History rendering failed: {0}".format(exc), file=sys.stderr)
        return 1
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "refresh-data":
        return refresh_data_command(args)
    if args.command == "patch-upstream":
        return patch_upstream_command(args)
    if args.command == "render":
        return render_command(args)
    raise RuntimeError("unknown Star History command: {0}".format(args.command))


if __name__ == "__main__":
    raise SystemExit(main())
