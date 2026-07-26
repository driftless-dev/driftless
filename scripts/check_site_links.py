#!/usr/bin/env python3
"""Check local links and fragments in the committed static site."""

from __future__ import annotations

import argparse
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SITE = ROOT / "site"


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: set[str] = set()
        self.links: list[tuple[str, str]] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.add(values["id"] or "")
        for attribute in ("href", "src"):
            if values.get(attribute):
                self.links.append((attribute, values[attribute] or ""))


def parse_page(path: Path) -> PageParser:
    parser = PageParser()
    parser.feed(path.read_text(encoding="utf-8"))
    return parser


def check(site: Path) -> list[str]:
    site = site.resolve()
    pages = {path.resolve(): parse_page(path) for path in site.rglob("*.html")}
    errors: list[str] = []

    for page, parsed_page in sorted(pages.items()):
        for attribute, raw_target in parsed_page.links:
            target = urlsplit(raw_target)
            if target.scheme or target.netloc or raw_target.startswith(("data:", "mailto:")):
                continue

            if target.path:
                relative_path = unquote(target.path)
                candidate = (
                    site / relative_path.lstrip("/")
                    if relative_path.startswith("/")
                    else page.parent / relative_path
                ).resolve()
            else:
                candidate = page

            try:
                candidate.relative_to(site)
            except ValueError:
                errors.append(
                    f"{page.relative_to(site)}: {attribute} escapes site root: {raw_target}"
                )
                continue

            if candidate.is_dir():
                candidate /= "index.html"
            if not candidate.is_file():
                errors.append(
                    f"{page.relative_to(site)}: missing {attribute} target: {raw_target}"
                )
                continue

            if target.fragment and candidate.suffix.lower() == ".html":
                target_page = pages.get(candidate.resolve())
                fragment = unquote(target.fragment)
                if target_page is None or fragment not in target_page.ids:
                    errors.append(
                        f"{page.relative_to(site)}: missing fragment #{fragment} in "
                        f"{candidate.relative_to(site)}"
                    )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "site", nargs="?", type=Path, default=DEFAULT_SITE, help="static site root"
    )
    args = parser.parse_args()
    errors = check(args.site)
    if errors:
        print("\n".join(errors))
        print(f"FAILED: {len(errors)} broken internal site link(s)")
        return 1
    print(f"OK: internal links valid in {args.site}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
