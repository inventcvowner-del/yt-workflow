"""Step 5: asks ChatGPT for a thumbnail of each video and saves it in the topic folder as thumbnail.png."""
import logging
import re
import struct
import time
from pathlib import Path

import chrome
import config

log = logging.getLogger("chatgpt")

COMPOSER = "form[data-chatgpt-composer]"
USER_MESSAGE = "[data-user-message-bubble=true]"
REPLY = "[data-response-body]"
PREVIEW = "button[data-testid=generated-image-preview]"
STOP_BUTTON = re.compile(r"^Stop")
PREFERENCE = re.compile(r"Which (option|response) do you prefer", re.IGNORECASE)
SELECTORS = {"message": USER_MESSAGE, "reply": REPLY, "preview": PREVIEW}

# The editor takes a long multi-line request reliably only through a paste (typing reflows the lines).
PASTE_JS = """(editor, text) => {
    const data = new DataTransfer();
    data.setData('text/plain', text);
    editor.dispatchEvent(new ClipboardEvent('paste', {clipboardData: data, bubbles: true, cancelable: true}));
}"""
# ChatGPT keeps only the messages near the viewport on the page, so messages are never counted: the newest message of
# the user is remembered as an element instead, and a new request shows as a different newest one.
NEWEST_MESSAGE_JS = """selector => {
    const messages = document.querySelectorAll(selector);
    return messages[messages.length - 1] || null;
}"""
IS_NEW_MESSAGE_JS = """([selector, before]) => {
    const messages = document.querySelectorAll(selector);
    return (messages[messages.length - 1] || null) !== before;
}"""
# Everything the page shows after the newest message of the user is ChatGPT's answer to it.
AFTER_NEWEST_JS = """(selectors) => {
    const messages = document.querySelectorAll(selectors.message);
    const last = messages[messages.length - 1];
    const follows = element => last && (last.compareDocumentPosition(element) & Node.DOCUMENT_POSITION_FOLLOWING);
    return {
        images: Array.from(document.querySelectorAll(selectors.preview)).filter(follows).length,
        reply: Array.from(document.querySelectorAll(selectors.reply)).filter(follows)
            .map(element => element.innerText.replace(/\\s+/g, ' ').trim()).filter(Boolean).join(' | '),
    };
}"""
LOADED_IMAGES_JS = "images => images.filter(image => image.complete && image.naturalWidth > 0).length"


def chat_id() -> str:
    return config.CHATGPT_URL.rstrip("/").rsplit("/", 1)[-1]


def open_page(context):
    """The tab already showing the thumbnail chat, or a new one (other ChatGPT tabs are left alone)."""
    return next((page for page in context.pages if chat_id() in page.url), None) or context.new_page()


def dismiss_dialogs(page) -> None:
    """Close pop-ups (announcements, offers) that would block every click."""
    for _ in range(3):
        if not page.get_by_role("dialog").filter(visible=True).count():
            return
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)


def load(page) -> None:
    """Open the thumbnail chat. Stops (for the user to fix) when ChatGPT is signed out or the chat is gone."""
    page.goto(config.CHATGPT_URL, wait_until="domcontentloaded")
    box = page.get_by_role("textbox", name="Ask ChatGPT")
    login = page.get_by_role("button", name=re.compile(r"^Log in$", re.IGNORECASE))
    for _ in range(60):
        if "/auth/" in page.url or login.first.is_visible():
            raise chrome.NeedsUser(
                "ChatGPT is signed out in the automation Chrome. Run 'run.py login', sign in, then start again.")
        if box.is_visible():
            break
        page.wait_for_timeout(1000)
    else:
        raise RuntimeError("The ChatGPT chat did not load")
    if chat_id() not in page.url:
        raise chrome.NeedsUser(f"ChatGPT opened {page.url} instead of the thumbnail chat {config.CHATGPT_URL}. "
                               "Is the chat deleted? Nothing was sent.")
    dismiss_dialogs(page)
    skip_preference(page)


def skip_preference(page) -> None:
    """Answer ChatGPT's "Which option do you prefer?" with Skip.

    ChatGPT now and then shows two options for a request and asks which is better. Until that is answered its
    images cannot be clicked, so a request would look as if it had no image. Skip keeps the first option.
    """
    question = page.get_by_text(PREFERENCE).filter(visible=True)
    if question.count():
        log.info("ChatGPT asked which option is better; skipping the question")
        page.get_by_role("button", name="Skip", exact=True).click()
        page.wait_for_timeout(2000)


def settle(page) -> None:
    """Wait until the chat history has finished loading (it fills in after the page itself)."""
    last, stable = -1, 0
    for _ in range(40):
        count = page.locator(USER_MESSAGE).count() + page.locator(PREVIEW).count()
        stable = stable + 1 if count == last else 0
        last = count
        if stable >= 3:
            return
        page.wait_for_timeout(1000)


def clear_composer(page) -> None:
    """Remove anything left in the request box (a draft, an attachment) so that only this request is sent."""
    composer = page.locator(COMPOSER)
    remove = composer.get_by_role("button", name=re.compile(r"^Remove "))
    for _ in range(10):
        if not remove.count():
            break
        remove.first.click()
        page.wait_for_timeout(500)
    composer.get_by_role("textbox", name="Ask ChatGPT").click()
    page.keyboard.press("Control+A")
    page.keyboard.press("Backspace")


def attach(page, files) -> None:
    """Attach images (the channel logo) to the request and wait until ChatGPT has taken each one."""
    composer = page.locator(COMPOSER)
    for number, file in enumerate(files, start=1):
        if not file.is_file():
            raise chrome.NeedsUser(
                f"{file} (THUMBNAIL_ATTACHMENTS in config.py) was not found. Nothing was sent.")
        chrome.attach_file(page, f"{COMPOSER} input[type=file][multiple]", file)
        for _ in range(60):
            if composer.locator("img").evaluate_all(LOADED_IMAGES_JS) >= number:
                break
            page.wait_for_timeout(1000)
        else:
            raise RuntimeError(f"ChatGPT did not finish taking {file.name}")


def fill(page, text: str) -> None:
    box = page.locator(COMPOSER).get_by_role("textbox", name="Ask ChatGPT")
    box.click()
    box.evaluate(PASTE_JS, text)
    for _ in range(40):
        if box.inner_text().split() == text.split():
            return
        page.wait_for_timeout(250)
    raise RuntimeError("The ChatGPT box does not hold the full request; nothing was sent")


def build_prompt(job) -> str:
    ratio, shape = config.THUMBNAIL_RATIO[job.topic.kind]
    logo = config.THUMBNAIL_LOGO_NOTE + "\n" if config.THUMBNAIL_ATTACHMENTS else ""
    return config.THUMBNAIL_PROMPT.format(ratio=ratio, shape=shape, logo=logo,
                                          title=job.title, description=job.description)


def busy(page) -> bool:
    """ChatGPT shows a Stop button in the request box for as long as it is answering."""
    return page.locator(COMPOSER).get_by_role("button", name=STOP_BUTTON).count() > 0


def scroll_to_bottom(page) -> None:
    """Show the newest messages: the chat keeps only those near the viewport on the page."""
    button = page.get_by_role("button", name="Scroll to bottom")
    if button.count() and button.first.is_visible():
        button.first.click()
        page.wait_for_timeout(1000)


def answer(page) -> dict:
    """ChatGPT's answer to the newest request: how many images it made and what it wrote."""
    skip_preference(page)
    scroll_to_bottom(page)
    return page.evaluate(AFTER_NEWEST_JS, SELECTORS)


def notices(page) -> str:
    texts = page.locator("[role=alert]").all_inner_texts()
    return " | ".join(" ".join(text.split()) for text in texts if text.strip())


def send(page) -> None:
    """Click Send once, then wait until ChatGPT has finished answering."""
    scroll_to_bottom(page)
    before = page.evaluate_handle(NEWEST_MESSAGE_JS, USER_MESSAGE)
    page.locator(COMPOSER).get_by_role("button", name="Send", exact=True).click()
    started = time.monotonic()
    sent = saw_busy = False
    quiet = 0
    while True:
        page.wait_for_timeout(2000)
        working = busy(page)
        saw_busy = saw_busy or working
        sent = sent or working or page.evaluate(IS_NEW_MESSAGE_JS, [USER_MESSAGE, before])
        if not sent:
            if time.monotonic() - started > 60:
                raise RuntimeError(f"ChatGPT did not take the request. {notices(page)}")
            continue
        quiet = 0 if working else quiet + 1
        if quiet >= 2:        # no Stop button for two checks in a row; an instant answer has no Stop button at all
            found = answer(page)
            if saw_busy or found["images"] or found["reply"]:
                return
        if time.monotonic() - started > config.CHATGPT_TIMEOUT:
            raise TimeoutError("ChatGPT did not finish in time")


def image_size(path: Path) -> tuple[int, int]:
    """Width and height of a PNG or JPEG, read from its header (no imaging library is installed)."""
    data = path.read_bytes()
    if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
        return struct.unpack(">II", data[16:24])
    if data[:2] == b"\xff\xd8":
        position = 2
        while position + 9 < len(data):
            if data[position] != 0xFF:
                position += 1
                continue
            marker = data[position + 1]
            if marker in (0x01, 0xD8) or 0xD0 <= marker <= 0xD7:     # markers that have no length
                position += 2
                continue
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):    # the frame header holds the size
                height, width = struct.unpack(">HH", data[position + 5:position + 9])
                return width, height
            position += 2 + struct.unpack(">H", data[position + 2:position + 4])[0]
    raise ValueError(f"{path.name} is not a PNG or JPEG image")


def check_image(file: Path, kind: str) -> tuple[int, int]:
    """Refuse an image that is not the aspect ratio asked for (9:16 for shorts, 16:9 for long videos)."""
    width, height = image_size(file)
    ratio = config.THUMBNAIL_RATIO[kind][0]
    wide, high = (int(part) for part in ratio.split(":"))
    if abs(width / height - wide / high) > config.THUMBNAIL_RATIO_TOLERANCE * wide / high:
        raise ValueError(f"ChatGPT made a {width}x{height} image, not {ratio}. It was left in {file}")
    return width, height


def download(page) -> Path:
    """Open the newest image of the chat in ChatGPT's viewer and use its Download button. Returns the file that arrives."""
    page.locator(PREVIEW).filter(visible=True).last.click()
    button = page.get_by_role("dialog").get_by_role("button", name="Download", exact=True)
    button.wait_for()
    before = chrome.downloaded_files()
    button.click()
    try:
        return chrome.wait_for_download(page, before, ".png", min_size=50_000)
    finally:
        page.keyboard.press("Escape")            # close the viewer


def save_thumbnail(page, job) -> tuple[int, int]:
    """Take the image ChatGPT made for the request just sent and save it as the topic's thumbnail."""
    found = answer(page)
    if not found["images"]:
        raise RuntimeError(f"ChatGPT did not make an image. It answered: {found['reply'] or 'nothing'}")
    if found["images"] > 1:
        log.info("%s: ChatGPT made %d images; taking the last", job.label, found["images"])
    for attempt in range(1, 4):                  # the image exists in the chat, so the download may be retried
        try:
            file = download(page)
            break
        except Exception as error:
            if attempt == 3 or not page.context.browser.is_connected():
                raise
            log.warning("%s: download failed (try %d): %s", job.label, attempt, chrome.brief(error))
    size = check_image(file, job.topic.kind)
    chrome.store(file, job.target)
    return size


def run(context, jobs) -> int:
    """Make the thumbnail of every video in `jobs`, one after another. Returns how many were saved."""
    page = open_page(context)
    saved = 0
    log.info("%d thumbnail(s) to make", len(jobs))
    for job in jobs:
        if job.target.exists():
            continue
        prompt = build_prompt(job)
        for attempt in range(1, config.CHATGPT_MAX_ATTEMPTS + 1):
            try:
                load(page)
                settle(page)
                clear_composer(page)
                attach(page, config.THUMBNAIL_ATTACHMENTS)
                fill(page, prompt)
                break
            except chrome.NeedsUser:
                raise
            except Exception as error:           # page hiccup before anything was sent: safe to try again
                if not context.browser.is_connected():
                    raise
                log.warning("%s: setup failed (try %d): %s", job.label, attempt, chrome.brief(error))
        else:
            log.error("Giving up on %s for now", job.label)
            continue

        ratio = config.THUMBNAIL_RATIO[job.topic.kind][0]
        log.info("Asking ChatGPT for the %s thumbnail of %s", ratio, job.label)
        started = time.monotonic()
        try:
            send(page)
            width, height = save_thumbnail(page, job)
        except Exception as error:
            # The request was sent, so an image may already have been made; it is never asked for twice automatically.
            raise chrome.NeedsUser(
                f"{job.label}: the request was sent to ChatGPT but no thumbnail was saved ({chrome.brief(error)}). "
                f"Look at the chat {config.CHATGPT_URL}; if the image is there, download it as {job.target}. "
                "Thumbnails are stopped until run.py is started again.") from error
        saved += 1
        log.info("Saved %s (%dx%d, %.0f s)", job.target, width, height, time.monotonic() - started)
    return saved
