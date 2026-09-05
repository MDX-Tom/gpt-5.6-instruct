from __future__ import annotations

import importlib.util
import io
import json
import os
import tempfile
import threading
import unittest
import urllib.error
from contextlib import contextmanager, redirect_stdout
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_project_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


star_history = load_project_module(
    "star_history",
    PROJECT_ROOT / ".github" / "scripts" / "star_history.py",
)


def make_svg(theme: str) -> bytes:
    background = "#0d1117" if theme == "dark" else "#fff"
    padding = "x" * 10_000
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="533.333">'
        f"<style>svg{{background:{background};font-family:xkcd}}</style>"
        "<desc>Star History GitHub Stars mdx-tom/gpt-instruct xkcdify"
        f"{padding}</desc></svg>"
    ).encode("utf-8")


def make_data(
    last_count: int = 100,
    repository: str = "mdx-tom/gpt-instruct",
):
    return {
        "schema_version": 1,
        "repository": repository,
        "updated_at": "2026-07-02T00:00:00Z",
        "logo_url": "data:image/png;base64,AA==",
        "star_records": [
            {"date": "2026/7/1 0:0:0", "count": 1},
            {"date": "2026/7/2 0:0:0", "count": last_count},
        ],
    }


@contextmanager
def serve(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class FailingBackendHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(503)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"renderer unavailable")

    def log_message(self, format: str, *args) -> None:
        pass


class DeployedChartHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        theme = "dark" if self.path.endswith("star-history-dark.svg") else "light"
        content = make_svg(theme)
        self.send_response(200)
        self.send_header("Content-Type", "image/svg+xml")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format: str, *args) -> None:
        pass


def write_upstream_fixture(root: Path) -> None:
    destination = root / star_history.MAIN_PATH
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        star_history.STARTUP_ORIGINAL + "\n  return true;\n};\n",
        encoding="utf-8",
    )


class StarHistoryRendererTests(unittest.TestCase):
    # One degraded render covers the complete fallback pair and the Actions
    # annotation; the same warning helper must stay silent during local runs.
    def test_renderer_fallback_and_annotation_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            with serve(FailingBackendHandler) as backend_url, serve(
                DeployedChartHandler
            ) as fallback_url:
                argv = [
                    "star_history.py",
                    "render",
                    "--backend-url",
                    backend_url,
                    "--fallback-base-url",
                    fallback_url,
                    "--output-dir",
                    str(output_dir),
                ]
                buffer = io.StringIO()
                with patch("sys.argv", argv), patch.object(
                    star_history.time,
                    "sleep",
                    return_value=None,
                ), patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}), redirect_stdout(
                    buffer
                ):
                    self.assertEqual(star_history.main(), 0)

            self.assertEqual(
                (output_dir / "star-history-light.svg").read_bytes(),
                make_svg("light"),
            )
            self.assertEqual(
                (output_dir / "star-history-dark.svg").read_bytes(),
                make_svg("dark"),
            )
            self.assertIn("::warning title=Star History::", buffer.getvalue())

        local_buffer = io.StringIO()
        with patch.dict(os.environ, {}, clear=True), redirect_stdout(local_buffer):
            star_history.emit_github_warning("local check")
        self.assertEqual(local_buffer.getvalue(), "")


class StarHistoryDataTests(unittest.TestCase):
    # The committed bootstrap cache is the first-run source of truth, so schema
    # or repository drift must fail CI before the Pages workflow consumes it.
    def test_repository_seed_passes_schema_validation(self) -> None:
        seed_file = PROJECT_ROOT / ".github" / "data" / "star-history-data.json"
        payload = star_history.read_json_file(seed_file)
        validated = star_history.validate_data(
            payload,
            "mdx-tom/gpt-instruct",
        )
        self.assertGreaterEqual(len(validated["star_records"]), 2)
        self.assertGreater(validated["star_records"][-1]["count"], 0)

    # The updater must query only repository metadata for the current total;
    # listing individual stargazers would recreate the access/rate-limit failure.
    def test_metadata_request_does_not_list_stargazers(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self) -> bytes:
                return b'{"stargazers_count": 2841}'

        with patch.object(
            star_history.urllib.request,
            "urlopen",
            return_value=FakeResponse(),
        ) as urlopen:
            count = star_history.fetch_repository_star_count(
                "mdx-tom/gpt-instruct",
                "test-token",
            )

        request = urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "https://api.github.com/repos/mdx-tom/gpt-instruct",
        )
        self.assertNotIn("/stargazers", request.full_url)
        self.assertEqual(count, 2841)

    # Repeated 12-hour runs with an unchanged count must be byte-stable; a
    # changed same-day count replaces the point and a new UTC day appends one.
    def test_current_record_coalesces_same_day_and_appends_next_day(self) -> None:
        original = make_data(last_count=100)
        unchanged = star_history.update_current_record(
            original,
            repository="mdx-tom/gpt-instruct",
            star_count=100,
            current_time=datetime(2026, 7, 2, 12, tzinfo=timezone.utc),
        )
        self.assertEqual(unchanged, original)

        same_day = star_history.update_current_record(
            original,
            repository="mdx-tom/gpt-instruct",
            star_count=101,
            current_time=datetime(2026, 7, 2, 12, tzinfo=timezone.utc),
        )
        self.assertEqual(len(same_day["star_records"]), 2)
        self.assertEqual(same_day["star_records"][-1]["count"], 101)
        self.assertEqual(same_day["star_records"][-1]["date"], "2026/7/2 12:0:0")

        next_day = star_history.update_current_record(
            same_day,
            repository="mdx-tom/gpt-instruct",
            star_count=102,
            current_time=datetime(2026, 7, 3, 1, 2, 3, tzinfo=timezone.utc),
        )
        self.assertEqual(len(next_day["star_records"]), 3)
        self.assertEqual(next_day["star_records"][-1], {
            "date": "2026/7/3 1:2:3",
            "count": 102,
        })

    # The deployed Pages cache carries history between commit-free runs. Only a
    # first-run 404 or explicit repository rename may use the seed; transient
    # errors and malformed current-repository data must preserve live data.
    def test_deployed_data_preferred_with_guarded_seed_fallbacks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            seed_file = Path(temporary_directory) / "seed.json"
            seed_file.write_text(json.dumps(make_data(100)), encoding="utf-8")
            deployed = make_data(101)

            with patch.object(
                star_history,
                "download_json",
                return_value=deployed,
            ):
                payload, source = star_history.load_best_data(
                    repository="mdx-tom/gpt-instruct",
                    seed_file=seed_file,
                    deployed_url="https://mdx-tom.github.io/example/data.json",
                )
            self.assertEqual(payload["star_records"][-1]["count"], 101)
            self.assertEqual(source, "deployed Pages data")

            with patch.object(
                star_history, "download_json", side_effect=urllib.error.HTTPError(
                    "https://mdx-tom.github.io/example/data.json",
                    404,
                    "Not Found",
                    None,
                    io.BytesIO(b""),
                )
            ):
                payload, source = star_history.load_best_data(
                    repository="mdx-tom/gpt-instruct",
                    seed_file=seed_file,
                    deployed_url="https://mdx-tom.github.io/example/data.json",
                )
            self.assertEqual(payload["star_records"][-1]["count"], 100)
            self.assertEqual(source, "repository seed")

            renamed_repository_cache = make_data(
                99,
                repository="mdx-tom/gpt-5.6-instruct",
            )
            output = io.StringIO()
            with patch.object(
                star_history,
                "download_json",
                return_value=renamed_repository_cache,
            ), redirect_stdout(output):
                payload, source = star_history.load_best_data(
                    repository="mdx-tom/gpt-instruct",
                    seed_file=seed_file,
                    deployed_url="https://mdx-tom.github.io/example/data.json",
                )
            self.assertEqual(payload["repository"], "mdx-tom/gpt-instruct")
            self.assertEqual(payload["star_records"][-1]["count"], 100)
            self.assertEqual(source, "repository seed")
            self.assertIn("previous repository identity", output.getvalue())

            malformed_current_cache = make_data(102)
            malformed_current_cache["logo_url"] = "https://example.com/logo.png"
            with patch.object(
                star_history,
                "download_json",
                return_value=malformed_current_cache,
            ), self.assertRaisesRegex(RuntimeError, "preserving the last deployment"):
                star_history.load_best_data(
                    repository="mdx-tom/gpt-instruct",
                    seed_file=seed_file,
                    deployed_url="https://mdx-tom.github.io/example/data.json",
                )

            with patch.object(
                star_history,
                "download_json",
                side_effect=urllib.error.URLError("offline"),
            ), self.assertRaisesRegex(RuntimeError, "preserving the last deployment"):
                star_history.load_best_data(
                    repository="mdx-tom/gpt-instruct",
                    seed_file=seed_file,
                    deployed_url="https://mdx-tom.github.io/example/data.json",
                )


class StarHistoryUpstreamPatchTests(unittest.TestCase):
    # Production may use GitHub repository metadata and this project's Pages
    # cache, but neither a hosted Star History endpoint nor stargazer listing.
    def test_pipeline_contains_no_hosted_service_or_stargazer_listing(self) -> None:
        pipeline_files = (
            PROJECT_ROOT / ".github" / "scripts" / "star_history.py",
            PROJECT_ROOT / ".github" / "workflows" / "sync-star-history.yml",
        )
        combined = "\n".join(
            path.read_text(encoding="utf-8").lower() for path in pipeline_files
        )
        self.assertNotIn("api.star-history.com", combined)
        self.assertNotIn("www.star-history.com", combined)
        self.assertNotIn("/stargazers", combined)

    # The guarded adaptation must seed official cache data, bypass token setup
    # only for that mode, and remain a no-op when setup is repeated.
    def test_patch_seeds_local_cache_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            write_upstream_fixture(root)

            changed = star_history.patch_upstream(root)

            self.assertEqual(changed, [star_history.MAIN_PATH])
            source = (root / star_history.MAIN_PATH).read_text(encoding="utf-8")
            self.assertIn("process.env.STAR_HISTORY_DATA_PATH", source)
            self.assertIn("if (!seedPath) {\n    await initTokenFromEnv();", source)
            self.assertIn("cache.set(repository", source)
            self.assertIn("star_records", source)
            self.assertEqual(star_history.patch_upstream(root), [])

    # A changed upstream startup must stop the job instead of silently skipping
    # cache seeding and falling back to access-restricted stargazer requests.
    def test_patch_rejects_unexpected_upstream_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            destination = root / star_history.MAIN_PATH
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(
                "const startServer = async () => { changedUpstream(); };\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "unexpected upstream"):
                star_history.patch_upstream(root)


if __name__ == "__main__":
    unittest.main()
