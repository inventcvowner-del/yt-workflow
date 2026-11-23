"""Finds topic folders and works out which voices, clips and uploads are still missing."""
import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

import config

log = logging.getLogger("topics")

CLIP_HEADER = re.compile(r"^\W*Clip\s+(\d+)\b", re.IGNORECASE)
# Clip-count markers such as "6 scirtps brake here - time 4:40" or just "4 scritps" (any spelling of
# "scripts") are notes for Step 3 and are never narrated.
MARKER_LINE = re.compile(r"(?im)^[ \t]*\d+[ \t]+sc[ript]{3,6}s\b[^\r\n]*\r?$")
SECTION_BREAK = re.compile(r"(?m)^\s*-{5,}\s*$")

LISTING_FILE = "youtube_title_description.txt"
UPLOAD_RECORD = "youtube_upload.json"    # written when an upload starts; its existence means "do not upload again"
LISTING_HEADER = re.compile(r"^(OTHER TITLE OPTIONS|TITLE OPTIONS|TITLE|DESCRIPTION|TAGS|HASHTAGS)\b")
THUMBNAIL_NAME = re.compile(r"th\w*nail", re.IGNORECASE)   # also matches the "thambnail" typo seen in a topic folder
THUMBNAIL_SUFFIXES = {".png", ".jpg", ".jpeg"}
TITLE_LIMIT, DESCRIPTION_LIMIT, TAGS_LIMIT = 100, 5000, 500   # YouTube's limits, in characters
ORDER_PREFIX = re.compile(r"^\s*(\d+)\.\s+")   # topic folders are numbered to keep the videos in order: "3. graphene"


def plain_name(name: str) -> str:
    """A folder name without its order number: '3. graphene' -> 'graphene'."""
    return ORDER_PREFIX.sub("", name)


def order_key(name: str) -> tuple:
    """Sort key for folder names: numbered folders in number order ('2. x' before '10. y'), then any others by name."""
    match = ORDER_PREFIX.match(name)
    return (0, int(match.group(1)), plain_name(name).lower()) if match else (1, 0, name.lower())


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


@dataclass(frozen=True)
class ThumbnailJob:
    topic: Topic
    title: str
    description: str

    @property
    def target(self) -> Path:
        return self.topic.path / config.THUMBNAIL_FILE

    @property
    def label(self) -> str:
        return f"{self.topic.label} thumbnail"


@dataclass(frozen=True)
class UploadJob:
    topic: Topic
    video: Path
    thumbnail: Path
    title: str
    description: str
    tags: tuple[str, ...]

    @property
    def target(self) -> Path:
        return self.topic.path / UPLOAD_RECORD

    @property
    def label(self) -> str:
        return f"{self.topic.label} upload"


def find_topics(kinds=("short", "long"), only=None) -> list[Topic]:
    """Topic folders of the given kinds in number order; `only` is a folder name, with or without its number."""
    folders = {"short": config.SHORTS_DIR, "long": config.LONGS_DIR}
    topics = []
    for kind in kinds:
        base = folders[kind]
        if not base.is_dir():
            continue
        for path in sorted(base.iterdir(), key=lambda folder: order_key(folder.name)):
            if path.is_dir() and (only is None or only.lower() in (path.name.lower(), plain_name(path.name).lower())):
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


def newest(files: list[Path]) -> Path | None:
    return max(files, key=lambda f: f.stat().st_mtime, default=None)


def find_final_video(folder: Path) -> Path | None:
    """Final.mp4, or else the newest final*.mp4 (older folders have names like 'final video.mp4' and 'final_1.mp4')."""
    videos = [f for f in folder.iterdir()
              if f.is_file() and f.suffix.lower() == ".mp4" and f.stem.strip().lower().startswith("final")]
    return newest([f for f in videos if f.stem.strip().lower() == "final"] or videos)


def find_thumbnail(folder: Path) -> Path | None:
    return newest([f for f in folder.iterdir()
                   if f.is_file() and f.suffix.lower() in THUMBNAIL_SUFFIXES and THUMBNAIL_NAME.match(f.stem)])


def parse_listing(path: Path) -> tuple[str, str, tuple[str, ...]]:
    """Read youtube_title_description.txt into (title, description, tags). Raises ValueError if it cannot be used.

    Shorts have a TITLE section. The older long-video layout has numbered TITLE OPTIONS, of which the first is used.
    A separate HASHTAGS section is added to the end of the description.
    """
    sections: dict[str, list[str]] = {}
    current = None
    for line in read_text(path).splitlines():
        header = LISTING_HEADER.match(line.strip())
        if header:
            current = header.group(1)
            sections.setdefault(current, [])
        elif current:
            sections[current].append(line.rstrip())

    title = next((line.strip() for line in sections.get("TITLE", []) if line.strip()), "")
    if not title:
        options = [line.strip() for line in sections.get("TITLE OPTIONS", []) if line.strip()]
        title = re.sub(r"^\d+[.)]\s*", "", options[0]) if options else ""
    description = "\n".join(sections.get("DESCRIPTION", [])).strip()
    hashtags = " ".join(" ".join(sections.get("HASHTAGS", [])).split())
    if hashtags and hashtags not in description:
        description = f"{description}\n\n{hashtags}".strip()
    tags = tuple(tag.strip() for tag in ",".join(sections.get("TAGS", [])).split(",") if tag.strip())

    problems = []
    if not title:
        problems.append("no title (it needs a TITLE section)")
    elif len(title) > TITLE_LIMIT:
        problems.append(f"the title has {len(title)} characters, YouTube allows {TITLE_LIMIT}")
    if not description:
        problems.append("no description (it needs a DESCRIPTION section)")
    elif len(description) > DESCRIPTION_LIMIT:
        problems.append(f"the description has {len(description)} characters, YouTube allows {DESCRIPTION_LIMIT}")
    if "<" in title + description or ">" in title + description:
        problems.append("the title and description may not contain < or >")
    if len(",".join(tags)) > TAGS_LIMIT:
        problems.append(f"the tags have {len(','.join(tags))} characters, YouTube allows {TAGS_LIMIT}")
    if problems:
        raise ValueError(f"{path.name}: " + "; ".join(problems))
    return title, description, tags


def thumbnail_blockers(topic: Topic) -> list[str]:
    """Why no thumbnail is made for a topic. Empty when it needs one.

    A thumbnail is made when the folder holds youtube_title_description.txt, has no thumbnail yet and has no
    youtube_upload.json (a video that is already on YouTube has its thumbnail there).
    """
    if (topic.path / UPLOAD_RECORD).exists():
        return ["already uploaded (youtube_upload.json exists)"]
    blockers = []
    existing = find_thumbnail(topic.path)
    if existing is not None:
        blockers.append(f"already has a thumbnail ({existing.name})")
    if not (topic.path / LISTING_FILE).is_file():
        blockers.append(f"no {LISTING_FILE}")
    return blockers


def pending_thumbnails(topic: Topic) -> list[ThumbnailJob]:
    if thumbnail_blockers(topic):
        return []
    try:
        title, description, _ = parse_listing(topic.path / LISTING_FILE)
    except ValueError as problem:
        log.warning("%s: cannot make a thumbnail, %s", topic.label, problem)
        return []
    return [ThumbnailJob(topic, title, description)]


def upload_blockers(topic: Topic) -> list[str]:
    """Why a topic's video cannot be uploaded yet. Empty when it is ready.

    A video is uploaded only when its folder holds all three of Final.mp4, a thumbnail and
    youtube_title_description.txt, and has no youtube_upload.json (that file marks it as uploaded).
    """
    if (topic.path / UPLOAD_RECORD).exists():
        return ["already uploaded (youtube_upload.json exists)"]
    blockers = []
    video = find_final_video(topic.path)
    if video is None:
        blockers.append("no Final.mp4")
    elif time.time() - video.stat().st_mtime < config.UPLOAD_SETTLE:
        blockers.append(f"{video.name} changed a moment ago and may still be exporting")
    if find_thumbnail(topic.path) is None:
        blockers.append("no thumbnail")
    if not (topic.path / LISTING_FILE).is_file():
        blockers.append(f"no {LISTING_FILE}")
    return blockers


def pending_uploads(topic: Topic) -> list[UploadJob]:
    if upload_blockers(topic):
        return []
    try:
        title, description, tags = parse_listing(topic.path / LISTING_FILE)
    except ValueError as problem:
        log.warning("%s: cannot upload, %s", topic.label, problem)
        return []
    return [UploadJob(topic, find_final_video(topic.path), find_thumbnail(topic.path), title, description, tags)]


def read_upload_record(topic: Topic) -> dict | None:
    """The upload record of a topic, {} when the file is empty or hand-made, None when there is none."""
    record = topic.path / UPLOAD_RECORD
    if not record.is_file():
        return None
    try:
        return json.loads(read_text(record))
    except ValueError:
        return {}


def write_upload_record(job: UploadJob, **fields) -> None:
    record = {"title": job.title, "video": job.video.name, **fields}
    job.target.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
