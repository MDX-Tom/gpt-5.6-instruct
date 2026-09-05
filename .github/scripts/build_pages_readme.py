#!/usr/bin/env python3
"""Build bilingual GitHub Pages HTML from README.md and README_EN.md."""

from __future__ import annotations

import argparse
import hashlib
import html
import shutil
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

try:
    import markdown
except ImportError as exc:  # pragma: no cover - exercised by the workflow setup
    raise SystemExit("Python package 'Markdown' is required") from exc


DEFAULT_REPOSITORY = "MDX-Tom/gpt-instruct"
DEFAULT_BRANCH = "main"
DEFAULT_PAGES_URL = "https://mdx-tom.github.io/gpt-instruct"

PAGE_STYLES = r"""
:root {
  color-scheme: light dark;
  --page-bg: #ffffff;
  --text: #1f2328;
  --muted: #59636e;
  --border: #d1d9e0;
  --soft-bg: #f6f8fa;
  --link: #0969da;
  --quote: #656d76;
}
@media (prefers-color-scheme: dark) {
  :root {
    --page-bg: #0d1117;
    --text: #f0f6fc;
    --muted: #9198a1;
    --border: #3d444d;
    --soft-bg: #151b23;
    --link: #4493f8;
    --quote: #9198a1;
  }
}
* { box-sizing: border-box; }
html { background: var(--page-bg); }
body {
  margin: 0;
  background: var(--page-bg);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  font-size: 16px;
  line-height: 1.5;
}
.markdown-body {
  max-width: 1012px;
  margin: 0 auto;
  padding: 48px 45px 72px;
  overflow-wrap: break-word;
}
.markdown-body h1, .markdown-body h2, .markdown-body h3,
.markdown-body h4, .markdown-body h5, .markdown-body h6 {
  margin-top: 24px;
  margin-bottom: 16px;
  font-weight: 600;
  line-height: 1.25;
}
.markdown-body h1, .markdown-body h2 {
  padding-bottom: .3em;
  border-bottom: 1px solid var(--border);
}
.markdown-body h1 { font-size: 2em; }
.markdown-body h2 { font-size: 1.5em; }
.markdown-body h3 { font-size: 1.25em; }
.markdown-body p, .markdown-body blockquote, .markdown-body ul,
.markdown-body ol, .markdown-body dl, .markdown-body table,
.markdown-body pre, .markdown-body details { margin: 0 0 16px; }
.markdown-body a { color: var(--link); text-decoration: none; }
.markdown-body a:hover { text-decoration: underline; }
.markdown-body img, .markdown-body svg { max-width: 100%; height: auto; }
.markdown-body blockquote {
  padding: 0 1em;
  color: var(--quote);
  border-left: .25em solid var(--border);
}
.markdown-body code {
  padding: .2em .4em;
  border-radius: 6px;
  background: var(--soft-bg);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 85%;
}
.markdown-body pre {
  padding: 16px;
  overflow: auto;
  border-radius: 6px;
  background: var(--soft-bg);
}
.markdown-body pre code { padding: 0; background: transparent; font-size: 100%; }
.markdown-body table { display: block; width: max-content; max-width: 100%; overflow: auto; border-spacing: 0; border-collapse: collapse; }
.markdown-body th, .markdown-body td { padding: 6px 13px; border: 1px solid var(--border); }
.markdown-body tr:nth-child(2n) { background: var(--soft-bg); }
.markdown-body hr { height: .25em; padding: 0; margin: 24px 0; background: var(--border); border: 0; }
.markdown-body li + li { margin-top: .25em; }
@media (max-width: 767px) {
  .markdown-body { padding: 24px 16px 48px; }
  .markdown-body h1 { font-size: 1.7em; }
  .markdown-body h2 { font-size: 1.35em; }
}
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--branch", default=DEFAULT_BRANCH)
    parser.add_argument("--pages-url", default=DEFAULT_PAGES_URL)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    return parser.parse_args()


class PageLinkRewriter(HTMLParser):
    def __init__(
        self,
        *,
        repo_root: Path,
        repository: str,
        branch: str,
        pages_url: str,
    ) -> None:
        super().__init__(convert_charrefs=False)
        self.repo_root = repo_root.resolve()
        self.repository = repository
        self.branch = branch
        self.pages_url = pages_url.rstrip("/")
        self.parts: list[str] = []

    def rewrite_href(self, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme or parsed.netloc or value.startswith(("#", "/")):
            return value

        if parsed.path == "README.md":
            local_page = "index.html"
        elif parsed.path == "README_EN.md":
            local_page = "README_EN.html"
        else:
            relative_path = Path(parsed.path)
            candidate = (self.repo_root / relative_path).resolve()
            try:
                candidate.relative_to(self.repo_root)
            except ValueError:
                return value
            view = "tree" if candidate.is_dir() else "blob"
            encoded_path = quote(relative_path.as_posix(), safe="/")
            local_page = (
                f"https://github.com/{self.repository}/{view}/{self.branch}/{encoded_path}"
            )
        return urlunsplit(("", "", local_page, parsed.query, parsed.fragment))

    def rewrite_asset(self, value: str) -> str:
        prefix = self.pages_url + "/"
        return value[len(prefix) :] if value.startswith(prefix) else value

    def rewrite_srcset(self, value: str) -> str:
        entries = []
        for entry in value.split(","):
            fields = entry.strip().split(maxsplit=1)
            if not fields:
                continue
            fields[0] = self.rewrite_asset(fields[0])
            entries.append(" ".join(fields))
        return ", ".join(entries)

    def format_tag(self, tag: str, attrs: list[tuple[str, str | None]], close: bool) -> str:
        rendered_attrs = []
        for key, value in attrs:
            if value is None:
                rendered_attrs.append(key)
                continue
            if key == "href":
                value = self.rewrite_href(value)
            elif key == "src":
                value = self.rewrite_asset(value)
            elif key == "srcset":
                value = self.rewrite_srcset(value)
            rendered_attrs.append(f'{key}="{html.escape(value, quote=True)}"')
        suffix = " /" if close else ""
        attributes = " " + " ".join(rendered_attrs) if rendered_attrs else ""
        return f"<{tag}{attributes}{suffix}>"

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.parts.append(self.format_tag(tag, attrs, False))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.parts.append(self.format_tag(tag, attrs, True))

    def handle_endtag(self, tag: str) -> None:
        self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_entityref(self, name: str) -> None:
        self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.parts.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        self.parts.append(f"<!--{data}-->")

    def handle_decl(self, decl: str) -> None:
        self.parts.append(f"<!{decl}>")

    def rewrite(self, fragment: str) -> str:
        self.feed(fragment)
        self.close()
        return "".join(self.parts)


def render_page(
    source: Path,
    destination: Path,
    *,
    language: str,
    title: str,
    repo_root: Path,
    repository: str,
    branch: str,
    pages_url: str,
) -> None:
    fragment = markdown.markdown(
        source.read_text(encoding="utf-8"),
        extensions=["extra", "sane_lists", "toc"],
        output_format="html5",
    )
    fragment = PageLinkRewriter(
        repo_root=repo_root,
        repository=repository,
        branch=branch,
        pages_url=pages_url,
    ).rewrite(fragment)
    document = f"""<!doctype html>
<html lang="{language}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light dark">
  <link rel="icon" href="data:,">
  <title>{html.escape(title)}</title>
  <style>{PAGE_STYLES}</style>
</head>
<body>
  <main class="markdown-body">{fragment}</main>
</body>
</html>
"""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(document, encoding="utf-8")
    print(f"[built] {destination}")


def write_manifest(output_dir: Path) -> None:
    manifest = output_dir / "manifest.sha256"
    lines = []
    for path in sorted(output_dir.rglob("*")):
        if not path.is_file() or path in {manifest, output_dir / ".nojekyll"}:
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.relative_to(output_dir).as_posix()}")
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[built] {manifest} ({len(lines)} files)")


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    render_page(
        repo_root / "README.md",
        output_dir / "index.html",
        language="zh-CN",
        title="Codex gpt-5.6 破甲提示词及测试包",
        repo_root=repo_root,
        repository=args.repository,
        branch=args.branch,
        pages_url=args.pages_url,
    )
    render_page(
        repo_root / "README_EN.md",
        output_dir / "README_EN.html",
        language="en",
        title="Codex gpt-5.6 Jailbreak Prompt and Test Pack",
        repo_root=repo_root,
        repository=args.repository,
        branch=args.branch,
        pages_url=args.pages_url,
    )

    images = repo_root / "docs" / "images"
    if images.is_dir():
        shutil.copytree(images, output_dir / "docs" / "images", dirs_exist_ok=True)
        print(f"[copied] {images}")

    (output_dir / ".nojekyll").touch()
    write_manifest(output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
