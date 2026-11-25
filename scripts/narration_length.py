"""run update short-narration-script-length: writes how many clip scripts a short needs at the end of narration.txt.

The count comes from the length of voices\\01.mp3: one script per started 10 seconds (0-10 s = 1, 10-20 s = 2, ...).
The footer looks like this and replaces an older one:

    4 scripts
    --------------
"""
import logging
import math
import re

from mutagen.mp3 import MP3

import topics

log = logging.getLogger("narration_length")
SECONDS_PER_SCRIPT = 10
FOOTER = re.compile(r"(?:\s*^[ \t]*\d+[ \t]+sc[ript]{3,6}s\b[^\r\n]*$)(?:\s*^\s*-{5,}\s*$)?\s*\Z", re.IGNORECASE | re.MULTILINE)


def script_count(seconds: float) -> int:
    return max(1, math.ceil(seconds / SECONDS_PER_SCRIPT))


def update(topic: topics.Topic) -> bool:
    voice = topic.path / "voices" / "01.mp3"
    narration = topic.path / "narration.txt"
    if not voice.is_file() or not narration.is_file():
        log.info("%s: skipped, no %s", topic.name, "voices\\01.mp3" if not voice.is_file() else "narration.txt")
        return False
    seconds = MP3(voice).info.length
    count = script_count(seconds)
    text = narration.read_text(encoding="utf-8-sig")
    body = FOOTER.sub("", text).rstrip()
    new = f"{body}\n\n{count} scripts\n--------------\n"
    if new == text:
        log.info("%s: %.1f s -> %d scripts (already up to date)", topic.name, seconds, count)
        return False
    narration.write_text(new, encoding="utf-8")
    log.info("%s: %.1f s -> %d scripts", topic.name, seconds, count)
    return True


def run(found: list[topics.Topic]) -> None:
    shorts = [topic for topic in found if topic.kind == "short"]
    changed = sum(update(topic) for topic in shorts)
    log.info("Updated %d of %d short narration.txt files", changed, len(shorts))
