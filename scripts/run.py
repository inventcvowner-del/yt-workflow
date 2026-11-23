r"""Runs the audio (ElevenLabs), clip (Firefly), edit (Premiere), thumbnail (ChatGPT) and upload (YouTube Studio) steps
for every topic.

Commands:
    run status           list what is still missing, and these commands; generates nothing
    run audio            generate the missing voices in ElevenLabs
    run clips            generate the missing clips in Firefly
    run edit             put clips and voices together in Premiere and export final.mp4 (close Premiere first)
    run thumbnails       ask ChatGPT for the missing thumbnails (9:16 for shorts, 16:9 for long videos)
    run upload           upload finished videos to YouTube Studio, scheduled into the release plan
    run all              audio, then clips, then edits, then thumbnails, then uploads
    run login            open the automation Chrome to sign in (needed once, or when a site signs you out)

Add to any command:
    short-N or long-N    only this video, by its number: "run edit short-11" is short videos\11. ferrofluid,
                         "run clips long-3" is long videos\3. hepatitis virus
    --topic "name"       only this topic, by its folder name (with or without its number)
    --kind short|long    only short videos or only long videos
    --watch              never exit: look for new work every few minutes (for runs of hours or days)

Without short-N, long-N, --topic or --kind a command handles every topic that has work left.
"run" is run.cmd in the yt-workflow folder (in PowerShell type .\run); "python run.py" in scripts does the same.
Only one command works at a time, but "run status" is always allowed. Stop with Ctrl+C and run the same command
again to continue: finished files are never generated again.
"""
import argparse
import ctypes
import logging
import re
import socket
import sys
import time
from logging.handlers import RotatingFileHandler

from playwright.sync_api import sync_playwright

import chatgpt
import chrome
import config
import elevenlabs
import firefly
import premiere
import topics
import youtube

log = logging.getLogger("run")
STEPS = {   # step name -> (finds the missing files of a topic, generates them)
    "audio": (topics.pending_audio, elevenlabs.run),
    "clips": (topics.pending_clips, firefly.run),
    "edit": (topics.pending_edits, premiere.run),
    "thumbnails": (topics.pending_thumbnails, chatgpt.run),
    "upload": (topics.pending_uploads, youtube.run),
}
LOCAL_STEPS = {"edit"}   # steps that do not use Chrome
VIDEO = re.compile(r"(short|long)[-_ ]?(\d+)", re.IGNORECASE)   # one video by its number: short-11, long-3
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
    parser.add_argument("command", choices=["login", "status", "audio", "clips", "edit", "thumbnails", "upload", "all"])
    parser.add_argument("video", nargs="?", metavar="short-N|long-N",
                        help='only this video, by its number: short-11 is "11. ferrofluid" in short videos')
    parser.add_argument("--topic", help="only this topic (its folder name)")
    parser.add_argument("--kind", choices=["short", "long"], help="only short or only long videos")
    parser.add_argument("--watch", action="store_true", help="keep running and pick up new work")
    args = parser.parse_args()
    if args.video:
        named = VIDEO.fullmatch(args.video)
        if not named:
            parser.error(f'"{args.video}" is not a video: write short-11 or long-3')
        if args.topic or args.kind:
            parser.error(f"use either {args.video} or --topic/--kind, not both")
        kind, number = named.group(1).lower(), int(named.group(2))
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
    setup_logging()
    if args.command == "login":
        login()
        return 0

    lock = socket.socket()
    try:
        lock.bind(("127.0.0.1", config.LOCK_PORT))
    except OSError:
        sys.exit("run.py is already running in another window.")
    keep_awake()
    steps = ["audio", "clips", "edit", "thumbnails", "upload"] if args.command == "all" else [args.command]
    try:
        return 0 if work(steps, args) else 1
    except KeyboardInterrupt:
        log.info("Stopped with Ctrl+C. Chrome stays open; start run.py again to continue.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
