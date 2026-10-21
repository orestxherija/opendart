#!/usr/bin/env python3
"""Extract the public English developer guides; never reads credentials or .env.

Usage: python3 scripts/api_reference/snapshot.py [--cache-dir DIRECTORY]
The cache is optional and contains public HTML only. Fetching is deliberately
sequential and bounded to the six group indexes and their linked detail pages.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import urlopen

BASE = "https://engopendart.fss.or.kr"
ROOT = Path(__file__).resolve().parents[2] / "api_reference"


class GuideParser(HTMLParser):
    """Extract guide tables, indentation, container markers, and public examples.

    Attributes:
        tables (list[dict]): Parsed tables with HTML attributes and rows of cell
            dictionaries.
        table (dict | None): Currently open table, if any.
        row (list[dict] | None): Currently open table row, if any.
        cell (dict | None): Currently open cell, including text and nesting metadata.
        examples (dict[str, str]): Public hidden input examples, excluding the API
            credential.
        links (list[str]): Relative links to developer-guide detail pages.
    """

    def __init__(self, html):
        """Initialize parser state and consume a guide HTML document.

        Args:
            html (str): HTML source from a public index or detail page.

        Raises:
            ValueError: The document contains unsupported nested tables.
        """
        super().__init__()
        self.tables = []
        self.table = self.row = self.cell = None
        self.examples = {}
        self.links = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        """Collect table structure, nesting markers, examples, and detail-page links.

        Args:
            tag (str): Lowercase HTML tag name.
            attrs (list[tuple[str, str | None]]): HTML attribute names and optional values.

        Raises:
            ValueError: A table starts inside another table.
        """
        attrs = dict(attrs)
        if tag == "table":
            if self.table is not None:
                raise ValueError("Unexpected nested table")
            self.table = {"attrs": attrs, "rows": []}
            self.tables.append(self.table)
        elif tag == "tr" and self.table is not None:
            self.row = []
            self.table["rows"].append(self.row)
        elif tag in ("td", "th") and self.row is not None:
            self.cell = {"text": "", "indent": 0, "container": False}
            self.row.append(self.cell)
        elif tag == "br" and self.cell is not None:
            self.cell["text"] += "\n"
        elif tag == "span" and self.cell is not None:
            match = re.fullmatch(r"mgl(\d+)", attrs.get("class", ""))
            if match:
                self.cell["indent"] = int(match[1])
        elif tag == "i" and self.cell is not None:
            self.cell["container"] = attrs.get("class") == "iconArrow"
        elif tag == "input" and attrs.get("name"):
            name, value = attrs["name"], attrs.get("value", "")
            if name != "crtfc_key" and value and attrs.get("type") == "hidden":
                self.examples[name] = value
        elif tag == "a" and attrs.get("href", "").startswith("/guide/detail.do?"):
            self.links.append(attrs["href"])

    def handle_endtag(self, tag):
        """Clear the state for a closing table, row, or cell.

        Args:
            tag (str): Lowercase closing HTML tag name.
        """
        if tag == "table":
            self.table = None
        elif tag == "tr":
            self.row = None
        elif tag in ("td", "th"):
            self.cell = None

    def handle_data(self, data):
        """Append text to the current table cell, when one is open.

        Args:
            data (str): Character data supplied by HTMLParser.
        """
        if self.cell is not None:
            self.cell["text"] += data


def clean(value):
    """Collapse whitespace into single spaces and strip the result.

    Args:
        value (str): Raw table text.

    Returns:
        str: Normalized text without leading or trailing whitespace.
    """
    return re.sub(r"\s+", " ", value).strip()


def rows(table):
    """Extract normalized cell text from a parsed table.

    Args:
        table (dict): Table dictionary produced by GuideParser.

    Returns:
        list[list[str]]: Rows containing normalized cell strings.
    """
    return [[clean(cell["text"]) for cell in row] for row in table["rows"]]


def extract(html, entry):
    """Extract a service catalog entry from a public guide detail page.

    Args:
        html (str): Public developer-guide HTML.
        entry (dict): Service metadata containing its ID, title, description, and source
            URL.

    Returns:
        dict: Metadata extended with a page hash, endpoints, parameters, response fields, and code tables.

    Raises:
        ValueError: Required tables are missing, nested tables occur, rows are malformed, or
            an endpoint is not a GET on the English API.
    """
    parser = GuideParser(html)
    endpoint_rows = request_rows = response_rows = None
    extra = []
    for table in parser.tables:
        values = rows(table)
        if not values:
            continue
        if values[0][0] == "Method":
            endpoint_rows = values[1:]
        elif values[0][0] == "Requested key":
            request_rows = values[1:]
        elif values[0][0] == "Response key":
            response_rows = table["rows"][1:]
        elif table["attrs"].get("class") == "tb02":
            extra.append(values)
    if not endpoint_rows or not request_rows or not response_rows:
        raise ValueError(f"Incomplete guide: {entry["source"]}")
    parameters = []
    for row in request_rows:
        if len(row) != 5 or row[3] not in ("Y", "N"):
            raise ValueError(f"Unexpected parameter row: {row}")
        name, title, declared_type, required, description = row
        parameter = dict(
            name=name,
            title=title,
            declared_type=declared_type,
            required=required == "Y",
            description=description,
        )
        if name in parser.examples:
            parameter["example"] = parser.examples[name]
        parameters.append(parameter)
    fields = []
    for row in response_rows:
        if len(row) != 3:
            raise ValueError(f"Unexpected response row: {row}")
        key, title, description = [clean(cell["text"]) for cell in row]
        fields.append(
            dict(
                name=key,
                title=title,
                description=description,
                indent=row[0]["indent"],
                container=row[0]["container"],
            )
        )
    endpoints = []
    for method, url, encoding, output in endpoint_rows:
        if method != "GET" or not url.startswith(BASE + "/engapi/"):
            raise ValueError(f"Unexpected endpoint: {url}")
        endpoints.append(
            dict(
                method=method,
                path=urlsplit(url).path.removeprefix("/engapi"),
                output=output,
                encoding=encoding,
            )
        )
    return dict(
        **entry,
        html_sha256=sha256(html.encode()).hexdigest(),
        endpoints=endpoints,
        parameters=parameters,
        fields=fields,
        code_tables=extra,
    )


def main():
    """Fetch six public guide indexes and their details, then write the catalog snapshot.

    Raises:
        SystemExit: CLI argument parsing exits.
        urllib.error.URLError: A public guide cannot be fetched.
        OSError: Cached HTML or the output catalog cannot be read or written.
        UnicodeError: A guide cannot be decoded as UTF-8.
        ValueError: Guide tables, endpoints, or index link counts are inconsistent.
        StopIteration: An index page has no expected service catalog table.
    """
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--cache-dir", type=Path)
    args = cli.parse_args()

    def read(name, url):
        """Read public HTML from the optional cache or fetch and cache it.

        Args:
            name (str): Index or service identifier used as the cache filename stem.
            url (str): Public guide URL to fetch when no cached file exists.

        Returns:
            str: UTF-8 decoded HTML.

        Raises:
            urllib.error.URLError: The guide cannot be fetched.
            OSError: The HTML cache cannot be read or written.
            UnicodeError: HTML cannot be decoded as UTF-8.
        """
        path = args.cache_dir / (name + ".html") if args.cache_dir else None
        if path and path.exists():
            return path.read_text(encoding="utf-8")
        target = urlsplit(url)
        if target.scheme != "https" or target.netloc != "engopendart.fss.or.kr":
            raise ValueError(f"Unexpected guide URL: {url}")
        # The scheme and host are checked above before following guide links.
        with urlopen(url, timeout=60) as response:  # noqa: S310
            html = response.read().decode("utf-8")
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(html, encoding="utf-8")
        return html

    groups = []
    for number in range(1, 7):
        code = f"DE{number:03}"
        source = f"{BASE}/guide/main.do?apiGrpCd={code}"
        html = read(code, source)
        parser = GuideParser(html)
        links = list(dict.fromkeys(parser.links))
        table = next(t for t in parser.tables if t["attrs"].get("class") == "tb01")
        catalog = rows(table)[1:]
        if len(links) != len(catalog) or not links:
            raise ValueError(f"Index rows and links do not agree: {code}")
        entries = []
        for link, row in zip(links, catalog, strict=True):
            api_id = re.search(r"apiId=(AE\d+)", link)[1]
            entry = dict(id=api_id, title=row[1], description=row[2], source=urljoin(BASE, link))
            entries.append(extract(read(api_id, entry["source"]), entry))
        groups.append(dict(code=code, source=source, services=entries))
        print(f"{code}: {len(entries)} services", flush=True)
    snapshot = dict(
        retrieved_on=datetime.now(UTC).date().isoformat(),
        source=BASE + "/intro/main.do",
        groups=groups,
    )
    target = ROOT / "sources/catalog.json"
    target.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
