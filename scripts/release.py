"""Reads the release plan (release.txt in the workflow folder) and hands out its next free slot for a video.

The plan is a table with one row per day. Each slot is a time followed by its Status (Pending or Done); the slots
are "Short 1" ... "Short 4" and "Long video". A scheduled video takes the earliest Pending slot of its kind that is
still far enough away, and that slot is then marked Done. Times are IST, like this PC and Studio's schedule picker.
"""
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import config

log = logging.getLogger("release")

HEADER_SLOT = re.compile(r"(Short \d+|Long video) time", re.IGNORECASE)
DATE_ROW = re.compile(r"^\d{4}-\d{2}-\d{2}\b")
CELL = re.compile(r"\S+(?: \S+)*")      # cells are separated by two or more spaces; a time is "08:00 AM"
PLAN_OFFSET = timedelta(hours=5, minutes=30)


@dataclass(frozen=True)
class Slot:
    when: datetime      # local time, no time zone
    kind: str           # "short" or "long"
    status: str
    line: int           # index of the slot's row in the file
    start: int          # where the Status cell starts and ends in that row
    end: int

    @property
    def label(self) -> str:
        return f"{self.when:%Y-%m-%d %H:%M}"


def in_plan_time_zone() -> bool:
    """The plan is in IST. Studio schedules in this PC's time zone, so the two must agree."""
    return datetime.now().astimezone().utcoffset() == PLAN_OFFSET


def read_lines(path: Path) -> list[str]:
    with open(path, encoding="utf-8", newline="") as file:      # newline="" keeps the CRLF line endings as they are
        return file.read().splitlines(keepends=True)


def load(path: Path) -> list[Slot]:
    """Every slot in the plan. A row that does not fit the header's columns is skipped with a warning."""
    lines = read_lines(path)
    header = next((line for line in lines if line.lower().startswith("date") and HEADER_SLOT.search(line)), None)
    if header is None:
        raise ValueError(f"{path.name}: the table header (Date, Short 1 time, Status, ...) was not found")
    kinds = ["long" if name.lower().startswith("long") else "short" for name in HEADER_SLOT.findall(header)]

    slots = []
    for number, line in enumerate(lines):
        if not DATE_ROW.match(line):
            continue
        cells = list(CELL.finditer(line.rstrip("\r\n")))
        if len(cells) != 1 + 2 * len(kinds):
            log.warning("%s line %d: expected %d columns, found %d; row skipped",
                        path.name, number + 1, 1 + 2 * len(kinds), len(cells))
            continue
        for index, kind in enumerate(kinds):
            time_cell, status_cell = cells[1 + 2 * index], cells[2 + 2 * index]
            try:
                when = datetime.strptime(f"{cells[0].group()} {time_cell.group()}", "%Y-%m-%d %I:%M %p")
            except ValueError:
                log.warning("%s line %d: cannot read the time '%s'; slot skipped", path.name, number + 1, time_cell.group())
                continue
            slots.append(Slot(when, kind, status_cell.group(), number, status_cell.start(), status_cell.end()))
    return slots


def next_slot(path: Path, kind: str, now: datetime | None = None) -> Slot | None:
    """The earliest Pending slot of this kind that is at least SCHEDULE_LEAD away, or None when the plan has run out."""
    earliest = (now or datetime.now()) + timedelta(seconds=config.SCHEDULE_LEAD)
    free = [slot for slot in load(path)
            if slot.kind == kind and slot.status.lower() == "pending" and slot.when >= earliest]
    return min(free, key=lambda slot: slot.when, default=None)


def mark_done(path: Path, slot: Slot) -> None:
    """Change the slot's Status from Pending to Done, keeping the table's alignment."""
    current = next((s for s in load(path) if s.when == slot.when and s.kind == slot.kind), None)
    if current is None or current.status.lower() != "pending":
        raise ValueError(f"{path.name}: the slot {slot.label} is no longer Pending")
    lines = read_lines(path)
    line = lines[current.line]
    lines[current.line] = line[:current.start] + "Done".ljust(current.end - current.start) + line[current.end:]
    temporary = path.with_name(path.name + ".tmp")
    with open(temporary, "w", encoding="utf-8", newline="") as file:
        file.write("".join(lines))
    os.replace(temporary, path)
