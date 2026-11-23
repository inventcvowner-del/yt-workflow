"""Runs the audio (ElevenLabs), clip (Firefly), thumbnail (ChatGPT) and upload (YouTube Studio) steps for every topic.

    python run.py login          open the automation Chrome to sign in (needed once)
    python run.py status         list what is still missing; generates nothing
    python run.py audio          generate the missing voices in ElevenLabs
    python run.py clips          generate the missing clips in Firefly
    python run.py thumbnails     ask ChatGPT for the missing thumbnails (9:16 for shorts, 16:9 for long videos)
    python run.py upload         upload finished videos to YouTube Studio, scheduled into the release plan
    python run.py all            audio, then clips, then thumbnails, then uploads

Options:
    --topic "folder name"        only this topic
    --kind short|long            only short videos or only long videos
    --watch                      never exit: look for new work every few minutes (for runs of hours or days)

Finished files are never generated again, so a stopped run continues where it left off.
"""
import argparse
import ctypes
import logging
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
import topics
import youtube

log = logging.getLogger("run")
STEPS = {   # step name -> (finds the missing files of a topic, generates them)
    "audio": (topics.pending_audio, elevenlabs.run),
    "clips": (topics.pending_clips, firefly.run),
    "thumbnails": (topics.pending_thumbnails, chatgpt.run),
    "upload": (topics.pending_uploads, youtube.run),
}
BLOCKERS = {   # step name -> (why a topic is skipped by it, what the step is not doing for it)
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
                    _, context = chrome.connect(playwright)
                    for step in list(steps):
                        if not jobs[step]:
                            continue
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
    parser.add_argument("command", choices=["login", "status", "audio", "clips", "thumbnails", "upload", "all"])
    parser.add_argument("--topic", help="only this topic (its folder name)")
    parser.add_argument("--kind", choices=["short", "long"], help="only short or only long videos")
    parser.add_argument("--watch", action="store_true", help="keep running and pick up new work")
    args = parser.parse_args()
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
    steps = ["audio", "clips", "thumbnails", "upload"] if args.command == "all" else [args.command]
    try:
        return 0 if work(steps, args) else 1
    except KeyboardInterrupt:
        log.info("Stopped with Ctrl+C. Chrome stays open; start run.py again to continue.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
