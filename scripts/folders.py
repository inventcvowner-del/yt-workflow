"""Creates the missing topic folders listed in topics.txt ("run folders").

Each kind of video has a topics.txt in its folder ("short videos\\topics.txt", "long videos\\topics.txt") with lines like
    200. Zero – India's gift that changed mathematics
A topic whose number has no folder yet gets one, named by the number and the part before the dash, in lower case:
    short videos\\200. zero
with empty voices and video_clips folders (and an empty script.txt for a long video, as new_video.ps1 makes).
A number that already has a folder is left alone, whatever that folder is called, so nothing is ever renamed or
created twice. Writing the script, narration and prompts is still a Copilot step.
"""
import logging
import re
from pathlib import Path

import config
import topics

log = logging.getLogger("folders")
LINE = re.compile(r"^\s*(\d+)\.\s+(.+?)\s*$")
DASH = re.compile(r"\s+[–—-]\s+")           # "Zero – India's gift ..." -> "Zero"
NOT_IN_NAMES = re.compile(r"[<>:\"/\\|?*'’‘“”()\[\],!]")
MAX_NAME = 60


def folder_name(number: int, title: str) -> str:
    name = DASH.split(title, maxsplit=1)[0]
    name = NOT_IN_NAMES.sub("", name).lower()
    name = re.sub(r"\s+", " ", name).strip(" .")
    if len(name) > MAX_NAME:
        name = name[:MAX_NAME].rsplit(" ", 1)[0].strip(" .")
    return f"{number}. {name}"


def listed(kind: str) -> list[tuple[int, str]]:
    """(number, title) for every numbered line of the kind's topics.txt, Done and Pending alike."""
    base = {"short": config.SHORTS_DIR, "long": config.LONGS_DIR}[kind]
    path = base / "topics.txt"
    if not path.is_file():
        return []
    found = []
    for line in topics.read_text(path).splitlines():
        match = LINE.match(line)
        if match:
            found.append((int(match.group(1)), match.group(2)))
    return found


def missing(kind: str, only: int | None = None) -> list[Path]:
    base = {"short": config.SHORTS_DIR, "long": config.LONGS_DIR}[kind]
    numbers = {int(m.group(1)) for f in base.iterdir() if f.is_dir() and (m := topics.ORDER_PREFIX.match(f.name))}
    return [base / folder_name(number, title) for number, title in listed(kind)
            if number not in numbers and (only is None or number == only)]


def create(kind: str, folder: Path) -> None:
    for sub in ("voices", "video_clips"):
        (folder / sub).mkdir(parents=True, exist_ok=True)
    if kind == "long":
        (folder / "script.txt").touch(exist_ok=True)


def run(kinds, only: int | None = None) -> int:
    """Create every missing folder of the given kinds (or only topic number `only`). Returns how many were made."""
    made = 0
    for kind in kinds:
        for folder in missing(kind, only):
            create(kind, folder)
            log.info("Created %s", folder)
            made += 1
    if not made:
        log.info("Topic %d already has a folder" % only if only is not None
                 else "Every topic in topics.txt already has a folder")
    return made
