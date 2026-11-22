"""Step 4: generates video clips in Adobe Firefly, several tabs at once."""
import logging
import re
import time
from collections import Counter, deque

import chrome
import config

log = logging.getLogger("firefly")


class Tab:
    def __init__(self, page, number):
        self.page = page
        self.number = number
        self.job = None
        self.started = 0.0
        self.idle_checks = 0
        self.free_at = 0.0


def open_tabs(context, count) -> list[Tab]:
    pages = [page for page in context.pages if page.url.startswith("https://firefly.adobe.com")]
    while len(pages) < count:
        pages.append(context.new_page())
    return [Tab(page, number) for number, page in enumerate(pages[:count], start=1)]


def choose(page, picker_name, value) -> None:
    picker = page.get_by_role("combobox", name=picker_name)
    if value in picker.aria_snapshot():
        return
    picker.click()
    page.get_by_role("option").filter(has_text=value).first.click()
    for _ in range(20):
        if value in picker.aria_snapshot():
            return
        page.wait_for_timeout(500)
    raise RuntimeError(f"Could not set {picker_name} to {value}")


def remove_videos(page) -> None:
    """Delete the generated videos shown on the page.

    Firefly brings a tab's videos back after a reload and they use a lot of memory. The clip is
    saved with the page's own Download button, so no other video may be on the page.
    """
    actions = page.get_by_role("button", name="Video Actions")
    for _ in range(20):
        count = actions.count()
        if count == 0:
            return
        actions.first.click()
        page.get_by_role("menuitem", name="Delete").click()
        for _ in range(20):
            if actions.count() < count:
                break
            page.wait_for_timeout(500)
    raise RuntimeError("Could not remove earlier videos from the Firefly page")


def prepare(tab: Tab, context) -> None:
    """Load Firefly in the tab and leave it ready to generate the tab's clip: clean page, settings, prompt."""
    if tab.page.is_closed():
        tab.page = context.new_page()
    page, job = tab.page, tab.job
    page.goto(config.FIREFLY_URL, wait_until="domcontentloaded")
    prompt = page.get_by_role("textbox", name="Prompt")
    prompt.wait_for(timeout=60_000)
    account = page.get_by_role("button", name=re.compile(r"Account$"))
    for _ in range(30):
        if account.is_visible():
            break
        page.wait_for_timeout(1000)
    else:
        raise chrome.NeedsUser(
            "Adobe Firefly is signed out in the automation Chrome. Run 'run.py login', sign in, then start again.")

    page.wait_for_timeout(config.FIREFLY_SETTLE * 1000)   # Firefly puts back the tab's last prompt, seed and videos
    remove_videos(page)
    for picker_name, value in config.FIREFLY_SETTINGS.items():
        choose(page, picker_name, value)
    page.get_by_role("textbox", name="Seed").fill("")
    prompt.fill(job.prompt)
    if prompt.input_value() != job.prompt:
        raise RuntimeError("The Prompt box does not hold the full prompt")
    if page.get_by_role("button", name="Download", exact=True).is_enabled():
        raise RuntimeError("An earlier video is still on the page")


def start(tab: Tab, context) -> None:
    prepare(tab, context)
    page = tab.page
    generate = page.get_by_role("button", name="Generate", exact=True)
    generate.click()
    for _ in range(40):                      # the button is disabled while Firefly is generating
        if not generate.is_enabled():
            break
        page.wait_for_timeout(500)
    else:
        raise RuntimeError(f"Generation did not start. {notices(page)}")
    tab.started = time.monotonic()
    tab.idle_checks = 0
    log.info("Tab %d: generating %s", tab.number, tab.job.label)


def check(tab: Tab) -> str:
    """'done', 'failed' or 'running' for the clip this tab is generating."""
    page = tab.page
    if page.get_by_role("button", name="Generate", exact=True).is_enabled():   # generating has stopped
        if page.get_by_role("button", name="Download", exact=True).is_enabled():
            return "done"
        # Nothing to download. Checked twice, because Generate can come back a moment before Download does.
        tab.idle_checks += 1
        if tab.idle_checks >= 2:
            return "failed"
    else:
        tab.idle_checks = 0
    if time.monotonic() - tab.started > config.FIREFLY_TIMEOUT:
        return "failed"
    return "running"


def notices(page) -> str:
    texts = page.locator("[role=alert], sp-toast").all_inner_texts()
    return " | ".join(" ".join(text.split()) for text in texts if text.strip())


def letters(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def is_named_after(file, prompt: str) -> bool:
    """Firefly names a download 'Firefly <start of the prompt>.mp4'; this confirms the file is this clip.

    A name in any other form cannot be compared and is accepted.
    """
    name = re.sub(r" \(\d+\)$", "", file.stem)       # Chrome adds " (1)" when the name is already taken
    if not name.startswith("Firefly "):
        return True
    return letters(prompt).startswith(letters(name.removeprefix("Firefly ")))


def save(tab: Tab) -> None:
    before = chrome.downloaded_files()
    tab.page.get_by_role("button", name="Download", exact=True).click()
    file = chrome.wait_for_download(tab.page, before, ".mp4", min_size=100_000)
    if not is_named_after(file, tab.job.prompt):
        file.unlink()
        raise RuntimeError(f"Firefly downloaded a different video: {file.name}")
    chrome.store(file, tab.job.target)
    minutes = (time.monotonic() - tab.started) / 60
    log.info("Tab %d: saved %s (%.1f min)", tab.number, tab.job.target, minutes)


def run(context, jobs) -> int:
    """Generate every clip in `jobs`, one per tab at a time. Returns how many were saved."""
    queue = deque(jobs)
    attempts = Counter()
    saved = 0
    tabs = open_tabs(context, min(config.FIREFLY_TABS, len(jobs)))
    log.info("Clips to generate: %d, using %d tab(s)", len(jobs), len(tabs))

    while queue or any(tab.job for tab in tabs):
        for tab in tabs:
            try:
                if tab.job is None:
                    if queue and time.monotonic() >= tab.free_at:
                        tab.job = queue.popleft()
                        if tab.job.target.exists():
                            tab.job = None
                        else:
                            start(tab, context)
                    continue
                state = check(tab)
                if state == "done":
                    save(tab)
                    saved += 1
                    tab.job = None
                    remove_videos(tab.page)
                elif state == "failed":
                    raise RuntimeError(f"Generation failed or timed out. {notices(tab.page)}")
            except chrome.NeedsUser:
                raise
            except Exception as error:   # any page hiccup: put the clip back and carry on with the rest
                if not context.browser.is_connected():
                    raise
                job, tab.job = tab.job, None
                tab.free_at = time.monotonic() + config.FIREFLY_RETRY_PAUSE
                if job is None:          # the clip is saved; only tidying the page afterwards failed
                    log.warning("Tab %d: %s", tab.number, chrome.brief(error))
                    continue
                attempts[job] += 1
                if attempts[job] < config.FIREFLY_MAX_ATTEMPTS:
                    log.warning("Tab %d: %s failed (try %d): %s",
                                tab.number, job.label, attempts[job], chrome.brief(error))
                    queue.append(job)
                else:
                    log.error("Tab %d: giving up on %s for now: %s", tab.number, job.label, chrome.brief(error))
        time.sleep(config.FIREFLY_POLL)
    return saved
