#!/usr/bin/env python3
"""Fetch the public STScI visit report and write dashboard JSON."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


PROGRAM_ID = "10678"
PROGRAM_TITLE = "The JWST/NIRCam Legacy Survey of the Galactic Center"
REPORT_URL = f"https://www.stsci.edu/jwst-program-info/visits/?program={PROGRAM_ID}"
XML_URL = f"{REPORT_URL}&download="
HELP_URL = f"https://www.stsci.edu/jwst-program-info/visit-help/?program={PROGRAM_ID}#status"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "data" / "visits.json"
USER_AGENT = "jwst-gc-dashboard/1.0 (https://github.com/ashleythomasbarnes/jwst_gc_dashboard)"

COMPLETED_STATUSES = {"executed", "collecting", "archived", "completed"}


def status_group(status: str) -> str:
    """Map an STScI status to one of the dashboard's four colour groups."""
    normalized = " ".join(status.casefold().split())
    if "failed" in normalized:
        return "failed"
    if normalized == "scheduled":
        return "scheduled"

    parts = {part.strip() for part in normalized.split(" - ")}
    if parts & COMPLETED_STATUSES:
        return "completed"
    return "neutral"


def natural_key(value: str) -> tuple[object, ...]:
    """Return a natural-sort key so GC_2 appears before GC_10."""
    return tuple(int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", value))


def child_texts(element: ET.Element, tag: str) -> list[str]:
    return [text for child in element.findall(tag) if (text := (child.text or "").strip())]


def child_text(element: ET.Element, tag: str) -> str | None:
    values = child_texts(element, tag)
    return values[0] if values else None


def parse_report(xml_data: bytes, fetched_at: str | None = None) -> dict[str, object]:
    """Parse and validate an STScI visit-status XML document."""
    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError as error:
        raise ValueError(f"STScI returned invalid XML: {error}") from error

    if root.tag != "visitStatusReport":
        raise ValueError(f"Unexpected XML root element: {root.tag!r}")
    if root.get("id") != PROGRAM_ID:
        raise ValueError(f"Expected program {PROGRAM_ID}, received {root.get('id')!r}")

    visits: list[dict[str, object]] = []
    for element in root.findall("visit"):
        observation = (element.get("observation") or "").strip()
        visit_number = (element.get("visit") or "").strip()
        statuses = child_texts(element, "status")
        targets = child_texts(element, "target")

        if not observation or not visit_number:
            raise ValueError("A visit is missing its observation or visit number")
        if not statuses:
            raise ValueError(f"Visit {observation}:{visit_number} has no status")
        if not targets:
            raise ValueError(f"Visit {observation}:{visit_number} has no target")

        hours_text = child_text(element, "hours")
        try:
            hours = float(hours_text) if hours_text is not None else None
        except ValueError as error:
            raise ValueError(f"Visit {observation}:{visit_number} has invalid hours: {hours_text!r}") from error

        status = " - ".join(statuses)
        visits.append(
            {
                "id": f"{PROGRAM_ID}:{observation}:{visit_number}",
                "observation": observation,
                "visit": visit_number,
                "status": status,
                "status_group": status_group(status),
                "targets": targets,
                "configurations": child_texts(element, "configuration"),
                "hours": hours,
                "plan_windows": child_texts(element, "planWindow"),
                "start_time": child_text(element, "startTime"),
                "end_time": child_text(element, "endTime"),
            }
        )

    if not visits:
        raise ValueError("STScI returned an empty visit report")

    visits.sort(
        key=lambda item: (
            natural_key(str(item["targets"][0])),
            natural_key(str(item["observation"])),
            natural_key(str(item["visit"])),
        )
    )

    counts = Counter(str(visit["status_group"]) for visit in visits)
    if fetched_at is None:
        fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    return {
        "program": {
            "id": PROGRAM_ID,
            "title": PROGRAM_TITLE,
            "source_url": REPORT_URL,
            "xml_url": XML_URL,
            "help_url": HELP_URL,
        },
        "report_time": child_text(root, "reportTime"),
        "fetched_at": fetched_at,
        "visit_count": len(visits),
        "status_counts": {
            "neutral": counts["neutral"],
            "scheduled": counts["scheduled"],
            "completed": counts["completed"],
            "failed": counts["failed"],
        },
        "visits": visits,
    }


def fetch_xml(url: str = XML_URL, attempts: int = 3, timeout: int = 30) -> bytes:
    """Fetch XML with short retries for temporary network/server errors."""
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/xml,text/xml;q=0.9,*/*;q=0.1"})
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.read()
        except (HTTPError, URLError, TimeoutError) as error:
            last_error = error
            if attempt < attempts:
                time.sleep(2 ** (attempt - 1))

    raise RuntimeError(f"Unable to fetch the STScI report after {attempts} attempts: {last_error}")


def write_json_atomic(data: dict[str, object], output: Path) -> None:
    """Replace the output only after a complete JSON document is ready."""
    output.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=output.parent, delete=False) as temporary:
            temporary.write(serialized)
            temporary_path = temporary.name
        os.replace(temporary_path, output)
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="JSON output path")
    parser.add_argument("--source-file", type=Path, help="Read local XML instead of downloading the live report")
    args = parser.parse_args()

    xml_data = args.source_file.read_bytes() if args.source_file else fetch_xml()
    report = parse_report(xml_data)
    write_json_atomic(report, args.output)
    print(f"Wrote {report['visit_count']} visits to {args.output}")


if __name__ == "__main__":
    main()
