"""The page behind "run ui": every topic with a button for each step.

A small web server for this PC only. It serves the React app built in ..\\ui\\dist and a JSON API for it. A button
on the page starts run.py as a separate program, one at a time, with the same arguments as the command line, so the
page and the command line always do the same thing. "Regenerate" first moves the old files to the Recycle Bin.
"""
import ctypes
import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import config
import premiere
import topics

UI_DIR = config.WORK_DIR / "ui"
DIST = UI_DIR / "dist"                  # made by "pnpm build" in the ui folder
RUN = Path(__file__).with_name("run.py")
URL = f"http://127.0.0.1:{config.UI_PORT}"
HOSTS = {f"127.0.0.1:{config.UI_PORT}", f"localhost:{config.UI_PORT}"}
ORIGINS = {f"http://{host}" for host in HOSTS}

KINDS = ("short", "long")
COMMANDS = ("audio", "clips", "edit", "thumbnails", "upload", "all")
REGENERATE = ("audio", "clips", "edit", "thumbnails")    # an uploaded video is never made again
STOP_ENV = "YT_WORKFLOW_STOP_ON_INPUT"   # set for the run.py started here: it stops, as with Ctrl+C, when its input closes
STOP_WAIT = 60                           # seconds run.py gets to stop by itself (it closes Premiere and tidies up)
LOG_LIMIT = 5000                         # lines of output kept for the page
TYPES = {
    ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg",
    ".ico": "image/x-icon", ".woff2": "font/woff2",
}


class Refused(Exception):
    """The page asked for something that cannot be done now. The message is shown on the page."""


# ---- what the page shows ----

def numbered(jobs) -> list[dict]:
    return [{"number": job.number, "name": job.target.name, "exists": job.target.exists()} for job in jobs]


def listed_step(items: list[dict], missing: str, uploaded: bool) -> dict:
    """The state of a step that makes one file per voice or clip."""
    done = sum(item["exists"] for item in items)
    if not items:
        return {"state": "blocked", "reasons": [missing], "items": [], "done": 0, "total": 0, "regenerate": False}
    return {"state": "done" if done == len(items) else "pending", "reasons": [], "items": items, "done": done,
            "total": len(items), "regenerate": bool(done) and not uploaded,
            "locked": "already uploaded" if uploaded else None}


def listing_problem(topic) -> str | None:
    listing = topic.path / topics.LISTING_FILE
    if not listing.is_file():
        return f"no {topics.LISTING_FILE}"
    try:
        topics.parse_listing(listing)
    except ValueError as problem:
        return str(problem)
    return None


def edit_step(topic, uploaded: bool) -> dict:
    video = topics.find_final_video(topic.path)
    project = topic.path / config.PREMIERE_PROJECT
    sources = [*topics.clip_files(topic), *topics.voice_files(topic)]
    blockers = [] if video else topics.edit_blockers(topic)
    step = {"state": "done" if video else "blocked" if blockers else "pending", "reasons": blockers,
            "regenerate": False}
    if video:
        step["file"] = video.name
        step["stale"] = not uploaded and any(f.stat().st_mtime > video.stat().st_mtime for f in sources)
    # Editing again is offered when this step's own files are all that stand in its way.
    locked = None
    if video or project.exists():
        other = next((p.name for p in topic.path.glob("*.prproj") if p != project), None)
        if uploaded:
            locked = "already uploaded"
        elif other:
            locked = f"{other} was made by hand"
        elif not sources or topics.pending_clips(topic) or topics.pending_audio(topic):
            locked = "clips or voices are missing"
        step["regenerate"] = locked is None
    step["locked"] = locked
    return step


def thumbnail_step(topic, uploaded: bool) -> dict:
    image = topics.find_thumbnail(topic.path)
    problem = listing_problem(topic)
    if image:
        locked = "already uploaded" if uploaded else problem
        return {"state": "done", "reasons": [], "file": image.name, "regenerate": locked is None, "locked": locked}
    reasons = topics.thumbnail_blockers(topic) or ([problem] if problem else [])
    return {"state": "blocked" if reasons else "pending", "reasons": reasons}


def upload_step(topic) -> dict:
    record = topics.read_upload_record(topic)
    if record is None:
        reasons = topics.upload_blockers(topic)
        if not reasons and (problem := listing_problem(topic)):
            reasons = [problem]
        return {"state": "blocked" if reasons else "pending", "reasons": reasons}
    status, url = record.get("status") or "uploaded", record.get("video_url")
    if status == "started":
        return {"state": "attention", "url": url, "reasons": [
            "an upload was started but not finished: finish or delete that video in YouTube Studio, "
            f"then delete {topics.UPLOAD_RECORD}"]}
    when = record.get("scheduled_for")
    detail = f"Scheduled for {when}" if status == "scheduled" and when else status.capitalize()
    return {"state": "done", "reasons": [], "detail": detail, "url": url}


def video_id(topic) -> str | None:
    """How the command line names the video: short-11."""
    number = topics.ORDER_PREFIX.match(topic.name)
    return f"{topic.kind}-{int(number.group(1))}" if number else None


def topic_state(topic) -> dict:
    uploaded = (topic.path / topics.UPLOAD_RECORD).exists()
    narration = "narration.txt" if topic.kind == "short" else "script.txt"
    return {
        "kind": topic.kind, "name": topic.name, "title": topics.plain_name(topic.name), "id": video_id(topic),
        "uploaded": uploaded,
        "steps": {
            "audio": listed_step(numbered(topics.audio_jobs(topic)), f"no narration in {narration}", uploaded),
            "clips": listed_step(numbered(topics.clip_jobs(topic)), "no clips in video_prompts.txt", uploaded),
            "edit": edit_step(topic, uploaded),
            "thumbnails": thumbnail_step(topic, uploaded),
            "upload": upload_step(topic),
        },
    }


def lock_free() -> bool:
    """False while a run.py holds its lock: one is working, started here or in another window."""
    probe = socket.socket()
    try:
        probe.bind(("127.0.0.1", config.LOCK_PORT))
        return True
    except OSError:
        return False
    finally:
        probe.close()


# ---- running run.py ----

class Runner:
    """Runs run.py as a separate program, one at a time, and keeps what it prints for the page."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.process = None
        self.job = {"command": None, "kind": None, "topic": None, "label": "", "started": None, "finished": None,
                    "exitCode": None}
        self.lines: list[str] = []
        self.dropped = 0        # lines no longer kept: a line's number is its position since the server started

    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def say(self, text: str) -> None:
        with self.lock:
            self.lines.append(text)
            extra = len(self.lines) - LOG_LIMIT
            if extra > 0:
                del self.lines[:extra]
                self.dropped += extra

    def log(self, since: int) -> dict:
        with self.lock:
            return {"next": self.dropped + len(self.lines), "lines": self.lines[max(since - self.dropped, 0):]}

    def snapshot(self) -> dict:
        return {**self.job, "running": self.running()}

    def start(self, command: str, topic=None, kind: str | None = None) -> None:
        arguments = [command]
        if topic is not None:
            arguments += ["--kind", topic.kind, "--topic", topic.name]
            label = f"run {command} " + (video_id(topic) or f'--kind {topic.kind} --topic "{topic.name}"')
        else:
            arguments += ["--kind", kind] if kind else []
            label = f"run {command}" + (f" --kind {kind}" if kind else "")
        self.say(f"> {label}")
        environment = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", STOP_ENV: "1"}
        # Its own process group: Ctrl+C in this window reaches only the server, which then stops run.py once.
        process = subprocess.Popen([sys.executable, str(RUN), *arguments], env=environment,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        self.job = {"command": command, "kind": topic.kind if topic else kind, "topic": topic.name if topic else None,
                    "label": label, "started": time.time(), "finished": None, "exitCode": None}
        self.process = process
        threading.Thread(target=self.follow, args=(process, self.job), daemon=True).start()

    def follow(self, process, job: dict) -> None:
        for line in process.stdout:
            self.say(line.decode("utf-8", "replace").rstrip())
        code = process.wait()
        job["finished"], job["exitCode"] = time.time(), code
        outcome = {0: "finished", 130: "stopped"}.get(code, "finished: something is left to do or went wrong, see above")
        self.say(f"> {job['label']}: {outcome}")

    def stop(self, wait: bool = False) -> None:
        process = self.process
        if not self.running():
            return
        self.say("> stopping, the same as Ctrl+C ...")
        try:
            process.stdin.close()       # run.py takes this as its request to stop
        except OSError:
            pass
        waiter = threading.Thread(target=self.end, args=(process,), daemon=True)
        waiter.start()
        if wait:
            waiter.join()

    def end(self, process) -> None:
        try:
            process.wait(STOP_WAIT)
        except subprocess.TimeoutExpired:
            self.say("> it did not stop by itself and was ended")
            process.kill()


runner = Runner()
action_lock = threading.Lock()      # one button at a time


def state() -> dict:
    job = runner.snapshot()
    return {"job": job, "busyElsewhere": not job["running"] and not lock_free(),
            "topics": [topic_state(topic) for topic in topics.find_topics()]}


# ---- what the buttons do ----

def requested_topic(request: dict):
    kind, name = request.get("kind"), request.get("topic")
    if kind not in KINDS:
        raise Refused("which kind of video? short or long")
    topic = next((topic for topic in topics.find_topics((kind,)) if topic.name == name), None)
    if topic is None:
        raise Refused(f'there is no {kind} video folder named "{name}"')
    return topic


def check_free(command: str) -> None:
    if runner.running():
        raise Refused(f"{runner.job['label']} is still running. Wait for it or stop it first.")
    if not lock_free():
        raise Refused("run.py is working in another window. Wait for it or stop it there first.")
    if command == "edit" and premiere.is_running():
        raise Refused("Premiere is open. Close it first: the edit starts Premiere itself.")


def run_command(request: dict) -> None:
    command, kind = request.get("command"), request.get("kind")
    if command not in COMMANDS:
        raise Refused(f"unknown command: {command}")
    topic = requested_topic(request) if request.get("topic") is not None else None
    if kind not in (None, *KINDS):
        raise Refused("which kind of video? short or long")
    check_free(command)
    runner.start(command, topic, kind)


def old_files(topic, step: str, number: int | None) -> list[Path]:
    """The files a step made for a topic (for one voice or clip when a number is given)."""
    if step in ("audio", "clips"):
        jobs = topics.audio_jobs(topic) if step == "audio" else topics.clip_jobs(topic)
        if number is not None:
            jobs = [job for job in jobs if job.number == number]
        return [job.target for job in jobs if job.target.exists()]
    if step == "edit":
        project = topic.path / config.PREMIERE_PROJECT
        return [f for f in (*topics.final_videos(topic.path), project, project.with_suffix(".prin")) if f.exists()]
    return topics.thumbnail_files(topic.path)


def regenerate(request: dict) -> None:
    """Move what a step made to the Recycle Bin and run the step again for that topic."""
    step, number = request.get("step"), request.get("number")
    if step not in REGENERATE or not (number is None or type(number) is int):
        raise Refused("this cannot be made again")
    topic = requested_topic(request)
    check_free(step)
    current = topic_state(topic)["steps"][step]
    files = old_files(topic, step, number)
    if not current.get("regenerate") or not files:
        raise Refused(current.get("locked") or "there is nothing to make again")
    recycle(files)
    if step == "edit":      # Premiere's previews and auto-saves of the old project
        premiere.remove_leftovers(topic.path, topic.path / config.PREMIERE_PROJECT)
    for file in files:
        runner.say(f"> moved to the Recycle Bin: {file}")
    runner.start(step, topic)


def stop(request: dict) -> None:
    runner.stop()


def open_item(request: dict) -> None:
    topic = requested_topic(request)
    target = {"folder": topic.path, "video": topics.find_final_video(topic.path)}.get(request.get("what"))
    if target is None:
        raise Refused("there is nothing to open")
    os.startfile(target)


ACTIONS = {"/api/run": run_command, "/api/regenerate": regenerate, "/api/stop": stop, "/api/open": open_item}


# ---- Recycle Bin ----

class FileOperation(ctypes.Structure):      # SHFILEOPSTRUCTW
    _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_uint16), ("fAnyOperationsAborted", wintypes.BOOL),
                ("hNameMappings", wintypes.LPVOID), ("lpszProgressTitle", wintypes.LPCWSTR)]


def recycle(files: list[Path]) -> None:
    """Move files to the Windows Recycle Bin, where they can be restored."""
    delete, allow_undo, no_confirmation, silent, no_error_ui = 3, 0x40, 0x10, 0x4, 0x400
    warn_if_destroyed = 0x4000      # Windows asks before deleting for good a file that is too big for the bin
    names = ctypes.create_unicode_buffer("\0".join(str(file) for file in files) + "\0")     # ends with two NULs
    operation = FileOperation(wFunc=delete, pFrom=ctypes.cast(names, wintypes.LPCWSTR),
                              fFlags=allow_undo | no_confirmation | silent | no_error_ui | warn_if_destroyed)
    code = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))
    left = [file.name for file in files if file.exists()]
    if code or operation.fAnyOperationsAborted or left:
        raise OSError(f"could not move to the Recycle Bin: {', '.join(left) or f'error {code}'}")


# ---- the web server ----

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:     # the page asks every second; nothing is printed for that
        pass

    def respond(self, status: int, body: bytes, kind: str, cache: str = "no-store") -> None:
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(body)

    def reply(self, data: dict, status: int = 200) -> None:
        self.respond(status, json.dumps(data).encode("utf-8"), "application/json")

    def trusted(self, changing: bool = False) -> bool:
        """Only this page may use the server. Another website open in the browser must not be able to press buttons."""
        if self.headers.get("Host") not in HOSTS:
            return False
        if not changing:
            return True
        origin = self.headers.get("Origin")
        return (origin is None or origin in ORIGINS) and \
            (self.headers.get("Content-Type") or "").startswith("application/json")

    def page(self, path: str) -> None:
        file = (DIST / path.lstrip("/")).resolve()
        if not file.is_file() or DIST.resolve() not in file.parents:
            file = DIST / "index.html"
        cache = "no-store" if file.name == "index.html" else "max-age=31536000, immutable"
        self.respond(200, file.read_bytes(), TYPES.get(file.suffix.lower(), "application/octet-stream"), cache)

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        try:
            if not self.trusted():
                self.reply({"error": "not allowed"}, 403)
            elif url.path == "/api/state":
                self.reply(state())
            elif url.path == "/api/log":
                self.reply(runner.log(int(parse_qs(url.query).get("since", ["0"])[0])))
            elif url.path.startswith("/api/"):
                self.reply({"error": "unknown address"}, 404)
            else:
                self.page(url.path)
        except ConnectionError:     # the browser went away
            pass
        except Exception as problem:    # e.g. a file of a topic that cannot be read: the page shows it and asks again
            self.reply({"error": f"{type(problem).__name__}: {problem}"}, 500)

    def do_POST(self) -> None:
        action = ACTIONS.get(urlsplit(self.path).path)
        try:
            if not self.trusted(changing=True):
                self.reply({"error": "not allowed"}, 403)
            elif action is None:
                self.reply({"error": "unknown address"}, 404)
            else:
                request = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 65536)) or b"{}")
                if not isinstance(request, dict):
                    raise ValueError("not an object")
                with action_lock:
                    action(request)
                self.reply({"ok": True})
        except ConnectionError:
            pass
        except Refused as problem:
            self.reply({"error": str(problem)}, 409)
        except ValueError as problem:
            self.reply({"error": f"bad request: {problem}"}, 400)
        except OSError as problem:
            self.reply({"error": str(problem)}, 500)


class Server(ThreadingHTTPServer):
    allow_reuse_address = False     # on Windows, reuse would let a second server share the port
    daemon_threads = True


def serve() -> int:
    """Run the page until Ctrl+C. Returns the exit code."""
    if not (DIST / "index.html").is_file():
        print(f"The page is not built yet. In {UI_DIR} run:  pnpm install  and then  pnpm build")
        return 1
    logging.getLogger("topics").setLevel(logging.ERROR)     # its warnings are shown on the page, not printed each second
    try:
        server = Server(("127.0.0.1", config.UI_PORT), Handler)
    except OSError:
        print(f"The page is already running in another window: {URL}")
        webbrowser.open(URL)
        return 0
    print(f"The workflow page is open at {URL}")
    print("Leave this window open. Ctrl+C here closes the page and stops what it is running.", flush=True)
    webbrowser.open(URL)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        runner.stop(wait=True)
        server.server_close()
    return 0
