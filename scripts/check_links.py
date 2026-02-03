#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urldefrag, urlparse


SKIP_SCHEMES = {"mailto", "tel", "javascript", "data", "sms", "geo", "fax"}
EXTERNAL_SCHEMES = {"http", "https"}


def parse_srcset(value: str) -> list[str]:
    urls: list[str] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        url = part.split()[0]
        if url:
            urls.append(url)
    return urls


class HTMLCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.ids: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict: dict[str, str] = {}
        for key, value in attrs:
            if not key:
                continue
            if value is None:
                continue
            attrs_dict[key.lower()] = value

        element_id = attrs_dict.get("id")
        if element_id:
            self.ids.add(element_id)
        if tag.lower() == "a":
            name = attrs_dict.get("name")
            if name:
                self.ids.add(name)

        href = attrs_dict.get("href")
        if href:
            self.links.append(href)
        src = attrs_dict.get("src")
        if src:
            self.links.append(src)
        srcset = attrs_dict.get("srcset")
        if srcset:
            self.links.extend(parse_srcset(srcset))


def parse_html(path: Path) -> tuple[list[str], set[str]]:
    parser = HTMLCollector()
    content = path.read_text(encoding="utf-8", errors="ignore")
    parser.feed(content)
    return parser.links, parser.ids


def normalize_path(path: Path) -> Path:
    return Path(os.path.normpath(str(path)))


def resolve_internal_path(url_path: str, current_html: Path, public_dir: Path) -> Path:
    url_path = url_path.replace("\\", "/")
    if url_path.startswith("/"):
        rel = url_path.lstrip("/")
        target = public_dir / Path(*rel.split("/"))
    else:
        target = current_html.parent / Path(*url_path.split("/"))
    return normalize_path(target)


def pick_existing_target(path: Path) -> Path | None:
    if path.exists():
        if path.is_dir():
            index = path / "index.html"
            if index.exists():
                return index
            return None
        return path

    if path.suffix == "":
        index = path / "index.html"
        if index.exists():
            return index
        html = path.with_suffix(".html")
        if html.exists():
            return html

    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Check internal links in built HTML.")
    parser.add_argument(
        "--public-dir",
        default=os.environ.get("PUBLIC_DIR", "public"),
        help="Path to Hugo's output directory (default: public).",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("BASE_URL", ""),
        help="Treat links matching this base URL as internal.",
    )
    args = parser.parse_args()

    public_dir = Path(args.public_dir).resolve()
    if not public_dir.exists():
        print(f"Public directory not found: {public_dir}", file=sys.stderr)
        return 2

    base_netloc = ""
    if args.base_url:
        base_netloc = urlparse(args.base_url).netloc

    html_files = sorted(public_dir.rglob("*.html"))
    if not html_files:
        print("No HTML files found to check.", file=sys.stderr)
        return 2

    links_by_file: dict[Path, list[str]] = {}
    ids_by_file: dict[Path, set[str]] = {}
    for html_file in html_files:
        links, ids = parse_html(html_file)
        links_by_file[html_file] = links
        ids_by_file[html_file] = ids

    errors: list[str] = []
    checked = 0
    skipped_external = 0

    for html_file, links in links_by_file.items():
        for raw_link in links:
            link = raw_link.strip()
            if not link:
                continue

            url, fragment = urldefrag(link)
            parsed = urlparse(url)

            if url == "" and fragment == "":
                continue
            if url.startswith("#"):
                url = ""
            if parsed.scheme in SKIP_SCHEMES:
                continue
            if url.startswith("//") or parsed.scheme in EXTERNAL_SCHEMES:
                if base_netloc and parsed.netloc == base_netloc:
                    url = parsed.path
                else:
                    skipped_external += 1
                    continue

            target_html: Path | None
            if url == "":
                target_html = html_file
            else:
                target_path = resolve_internal_path(url, html_file, public_dir)
                target_html = pick_existing_target(target_path)
                if target_html is None:
                    errors.append(f"{html_file}: missing target for '{raw_link}'")
                    checked += 1
                    continue

            checked += 1
            if fragment and target_html.suffix == ".html":
                ids = ids_by_file.get(target_html, set())
                if fragment not in ids:
                    errors.append(
                        f"{html_file}: missing anchor '#{fragment}' in '{target_html}'"
                    )

    if errors:
        print("Broken internal links found:")
        for error in errors:
            print(f"- {error}")
        print(f"Checked {checked} links. Skipped {skipped_external} external links.")
        return 1

    print(f"Link check passed. Checked {checked} links. Skipped {skipped_external} external links.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
