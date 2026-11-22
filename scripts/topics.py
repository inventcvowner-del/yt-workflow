"""Finds topic folders and works out which voices and clips are still missing."""
import re
from dataclasses import dataclass
from pathlib import Path

import config

CLIP_HEADER = re.compile(r"^\W*Clip\s+(\d+)\b", re.IGNORECASE)
# Clip-count markers such as "6 scirtps brake here - time 4:40" or just "4 scritps" (any spelling of
# "scripts") are notes for Step 3 and are never narrated.
MARKER_LINE = re.compile(r"(?im)^[ \t]*\d+[ \t]+sc[ript]{3,6}s\b[^\r\n]*\r?$")
SECTION_BREAK = re.compile(r"(?m)^\s*-{5,}\s*$")


@dataclass(frozen=True)
class Topic:
    kind: str   # "short" or "long"
    path: Path

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def label(self) -> str:
        return f"{self.kind}/{self.name}"


@dataclass(frozen=True)
class ClipJob:
    topic: Topic
    number: int
    prompt: str

    @property
    def target(self) -> Path:
        return self.topic.path / "video_clips" / f"Clip {self.number:02d}.mp4"

    @property
    def label(self) -> str:
        return f"{self.topic.label} Clip {self.number:02d}"


@dataclass(frozen=True)
class AudioJob:
    topic: Topic
    number: int
    text: str

    @property
    def target(self) -> Path:
        return self.topic.path / "voices" / f"{self.number:02d}.mp3"

    @property
    def label(self) -> str:
        return f"{self.topic.label} voice {self.number:02d}"


def find_topics(kinds=("short", "long"), only=None) -> list[Topic]:
    """Topic folders of the given kinds; `only` filters by folder name (case-insensitive)."""
    folders = {"short": config.SHORTS_DIR, "long": config.LONGS_DIR}
    topics = []
    for kind in kinds:
        base = folders[kind]
        if not base.is_dir():
            continue
        for path in sorted(base.iterdir()):
            if path.is_dir() and (only is None or path.name.lower() == only.lower()):
                topics.append(Topic(kind, path))
    return topics


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def parse_prompts(path: Path) -> dict[int, str]:
    """Read video_prompts.txt (short and long layouts) into {clip number: English prompt}."""
    prompts: dict[int, str] = {}
    number = None
    collecting = False
    parts: list[str] = []

    def finish():
        if number is not None and parts:
            prompts[number] = " ".join(parts)

    for line in read_text(path).splitlines():
        header = CLIP_HEADER.match(line)
        if header:
            finish()
            number, collecting, parts = int(header.group(1)), False, []
            continue
        if number is None:
            continue
        text = line.strip()
        if not collecting:
            if text.lower().startswith("prompt:"):
                collecting = True
                if text[7:].strip():
                    parts.append(text[7:].strip())
        elif text and not text.startswith("==="):
            parts.append(text)
        elif parts:     # a blank line or separator after the prompt text ends it
            finish()
            number = None
    finish()
    return prompts


ASPECT_IN_PROMPT = re.compile(r"(?:\b(?:Vertical|Widescreen) )?\b(9:16|16:9)\b")


def firefly_prompt(prompt: str, kind: str) -> str:
    """Make an aspect ratio named in the prompt agree with the Firefly setting for this kind of video.

    Most short-video prompts were written as "16:9, 4K, ..." and are generated vertically.
    """
    label = config.FIREFLY_SETTINGS[kind]["Aspect ratio"].replace("(", "").replace(")", "")   # "Vertical 9:16"
    ratio = label.split()[-1]
    return ASPECT_IN_PROMPT.sub(lambda found: found.group(0) if found.group(1) == ratio else label, prompt)


def split_script(text: str) -> list[str]:
    """Split a long-video script into narration sections (same rules as split_script.ps1)."""
    text = MARKER_LINE.sub("", text)
    return [part.strip() for part in SECTION_BREAK.split(text) if part.strip()]


def pending_clips(topic: Topic) -> list[ClipJob]:
    prompts_file = topic.path / "video_prompts.txt"
    if not prompts_file.is_file():
        return []
    jobs = [ClipJob(topic, number, firefly_prompt(prompt, topic.kind))
            for number, prompt in sorted(parse_prompts(prompts_file).items())]
    return [job for job in jobs if not job.target.exists()]


def saved_sections(topic: Topic) -> list[Path]:
    return sorted(f for f in (topic.path / "sections").glob("*.txt") if f.stem.isdigit())


def audio_sections(topic: Topic) -> dict[int, str]:
    """{section number: narration text} for a topic."""
    if topic.kind == "short":
        narration = topic.path / "narration.txt"
        # A short is one audio file, so separator lines are dropped too, not treated as section breaks.
        text = "\n".join(split_script(read_text(narration))) if narration.is_file() else ""
        return {1: text} if text else {}
    # Once a long video is split, sections\NN.txt decide what is narrated. script.txt is often edited
    # afterwards (clip markers, merged parts), and re-splitting it would ask for audio that already exists.
    saved = saved_sections(topic)
    if saved:
        return {int(f.stem): read_text(f).strip() for f in saved}
    script = topic.path / "script.txt"
    return dict(enumerate(split_script(read_text(script)), start=1)) if script.is_file() else {}


def pending_audio(topic: Topic) -> list[AudioJob]:
    jobs = [AudioJob(topic, number, text) for number, text in sorted(audio_sections(topic).items())]
    return [job for job in jobs if job.text and not job.target.exists()]


def save_sections(topic: Topic) -> None:
    """Write sections\\NN.txt the first time a long video's audio is generated."""
    if topic.kind != "long" or saved_sections(topic):
        return
    folder = topic.path / "sections"
    folder.mkdir(exist_ok=True)
    for number, text in audio_sections(topic).items():
        (folder / f"{number:02d}.txt").write_text(text, encoding="utf-8-sig")
