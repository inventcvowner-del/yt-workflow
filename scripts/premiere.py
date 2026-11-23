"""Step "edit": builds the Premiere project of a topic and exports final.mp4.

Premiere takes a script only when it is started with one, so each topic gets its own Premiere run: the script
(premiere.jsx) puts the clips end to end, the voices end to end, cuts the longer of the two at its end, scales the
clips until they fill the frame, exports, and closes Premiere. The export gets the name final.mp4 only once it has
been checked, because that name is what the upload step looks for.
"""
import json
import logging
import os
import shutil
import struct
import subprocess
import time
from pathlib import Path

import chrome
import config

log = logging.getLogger("premiere")

PROGRAM = "Adobe Premiere Pro.exe"
RUNNER = Path(__file__).with_name("premiere.jsx")
EXPORT_NAME = "_export.mp4"      # must not start with "final": the upload step would take it while it is being written
EXPORT_FILES = "_export*"        # the export and the _export<id>.m4v/.aac files Premiere writes next to it meanwhile
PREMIERE_FOLDERS = ("Adobe Premiere Pro Audio Previews", "Adobe Premiere Pro Video Previews",
                    "Adobe Premiere Pro Auto-Save")     # Premiere makes these next to a project
LAUNCHER = """\
var JOB = %s;
try {
    $.evalFile(new File(JOB.runner));
} catch (problem) {
    var failed = new File(JOB.result);
    failed.open("w");
    failed.writeln("status=ERROR");
    failed.writeln("message=premiere.jsx could not be loaded: " + problem);
    failed.close();
    app.quit();
}
"""

_gave_up: dict[Path, tuple] = {}    # topic folder -> its clips and voices when Premiere could not edit it


class NotEdited(Exception):
    """The topic's files cannot be edited as they are (e.g. a clip that is not a readable MP4)."""


def find_premiere() -> Path:
    found = sorted(config.ADOBE_DIR.glob(f"Adobe Premiere Pro */{PROGRAM}"))
    if not found:
        raise chrome.NeedsUser(f"Adobe Premiere Pro was not found in {config.ADOBE_DIR} (ADOBE_DIR in config.py).")
    return found[-1]


def is_running() -> bool:
    listing = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {PROGRAM}", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
    return PROGRAM.lower() in listing.stdout.lower()


def boxes(file, start: int, end: int):
    """The MP4 boxes between two positions of a file, as (type, start of the content, end)."""
    position = start
    while position + 8 <= end:
        file.seek(position)
        header = file.read(16)
        size, kind = struct.unpack(">I4s", header[:8])
        skip = 8
        if size == 1:                   # a 64-bit size follows
            size, skip = struct.unpack(">Q", header[8:16])[0], 16
        elif size == 0:                 # the box runs to the end
            size = end - position
        if size < skip:
            return
        yield kind, position + skip, position + size
        position += size


def media_info(path: Path) -> tuple[int, int, float]:
    """(width, height, seconds) of an MP4, read from its header (a 3 GB export is not read through)."""
    width = height = 0
    length = 0.0
    with open(path, "rb") as file:
        for box, start, end in boxes(file, 0, path.stat().st_size):
            if box != b"moov":
                continue
            for part, part_start, part_end in boxes(file, start, end):
                if part == b"mvhd":
                    file.seek(part_start)
                    data = file.read(32)
                    scale, ticks = struct.unpack(">II", data[12:20]) if data[0] == 0 else struct.unpack(">IQ", data[20:32])
                    length = ticks / scale
                elif part == b"trak":
                    for header, _, header_end in boxes(file, part_start, part_end):
                        if header == b"tkhd":
                            file.seek(header_end - 8)   # a track header ends with its width and height
                            size = [value >> 16 for value in struct.unpack(">II", file.read(8))]
                            if all(size):               # an audio track has none
                                width, height = size
    if not width or not length:
        raise ValueError("no video track found")
    return width, height, length


def png_size(path: Path) -> tuple[int, int]:
    with open(path, "rb") as file:
        header = file.read(24)
    if header[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("it is not a PNG")
    return struct.unpack(">II", header[16:24])


def logo_spec(kind: str, frame: tuple[int, int]) -> dict | None:
    """Where the logo goes: its file, its scale in percent and its centre as parts of the frame (Premiere's units)."""
    if config.PREMIERE_LOGO is None:
        return None
    try:
        width, height = png_size(config.PREMIERE_LOGO)
    except (OSError, ValueError) as problem:
        raise chrome.NeedsUser(f"The logo cannot be used: {config.PREMIERE_LOGO} ({problem}). "
                               "See PREMIERE_LOGO in config.py.") from None
    size, right, bottom = config.PREMIERE_LOGO_LAYOUT[kind]
    shown = size * frame[0]         # its width in the frame, in pixels
    return {
        "path": str(config.PREMIERE_LOGO),
        "scale": shown / width * 100,
        "x": 1 - right - size / 2,
        "y": 1 - bottom - shown * height / width / 2 / frame[1],
    }


def signature(job) -> tuple:
    return tuple((f.name, f.stat().st_size, f.stat().st_mtime_ns) for f in (*job.clips, *job.voices))


def export_size(folder: Path) -> int:
    total = 0
    for file in folder.glob(EXPORT_FILES):
        try:
            total += file.stat().st_size
        except OSError:     # Premiere removes its temporary files when the export is put together
            pass
    return total


def wait_for_result(process, result_file: Path, folder: Path) -> dict[str, str]:
    """What premiere.jsx reported: status (OK or ERROR), message and the lengths it measured.

    Premiere is given up on when it has neither reported nor made the export grow for PREMIERE_STALL_TIMEOUT.
    """
    size, last_progress = 0, time.monotonic()
    while True:
        exited = process.poll() is not None
        if result_file.exists():
            break
        if exited:
            raise RuntimeError("Premiere closed before it finished")
        if (now_size := export_size(folder)) != size:
            size, last_progress = now_size, time.monotonic()
        elif time.monotonic() - last_progress > config.PREMIERE_STALL_TIMEOUT:
            raise TimeoutError(f"nothing happened in Premiere for {config.PREMIERE_STALL_TIMEOUT // 60} minutes "
                               "(a dialog may be waiting for an answer)")
        time.sleep(1)
    lines = result_file.read_text(encoding="utf-8-sig").splitlines()
    return dict(line.split("=", 1) for line in lines if "=" in line)


def close(process, wait: float) -> None:
    """Premiere closes itself when its script ends. If it has not after `wait` seconds, it is stopped."""
    try:
        process.wait(timeout=wait)
    except subprocess.TimeoutExpired:
        log.warning("Stopping Premiere")
        process.kill()
        process.wait(timeout=30)


def remove_leftovers(folder: Path, project: Path) -> None:
    """Take a failed run out of the topic folder: its project, its unfinished export and Premiere's files for it."""
    for file in (project, project.with_suffix(".prin"), *folder.glob(EXPORT_FILES)):
        file.unlink(missing_ok=True)
    for name in PREMIERE_FOLDERS:
        extras = folder / name
        if not extras.is_dir():
            continue
        shutil.rmtree(extras / f"{project.stem}.PRV", ignore_errors=True)      # previews
        for backup in extras.glob(f"{project.stem}--*.prproj"):                 # auto-saves
            backup.unlink(missing_ok=True)
        if not any(extras.iterdir()):
            extras.rmdir()


def save_final(job, result: dict[str, str], export: Path, frame: tuple[int, int]) -> None:
    """Check the export against what Premiere reported and give it its final name."""
    if result.get("status") != "OK":
        raise RuntimeError(f"Premiere reported: {result.get('message', 'no message')}")
    clips, voices, cut = (float(result[key]) for key in ("videoSeconds", "audioSeconds", "cutSeconds"))
    try:
        width, height, length = media_info(export)
    except (OSError, ValueError, struct.error) as problem:
        raise RuntimeError(f"the export cannot be read ({problem})") from None
    if (width, height) != frame or abs(length - cut) > 1:
        raise RuntimeError(f"the export is {width}x{height} and {length:.1f} s, "
                           f"expected {frame[0]}x{frame[1]} and {cut:.1f} s")
    os.replace(export, job.target)
    log.info("%s: saved %s (%dx%d, %.1f s, %.0f MB)", job.label, job.target.name, width, height, length,
             job.target.stat().st_size / 1e6)
    if voices - cut > 0.05:
        log.warning("%s: the last %.1f s of the narration were cut (clips %.1f s, voices %.1f s)",
                    job.label, voices - cut, clips, voices)
    elif clips - cut > 0.05:
        log.info("%s: the clips were cut by %.1f s to the length of the voices (%.1f s)", job.label, clips - cut, voices)


def edit(exe: Path, job) -> None:
    topic = job.topic
    frame = config.PREMIERE_FRAME[topic.kind]
    project = topic.path / config.PREMIERE_PROJECT
    export = topic.path / EXPORT_NAME
    result_file = config.LOG_DIR / "premiere_result.txt"
    launcher = config.LOG_DIR / "premiere_job.jsx"
    preset = exe.parent / config.PREMIERE_PRESET
    if not preset.is_file():
        raise chrome.NeedsUser(f"The export preset was not found: {preset} (PREMIERE_PRESET in config.py).")
    if project.exists():        # made since the topic was listed; never replaced
        raise NotEdited(f"{project.name} already exists")

    clips = []
    for clip in job.clips:
        try:
            width, height, _ = media_info(clip)
        except (OSError, ValueError, struct.error) as problem:
            raise NotEdited(f"{clip.name} cannot be read as an MP4 ({problem})") from None
        clips.append({"path": str(clip), "width": width, "height": height})
    spec = {
        "runner": str(RUNNER),
        "result": str(result_file),
        "project": str(project),
        "sequence": config.PREMIERE_SEQUENCE,
        "clips": clips,
        "voices": [str(voice) for voice in job.voices],
        "logo": logo_spec(topic.kind, frame),
        "width": frame[0],
        "height": frame[1],
        "preset": str(preset),
        "output": str(export),
    }
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    for old in (result_file, result_file.with_name(result_file.name + ".tmp"), *topic.path.glob(EXPORT_FILES)):
        old.unlink(missing_ok=True)
    launcher.write_text(LAUNCHER % json.dumps(spec, indent=4), encoding="ascii")

    log.info("%s: starting Premiere (%d clips, %d voices, %dx%d)", job.label, len(clips), len(job.voices), *frame)
    process = subprocess.Popen([str(exe), "/C", "es.processFile", str(launcher)])
    try:
        finished = False
        try:
            result = wait_for_result(process, result_file, topic.path)
            finished = True
        finally:
            close(process, config.PREMIERE_QUIT_WAIT if finished else 0)
        save_final(job, result, export, frame)
    except BaseException:       # also Ctrl+C: a half-made project or export is not left in the topic folder
        remove_leftovers(topic.path, project)
        raise


def run(context, jobs) -> int:
    """Edit and export every job. Returns how many final videos were saved.

    `context` is the Chrome of the other steps; this one does not use it.
    """
    exe = find_premiere()
    saved = 0
    for job in jobs:
        files = signature(job)
        if _gave_up.get(job.topic.path) == files:
            continue        # Premiere could not edit these files before and they have not changed
        if is_running():
            raise chrome.NeedsUser("Premiere is open. Close it and start again: this step starts Premiere itself, "
                                   "because a Premiere that is already running cannot be given a script.")
        try:
            edit(exe, job)
            saved += 1
            continue
        except NotEdited as problem:
            log.warning("%s: not edited, %s", job.label, problem)
        except (RuntimeError, OSError) as problem:
            log.error("%s failed: %s", job.label, problem)
        _gave_up[job.topic.path] = files
        log.info("%s is tried again when its clips or voices change, or when run.py is started again", job.label)
    return saved
