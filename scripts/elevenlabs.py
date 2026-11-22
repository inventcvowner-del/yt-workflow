"""Step 2: generates narration audio on the ElevenLabs Text to Speech page."""
import logging
import re
import time

import chrome
import config
import topics

log = logging.getLogger("elevenlabs")

# The editor only accepts text reliably through a paste; typing into it loses every line after the first.
PASTE_JS = """(editor, text) => {
    const data = new DataTransfer();
    data.setData('text/plain', text);
    editor.dispatchEvent(new ClipboardEvent('paste', {clipboardData: data, bubbles: true, cancelable: true}));
}"""
COUNTER = re.compile(r"^([\d,]+) / [\d,]+$")


def open_page(context):
    for page in context.pages:
        if page.url.startswith("https://elevenlabs.io/app"):
            return page
    return context.new_page()


def narration(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").split("\n")).strip()


def load(page) -> None:
    page.goto(config.ELEVEN_URL, wait_until="domcontentloaded")
    editor = page.get_by_test_id("tts-editor")
    for _ in range(60):
        if "/sign-in" in page.url:
            raise chrome.NeedsUser(
                "ElevenLabs is signed out in the automation Chrome. Run 'run.py login', sign in, then start again.")
        if editor.is_visible():
            return
        page.wait_for_timeout(1000)
    raise RuntimeError("The ElevenLabs Text to Speech page did not load")


def check_workspace(page) -> None:
    """Account safety check: credits must only ever be spent in the configured workspace."""
    page.get_by_role("button", name="Your profile").click()
    menu = page.get_by_role("dialog").filter(has=page.get_by_role("button", name="Switch workspace")).last
    menu.wait_for()
    lines = [text.replace("\u2019", "'").strip() for text in menu.locator("p").all_inner_texts()]
    page.keyboard.press("Escape")
    menu.wait_for(state="hidden")
    if config.ELEVEN_WORKSPACE not in lines:
        found = [line for line in lines if "workspace" in line.lower()] or lines[:3]
        raise chrome.NeedsUser(
            f"ElevenLabs is not in '{config.ELEVEN_WORKSPACE}' (it shows {found}). Nothing was generated.")


def has_setting(page, kind, value) -> bool:
    return page.get_by_role("button", name=f"Select {kind} - {value}", exact=True).is_visible()


def choose_voice(page) -> None:
    if has_setting(page, "voice", config.ELEVEN_VOICE):
        return
    page.get_by_role("button", name=re.compile(r"^Select voice")).click()
    dialog = page.get_by_role("dialog", name="Select a voice")
    dialog.get_by_role("tab", name="My voices").click()
    dialog.get_by_role("button", name=f"Select {config.ELEVEN_VOICE}", exact=True).click()
    dialog.wait_for(state="hidden")
    if not has_setting(page, "voice", config.ELEVEN_VOICE):
        raise RuntimeError(f"Could not select the voice '{config.ELEVEN_VOICE}'")


def choose_model(page) -> None:
    if has_setting(page, "model", config.ELEVEN_MODEL):
        return
    page.get_by_role("button", name=re.compile(r"^Select model")).click()
    dialog = page.get_by_role("dialog", name="Select a model")
    dialog.get_by_role("radio", name=re.compile(rf"^{re.escape(config.ELEVEN_MODEL)}\b")).click()
    dialog.wait_for(state="hidden")
    if not has_setting(page, "model", config.ELEVEN_MODEL):
        raise RuntimeError(f"Could not select the model '{config.ELEVEN_MODEL}'")


def counted(page) -> int:
    """Characters the editor really holds (its own counter), or -1 while no counter is shown."""
    for text in page.locator("main p").all_inner_texts():
        match = COUNTER.match(text.strip())
        if match:
            return int(match.group(1).replace(",", ""))
    return -1


def enter_text(page, text: str) -> None:
    """Put exactly `text` in the editor. ElevenLabs restores the previous draft after a reload, so clear first."""
    editor = page.get_by_test_id("tts-editor")
    if editor.inner_text().strip():
        page.locator("main").get_by_role("button", name="Clear text").click()
    for _ in range(20):
        if not editor.inner_text().strip():
            break
        page.wait_for_timeout(250)
    else:
        raise RuntimeError("The ElevenLabs editor could not be cleared")

    editor.click()
    page.locator("main [contenteditable=true]").evaluate(PASTE_JS, text)
    for _ in range(40):
        if counted(page) == len(text) and editor.inner_text().split() == text.split():
            return
        page.wait_for_timeout(250)
    raise RuntimeError(
        f"The ElevenLabs editor does not hold exactly this section ({counted(page)} characters, "
        f"expected {len(text)}); nothing was generated")


def generate_and_save(page, job) -> None:
    main = page.locator("main")
    generate = main.get_by_role("button", name=re.compile(r"^Generate speech"))
    regenerate = main.get_by_role("button", name=re.compile(r"^Regenerate speech"))
    card = (main.locator("div")
            .filter(has=page.get_by_text("Generation 1", exact=True))
            .filter(has=page.get_by_role("button", name="Download"))
            .last)
    download = card.get_by_role("button", name="Download")

    generate.click()
    deadline = time.monotonic() + config.ELEVEN_TIMEOUT
    idle_checks = 0
    while True:
        page.wait_for_timeout(2000)
        if regenerate.is_visible() and regenerate.is_enabled() and download.is_visible():
            break
        idle_checks = idle_checks + 1 if generate.is_visible() and generate.is_enabled() else 0
        if idle_checks >= 3:
            raise RuntimeError("ElevenLabs stopped without showing any audio")
        if time.monotonic() > deadline:
            raise TimeoutError("ElevenLabs did not finish in time")

    before = chrome.downloaded_files()
    download.click()
    chrome.store(chrome.wait_for_download(page, before, ".mp3", min_size=2_000), job.target)


def credits(page) -> str:
    texts = page.locator("main").get_by_text(re.compile(r"credits remaining")).all_inner_texts()
    return texts[0].strip() if texts else "credits unknown"


def run(context, jobs) -> int:
    """Generate every voice file in `jobs`, one after another. Returns how many were saved."""
    page = open_page(context)
    saved = 0
    log.info("%d voice files to generate", len(jobs))
    for job in jobs:
        if job.target.exists():
            continue
        topics.save_sections(job.topic)
        text = narration(job.text)
        for attempt in range(1, config.ELEVEN_MAX_ATTEMPTS + 1):
            try:
                load(page)
                check_workspace(page)
                choose_voice(page)
                choose_model(page)
                enter_text(page, text)
                break
            except chrome.NeedsUser:
                raise
            except Exception as error:   # page hiccup before anything was generated: safe to try again
                if not context.browser.is_connected():
                    raise
                log.warning("%s: setup failed (try %d): %s", job.label, attempt, chrome.brief(error))
        else:
            log.error("Giving up on %s for now", job.label)
            continue

        log.info("Generating %s (%d characters)", job.label, len(text))
        try:
            generate_and_save(page, job)
        except Exception as error:
            # Credits may already be spent, so this is never retried automatically.
            raise chrome.NeedsUser(
                f"{job.label}: Generate was clicked but the audio was not saved ({chrome.brief(error)}). "
                f"Check the History tab in ElevenLabs; if the audio is there, download it as {job.target}. "
                "Audio is stopped until run.py is started again.") from error
        saved += 1
        log.info("Saved %s (%s)", job.target, credits(page))
    return saved
