r"""Runs the audio (ElevenLabs), clip (Firefly), edit (Premiere), thumbnail (ChatGPT) and upload (YouTube Studio) steps
for every topic.

Commands:
    run status           list what is still missing, and these commands; generates nothing
    run folders          make a folder for every topic in topics.txt that has none yet ("200. zero")
    run audio            generate the missing voices in ElevenLabs
    run audio vast       generate the missing voices with your own voice on the Vast GPU (start the instance first)
    run clips            generate the missing clips in Firefly
    run edit             put clips and voices together in Premiere and export final.mp4 (close Premiere first)
    run thumbnails       ask ChatGPT for the missing thumbnails (9:16 for shorts, 16:9 for long videos)
    run upload           upload finished videos to YouTube Studio, scheduled into the release plan
    run all              audio, then clips, then edits, then thumbnails, then uploads
    run login            open the automation Chrome to sign in (needed once, or when a site signs you out)
    run ui               open a page in the browser with a button for each step of each video (same commands)
    run update short-narration-script-length
                         write "N scripts" at the end of each short's narration.txt, one per 10 s of voices\01.mp3

Add to any command:
    short-N or long-N    only this video, by its number: "run edit short-11" is short videos\11. ferrofluid,
                         "run clips long-3" is long videos\3. hepatitis virus, "run audio vast long-12"
    --topic "name"       only this topic, by its folder name (with or without its number)
    short or long        only short videos or only long videos: "run audio short", "run audio vast long"
    --kind short|long    the same as short or long
    --watch              never exit: look for new work every few minutes (for runs of hours or days)

Without short-N, long-N, --topic or --kind a command handles every topic that has work left.
"run" is run.cmd in the yt-workflow folder (in PowerShell type .\run); "python run.py" in scripts does the same.
Only one command works at a time, but "run status" is always allowed. Stop with Ctrl+C and run the same command
again to continue: finished files are never generated again.
"""
import argparse
import ctypes
import logging
import os
import re
import signal
import socket
import sys
import threading
import time
from logging.handlers import RotatingFileHandler

from playwright.sync_api import sync_playwright

import chatgpt
import chrome
import config
import elevenlabs
import firefly
import folders
import narration_length
import premiere
import server
import topics
import vast_tts
import youtube

log = logging.getLogger("run")
STEPS = {   # step name -> (finds the missing files of a topic, generates them)
    "audio": (topics.pending_audio, elevenlabs.run),
    "audio-vast": (topics.pending_audio, vast_tts.run),    # "run audio vast": the same voices, made on Vast
    "clips": (topics.pending_clips, firefly.run),
    "edit": (topics.pending_edits, premiere.run),
    "thumbnails": (topics.pending_thumbnails, chatgpt.run),
    "upload": (topics.pending_uploads, youtube.run),
}
LOCAL_STEPS = {"edit", "audio-vast"}   # steps that do not use Chrome
ENGINE = "vast"     # "run audio vast": the word that picks the Vast voice instead of ElevenLabs
VIDEO = re.compile(r"(short|long)[-_ ]?(\d+)", re.IGNORECASE)   # one video by its number: short-11, long-3
UPDATES = {"short-narration-script-length": "short"}   # "run update <what>" -> the kind of video it changes
BLOCKERS = {   # step name -> (why a topic is skipped by it, what the step is not doing for it)
    "edit": (topics.edit_blockers, "editing"),
    "thumbnails": (topics.thumbnail_blockers, "making a thumbnail"),
    "upload": (topics.upload_blockers, "uploading"),
}


def setup_logging() -> None:
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = RotatingFileHandler(config.LOG_DIR / "automation.log", maxBytes=5_000_000,
                                   backupCount=5, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[logging.StreamHandler(), log_file],
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")


def selected_topics(args) -> list:
    kinds = (args.kind,) if args.kind else ("short", "long")
    return topics.find_topics(kinds, args.topic)


def pending(step, args) -> list:
    find = STEPS[step][0]
    return [job for topic in selected_topics(args) for job in find(topic)]


def step_notes(step, args) -> list[str]:
    """Why selected videos are not handled by a step: an unfinished upload, or (with --topic) what is missing."""
    notes = []
    for topic in selected_topics(args):
        if step == "upload":
            record = topics.read_upload_record(topic)
            if record is not None and record.get("status") == "started":
                notes.append(f"{topic.label}: an upload was started but not finished, see {topics.UPLOAD_RECORD}")
                continue
        if args.topic and step in BLOCKERS and not STEPS[step][0](topic):
            blockers, doing = BLOCKERS[step]
            reasons = blockers(topic) or ["its listing file cannot be used (see the warning above)"]
            notes.append(f"{topic.label}: not {doing}, " + "; ".join(reasons))
    return notes


def show_status(args) -> None:
    for step in STEPS:
        if step == "audio-vast":    # the same files as "audio"
            continue
        jobs = pending(step, args)
        print(f"{step}: {len(jobs)} pending")
        for job in jobs:
            print(f"   {job.label}")
        for note in step_notes(step, args):
            print(f"   ({note})")
    print()
    print(__doc__.split("\n\n", 1)[1].rstrip())     # the commands and options above, for reference
    print(f"Folder: {config.WORK_DIR}   Log: {config.LOG_DIR / 'automation.log'}")


def login() -> None:
    urls = [config.ELEVEN_URL, config.FIREFLY_URL, config.CHATGPT_URL, config.YOUTUBE_STUDIO_URL]
    if not chrome.is_running():
        chrome.launch(urls)
    else:
        with sync_playwright() as playwright:
            _, context = chrome.connect(playwright)
            for url in urls:
                host = url.split("/")[2]
                if not any(host in page.url for page in context.pages):
                    context.new_page().goto(url)
    print(f"The automation Chrome is open. Sign in to ElevenLabs ({config.ELEVEN_WORKSPACE}), Adobe Firefly, ChatGPT\n"
          f"and YouTube Studio (the Google account that owns channel {config.YOUTUBE_CHANNEL_ID}) in that window.\n"
          "It remembers the sign-in, so this is needed only once. Leave the window open.")


def keep_awake() -> None:
    """Stop Windows going to sleep while this script runs (the display may still turn off)."""
    continuous, system_required = 0x80000000, 0x00000001
    ctypes.windll.kernel32.SetThreadExecutionState(continuous | system_required)


def stop_when_input_closes() -> None:
    """For a run started by the page (server.py), which has no Ctrl+C: closing this program's input means the same."""
    def wait() -> None:
        try:
            os.read(sys.stdin.fileno(), 1)
        except OSError:
            pass
        signal.raise_signal(signal.SIGINT)      # like the real Ctrl+C, this also ends a sleep straight away
    threading.Thread(target=wait, daemon=True).start()


def work(steps, args) -> bool:
    """Run passes until nothing is pending, or for ever with --watch. True when everything is done."""
    while steps:
        saved = 0
        try:
            jobs = {step: pending(step, args) for step in steps}
            if any(jobs.values()):
                with sync_playwright() as playwright:
                    context = None      # Chrome is started only for a step that uses it
                    for step in list(steps):
                        if not jobs[step]:
                            continue
                        if context is None and step not in LOCAL_STEPS:
                            _, context = chrome.connect(playwright)
                        try:
                            saved += STEPS[step][1](context, jobs[step])
                        except chrome.NeedsUser as problem:
                            log.error("%s stopped: %s", step, problem)
                            steps.remove(step)
        except Exception:   # e.g. Chrome was closed or the network dropped; the next pass starts fresh
            log.exception("This pass failed")
        left = sum(len(pending(step, args)) for step in steps)
        log.info("Pass finished: %d saved, %d still pending", saved, left)
        if saved and left:
            continue                # progress was made, so go straight on to what is left
        if not args.watch:
            return left == 0
        log.info("Looking for new work again in %d minutes (Ctrl+C to stop)", config.WATCH_INTERVAL // 60)
        time.sleep(config.WATCH_INTERVAL)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command",
                        choices=["login", "status", "folders", "audio", "clips", "edit", "thumbnails", "upload", "all",
                                 "ui", "update"])
    parser.add_argument("video", nargs="*", metavar="vast|short|long|short-N|long-N",
                        help='"vast" (only with audio) makes the voices on the Vast GPU; short or long handles only '
                             'short or only long videos; short-11 or long-3 picks one video by its number: '
                             'short-11 is "11. ferrofluid" in short videos')
    parser.add_argument("--topic", help="only this topic (its folder name)")
    parser.add_argument("--kind", choices=["short", "long"], help="only short or only long videos")
    parser.add_argument("--watch", action="store_true", help="keep running and pick up new work")
    args = parser.parse_args()
    update = None
    if args.command == "update":
        update = next((word.lower() for word in args.video if word.lower() in UPDATES), None)
        if not update:
            parser.error("run update takes one of: " + ", ".join(UPDATES))
        args.video = [word for word in args.video if word.lower() != update]
    words = [word for word in args.video if word.lower() != ENGINE]
    on_vast = len(words) < len(args.video)
    if on_vast and args.command != "audio":
        parser.error(f'"{ENGINE}" only goes with audio: run audio {ENGINE} [short-N|long-N]')
    kinds = {word.lower() for word in words if word.lower() in ("short", "long")}   # "run audio short"
    words = [word for word in words if word.lower() not in ("short", "long")]
    if kinds:
        if len(kinds) > 1:
            parser.error("write short or long, not both (leave both out for all videos)")
        if args.kind and args.kind not in kinds:
            parser.error(f"use either {kinds.pop()} or --kind {args.kind}, not both")
        args.kind = kinds.pop()
    if len(words) > 1:
        parser.error(f"only one video at a time, not {' '.join(words)}")
    args.video = words[0] if words else None
    if args.video:
        named = VIDEO.fullmatch(args.video)
        if not named:
            parser.error(f'"{args.video}" is not a video: write short-11 or long-3')
        if args.topic or (args.kind and args.kind != VIDEO.fullmatch(args.video).group(1).lower()):
            parser.error(f"use either {args.video} or --topic/--kind, not both")
        kind, number = named.group(1).lower(), int(named.group(2))
        if args.command == "folders":       # the folder may not exist yet: that is the point
            setup_logging()
            folders.run([kind], number)
            return 0
        found = topics.find_numbered(kind, number)
        if not found:
            parser.error(f'there is no {kind} video {number} (a folder named "{number}. <topic>")')
        if len(found) > 1:
            parser.error(f"{kind} video {number} is more than one folder: " + ", ".join(topic.name for topic in found))
        args.kind, args.topic = kind, found[0].name
    if args.topic and not selected_topics(args):
        parser.error(f'no topic folder named "{args.topic}"')

    if args.command == "status":
        show_status(args)
        return 0
    if args.command == "folders":
        if args.topic:
            parser.error("run folders takes short-N, long-N or --kind, not --topic")
        setup_logging()
        folders.run((args.kind,) if args.kind else ("short", "long"))
        return 0
    if args.command == "ui":
        return server.serve()
    setup_logging()
    if update:
        if args.kind and args.kind != UPDATES[update]:
            parser.error(f"{update} only changes {UPDATES[update]} videos")
        args.kind = UPDATES[update]
        narration_length.run(selected_topics(args))
        return 0
    if args.command == "login":
        login()
        return 0

    lock = socket.socket()
    try:
        lock.bind(("127.0.0.1", config.LOCK_PORT))
    except OSError:
        sys.exit("run.py is already running in another window.")
    keep_awake()
    if os.environ.get(server.STOP_ENV):
        stop_when_input_closes()
    steps = ["audio", "clips", "edit", "thumbnails", "upload"] if args.command == "all" else [args.command]
    if on_vast:
        steps = ["audio-vast"]
    try:
        return 0 if work(steps, args) else 1
    except KeyboardInterrupt:
        log.info("Stopped with Ctrl+C. Chrome stays open; start run.py again to continue.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
