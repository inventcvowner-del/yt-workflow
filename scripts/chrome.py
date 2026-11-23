"""Starts the real Google Chrome with the automation profile and connects Playwright to it."""
import json
import logging
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

import config

log = logging.getLogger("chrome")
ENDPOINT = f"http://127.0.0.1:{config.CDP_PORT}"


class NeedsUser(Exception):
    """Something only the user can fix (signed out, wrong workspace). The step stops instead of retrying."""


def brief(error) -> str:
    """First line of an error, for one-line log entries (Playwright errors carry a long call log)."""
    lines = str(error).splitlines()
    return lines[0] if lines else type(error).__name__


def find_chrome() -> Path:
    for path in config.CHROME_CANDIDATES:
        if path.exists():
            return path
    raise FileNotFoundError("Google Chrome was not found. Add its path to CHROME_CANDIDATES in config.py.")


def is_running() -> bool:
    try:
        with urllib.request.urlopen(f"{ENDPOINT}/json/version", timeout=3) as response:
            return "Browser" in json.load(response)
    except (OSError, ValueError):
        return False


def launch(urls=()) -> None:
    """Start Chrome as an ordinary independent program, so it stays open when a script stops."""
    config.PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    args = [
        str(find_chrome()),
        f"--remote-debugging-port={config.CDP_PORT}",
        f"--user-data-dir={config.PROFILE_DIR}",
        "--no-first-run",
        "--no-default-browser-check",
        # Keep background tabs working at full speed; the scripts drive several tabs at once.
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        *urls,
    ]
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(args, creationflags=flags, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        if is_running():
            log.info("Chrome started (profile: %s)", config.PROFILE_DIR)
            return
        time.sleep(0.5)
    raise RuntimeError(
        "Chrome did not open its control port. Close every window of the automation Chrome and try again.")


def ensure_running(urls=()) -> None:
    if not is_running():
        launch(urls)


def connect(playwright):
    """Return (browser, context) for the automation Chrome, starting it if needed."""
    ensure_running()
    browser = playwright.chromium.connect_over_cdp(ENDPOINT)
    context = browser.contexts[0]
    context.set_default_timeout(30_000)
    config.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    session = browser.new_browser_cdp_session()
    session.send("Browser.setDownloadBehavior",
                 {"behavior": "allow", "downloadPath": str(config.DOWNLOAD_DIR)})
    return browser, context


def downloaded_files() -> set[Path]:
    return set(config.DOWNLOAD_DIR.iterdir())


def wait_for_download(page, before: set[Path], suffix: str, min_size: int) -> Path:
    """Wait for the download started after `before` was taken and return the finished file.

    Chrome writes a .crdownload file and renames it when complete, so a new file with the
    expected extension is a finished download. Downloads are collected one at a time.
    """
    deadline = time.monotonic() + config.DOWNLOAD_TIMEOUT
    while time.monotonic() < deadline:
        page.wait_for_timeout(1000)
        finished = [f for f in downloaded_files() - before if f.suffix.lower() == suffix]
        if finished:
            size = finished[0].stat().st_size
            if size < min_size:
                raise RuntimeError(f"Downloaded file is too small to be real ({size} bytes): {finished[0]}")
            return finished[0]
    raise TimeoutError(f"No {suffix} file arrived in {config.DOWNLOAD_DIR}")


def store(file: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(file), str(target))
    if not target.is_file():
        raise RuntimeError(f"File was not saved: {target}")


def attach_file(page, selector: str, path: Path) -> None:
    """Choose a file in the page's <input type=file>, whatever its size.

    Playwright's own set_input_files refuses files over 50 MB on this kind of connection, because it cannot tell that
    Chrome runs on the same PC. Chrome only needs the path, so the path is handed over through the DevTools protocol.
    """
    session = page.context.new_cdp_session(page)
    try:
        found = session.send("Runtime.evaluate", {"expression": f"document.querySelector({json.dumps(selector)})"})
        object_id = found["result"].get("objectId")
        if object_id is None:
            raise RuntimeError(f"The page has no file input matching {selector}")
        session.send("DOM.setFileInputFiles", {"files": [str(path)], "objectId": object_id})
    finally:
        session.detach()
