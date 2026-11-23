"""Step 6: uploads a finished video to YouTube Studio and schedules it into the next slot of the release plan."""
import logging
import re
import time
from datetime import datetime

import chrome
import config
import release
import topics

log = logging.getLogger("youtube")

STUDIO = "https://studio.youtube.com"
VIDEO_ID = re.compile(r"(?:shorts/|youtu\.be/|[?&]v=|/video/)([\w-]{11})")
UPLOAD_FAILED = re.compile(r"\b(fail\w*|error|abandoned|rejected|limit reached)\b", re.IGNORECASE)
REFUSED = re.compile(r"upload limit|verify your|verification", re.IGNORECASE)     # Studio will not take the file at all
CHECKS_DONE = re.compile(r"checks complete", re.IGNORECASE)
NO_ISSUES = re.compile(r"no issues found", re.IGNORECASE)
POPUP_BUTTONS = re.compile(r"^(Continue|Got it|Dismiss|Not now|No thanks)$", re.IGNORECASE)
QUESTIONS = ("VIDEO_HAS_ALTERED_CONTENT", "VIDEO_PAID_PRODUCT_PLACEMENT")   # "AI use" and "Paid promotion"
DATE_FORMATS = ("%b %d, %Y", "%d %b %Y")     # Studio in English (US), and in English (India or UK)
TIME_FORMATS = ("%I:%M %p", "%H:%M")         # a 12-hour and a 24-hour clock
# Studio writes a time as "6:00<narrow no-break space>PM"; comparisons turn those into ordinary spaces first.
SPACES = str.maketrans({"\u202f": " ", "\u00a0": " "})


def clean(text: str) -> str:
    return " ".join(text.translate(SPACES).split())


def same_text(shown: str, wanted: str) -> bool:
    """Line-by-line comparison; the editors add a trailing newline of their own."""
    def lines(text):
        return [line.rstrip() for line in text.replace("\r\n", "\n").strip().split("\n")]
    return lines(shown) == lines(wanted)


def open_page(context):
    page = next((p for p in context.pages if p.url.startswith(STUDIO)), None) or context.new_page()
    page.on("dialog", lambda dialog: dialog.accept())    # "Leave site?" when an earlier upload dialog is still open
    return page


def clear_popups(page) -> None:
    """Close Studio's welcome and announcement pop-ups. While one is open, every click on the page is blocked."""
    for _ in range(5):
        if not page.locator("tp-yt-iron-overlay-backdrop[opened]").filter(visible=True).count():
            return
        button = page.locator("ytcp-dialog, tp-yt-paper-dialog").get_by_role("button", name=POPUP_BUTTONS).filter(visible=True)
        if button.count():
            log.info("Closing a Studio pop-up: %s", clean(button.first.inner_text()))
            button.first.click()
        else:
            page.keyboard.press("Escape")
        page.wait_for_timeout(1000)


def load(page) -> None:
    """Open the channel in Studio. Stops (for the user to fix) when signed out or without access to the channel."""
    page.goto(config.YOUTUBE_STUDIO_URL, wait_until="domcontentloaded")
    create = page.get_by_role("button", name="Create", exact=True)
    no_access = page.get_by_text(re.compile(r"don.t have permission", re.IGNORECASE))
    for _ in range(60):
        if "accounts.google.com" in page.url:
            raise chrome.NeedsUser(
                "YouTube is signed out in the automation Chrome. Run 'run.py login', sign in, then start again.")
        if no_access.first.is_visible():
            raise chrome.NeedsUser(
                "The Google account signed in to the automation Chrome has no access to the channel "
                f"{config.YOUTUBE_CHANNEL_ID}. Run 'run.py login', switch account in Studio, then start again.")
        if create.first.is_visible():
            break
        page.wait_for_timeout(1000)
    else:
        raise RuntimeError("YouTube Studio did not load")
    if config.YOUTUBE_CHANNEL_ID not in page.url:
        raise chrome.NeedsUser(f"Studio opened {page.url} instead of the channel {config.YOUTUBE_CHANNEL_ID}. "
                               "Nothing was uploaded.")


def open_dialog(page):
    clear_popups(page)
    page.get_by_role("button", name="Create", exact=True).first.click()
    page.get_by_role("menuitem", name="Upload videos").click()
    dialog = page.locator("ytcp-uploads-dialog")
    dialog.locator("#select-files-button").wait_for()
    return dialog


def hand_over(page, dialog, job) -> str:
    """Give Studio the video file and wait for the Details step. Returns the link Studio gave the new video."""
    chrome.attach_file(page, "ytcp-uploads-dialog input[type=file]", job.video)
    title = dialog.locator("#title-textarea")
    for _ in range(120):
        if title.is_visible():
            break
        refusal = REFUSED.search(clean(dialog.inner_text()))
        if refusal:
            raise chrome.NeedsUser(f"Studio will not take the upload ({refusal.group()}). Open Studio to see why.")
        page.wait_for_timeout(1000)
    else:
        raise RuntimeError("Studio did not show the Details step after the file was chosen")
    link = dialog.locator("#video-link")
    for _ in range(60):
        if VIDEO_ID.search(link.inner_text()):
            return link.inner_text().strip()
        page.wait_for_timeout(1000)
    raise RuntimeError("Studio did not show the new video's link")


def visible_problems(dialog) -> str:
    texts = dialog.locator("#message, #error-message").filter(visible=True).all_inner_texts()
    return " | ".join(clean(text) for text in texts if text.strip())


def set_thumbnail(page, dialog, job) -> None:
    dialog.locator("ytcp-thumbnail-uploader input[type=file]").set_input_files(str(job.thumbnail))
    thumbnail = dialog.locator("#custom-still-editor-wrapper #preview-button")     # its label is the file name
    for _ in range(120):
        if (thumbnail.count() and thumbnail.first.is_visible()
                and clean(thumbnail.first.get_attribute("aria-label") or "") == clean(job.thumbnail.name)
                and "uploading" not in thumbnail.first.inner_text().lower()):
            return
        page.wait_for_timeout(1000)
    raise RuntimeError("Studio did not finish uploading the thumbnail")


def show_advanced(dialog) -> None:
    toggle = dialog.locator("#toggle-button")
    if (toggle.first.get_attribute("aria-label") or "").startswith("Show"):
        toggle.first.click()
        dialog.locator("input#text-input[aria-label='Tags']").wait_for()


def set_tags(page, dialog, tags) -> None:
    show_advanced(dialog)
    dialog.locator("input#text-input[aria-label='Tags']").click()
    page.keyboard.type(",".join(tags) + ",")         # a comma turns the typed text into a tag
    for _ in range(10):
        chips = [clean(text) for text in dialog.locator("ytcp-chip").all_inner_texts()]
        missing = [tag for tag in tags if clean(tag) not in chips]
        if not missing:
            return
        page.wait_for_timeout(500)
    raise RuntimeError(f"Studio did not take these tags: {', '.join(missing)}")


def fill_details(page, dialog, job) -> None:
    title = dialog.locator("#title-textarea #textbox")
    description = dialog.locator("#description-textarea #textbox")
    title.fill(job.title)
    description.fill(job.description)
    if clean(title.inner_text()) != clean(job.title) or not same_text(description.inner_text(), job.description):
        raise RuntimeError("Studio's title or description box does not hold the text from the listing file")
    set_thumbnail(page, dialog, job)
    kids = "VIDEO_MADE_FOR_KIDS_MFK" if config.YOUTUBE_MADE_FOR_KIDS else "VIDEO_MADE_FOR_KIDS_NOT_MFK"
    dialog.locator(f"tp-yt-paper-radio-button[name={kids}]").click()
    if job.tags:
        set_tags(page, dialog, job.tags)


def step_is(dialog, index: int) -> bool:
    return dialog.locator(f"#step-badge-{index}").get_attribute("aria-selected") == "true"


def answer_open_questions(dialog) -> None:
    """Studio refused to continue: answer "No" to the AI use / Paid promotion questions that still have no answer."""
    show_advanced(dialog)
    for question in QUESTIONS:
        no = dialog.locator(f"tp-yt-paper-radio-button[name={question}_NO]")
        yes = dialog.locator(f"tp-yt-paper-radio-button[name={question}_YES], "
                             f"tp-yt-paper-radio-button[name={question}_NOTIFY]")
        if no.count() and no.first.get_attribute("aria-checked") != "true" and yes.first.get_attribute("aria-checked") != "true":
            log.info("Studio needs an answer to %s; choosing No", question)
            no.first.click()


def go_next(page, dialog, index: int) -> bool:
    """Click Next and wait until step `index` is shown. False when Studio stays on the step."""
    dialog.locator("#next-button").click()
    for _ in range(30):
        if step_is(dialog, index):
            return True
        page.wait_for_timeout(500)
    return False


def to_visibility(page, dialog) -> None:
    for index in (1, 2, 3):
        if not go_next(page, dialog, index):
            if index == 1:           # the questions are on the Details step
                answer_open_questions(dialog)
                if go_next(page, dialog, index):
                    continue
            raise RuntimeError(f"Studio would not continue to step {index + 1}. {visible_problems(dialog)}")


def upload_progress(dialog) -> str:
    progress = dialog.locator("ytcp-video-upload-progress")
    return clean(progress.first.inner_text()) if progress.count() else ""


def wait_for_upload(page, dialog, job) -> None:
    """Wait until Studio has received the whole file and finished its checks. Long videos take an hour or more.

    Scheduling earlier makes Studio warn that it is "still checking", and it recommends waiting for the checks.
    """
    done = dialog.locator("#done-button")
    started = last_change = last_logged = time.monotonic()
    shown = ""
    while True:
        text = upload_progress(dialog)
        now = time.monotonic()
        if text != shown:
            shown, last_change = text, now
        if now - last_logged > 300:
            log.info("%s: %s", job.label, text or "waiting for Studio")
            last_logged = now
        if CHECKS_DONE.search(text):
            if not NO_ISSUES.search(text):
                raise RuntimeError(f"Studio's checks report a problem: {text}")
            if done.get_attribute("disabled") is None:
                return
        elif text and UPLOAD_FAILED.search(text):
            raise RuntimeError(f"Studio reports a problem with the upload: {text}")
        if now - last_change > config.YOUTUBE_STALL_TIMEOUT:
            raise TimeoutError(f"Nothing has changed for {config.YOUTUBE_STALL_TIMEOUT // 60} minutes ({text})")
        if now - started > config.YOUTUBE_UPLOAD_TIMEOUT:
            raise TimeoutError("The upload did not finish in time")
        page.wait_for_timeout(3000)


def pick_slot(job):
    """The release-plan slot this video would take now, or None when the plan is not used."""
    if config.RELEASE_FILE is None:
        return None
    if not release.in_plan_time_zone():
        raise chrome.NeedsUser("This PC is not in India Standard Time, but the release plan is. "
                               "Change the Windows time zone to IST.")
    if not config.RELEASE_FILE.is_file():
        raise chrome.NeedsUser(f"The release plan {config.RELEASE_FILE} was not found.")
    slot = release.next_slot(config.RELEASE_FILE, job.topic.kind)
    if slot is None:
        raise chrome.NeedsUser(f"{config.RELEASE_FILE.name} has no Pending {job.topic.kind} slot left. "
                               "Add days to the plan.")
    return slot


def read_with(formats, text: str):
    """(format, value) of the first of `formats` that reads `text`, which Studio wrote in the page's own locale."""
    for fmt in formats:
        try:
            return fmt, datetime.strptime(clean(text), fmt)
        except ValueError:
            continue
    raise RuntimeError(f"Studio shows '{clean(text)}' in the schedule, a format this script cannot read")


def write_with(fmt: str, when: datetime) -> str:
    """`when` in the given format, without leading zeros on the day and the 12-hour hour (Studio writes 3 Dec, 6:00 PM)."""
    return clean(when.strftime(fmt.replace("%d", str(when.day)).replace("%I", str(when.hour % 12 or 12))))


def schedule(page, dialog, slot) -> None:
    """Fill Studio's Schedule section with the slot's date and time, written the way Studio itself shows them."""
    trigger = dialog.locator("#datepicker-trigger")
    if not trigger.is_visible():
        dialog.locator("#second-container-expand-button").click()
        trigger.wait_for()
    scheduler = dialog.locator("ytcp-visibility-scheduler")
    zone = scheduler.locator("yt-icon[aria-label*='time zone']")
    if zone.count() and "+0530" not in (zone.first.get_attribute("aria-label") or ""):
        raise chrome.NeedsUser(f"Studio's schedule uses a different time zone: {zone.first.get_attribute('aria-label')}")

    time_box = dialog.locator("ytcp-datetime-picker tp-yt-paper-input input")
    date_format, _ = read_with(DATE_FORMATS, trigger.inner_text())
    time_format, _ = read_with(TIME_FORMATS, time_box.input_value())

    trigger.click()
    date_box = page.locator("ytcp-date-picker input").first
    date_box.fill(write_with(date_format, slot.when))
    date_box.press("Enter")
    date_box.wait_for(state="hidden")           # the pop-up stays open when Studio does not accept the date
    time_box.click()
    time_box.fill(write_with(time_format, slot.when))
    time_box.press("Enter")
    page.wait_for_timeout(1000)
    shown = (read_with(DATE_FORMATS, trigger.inner_text())[1].date(), read_with(TIME_FORMATS, time_box.input_value())[1].time())
    if shown != (slot.when.date(), slot.when.time()):
        raise RuntimeError(f"Could not set the schedule to {slot.label} "
                           f"(Studio shows {clean(trigger.inner_text())} {clean(time_box.input_value())})")


def publish_now(dialog) -> None:
    """Choose the visibility from config.py, used when the release plan is switched off."""
    option = config.YOUTUBE_VISIBILITY.upper()
    dialog.locator(f"tp-yt-paper-radio-button[name={option}]").click()


def finish(page, dialog) -> str:
    """Click the final button (Schedule, Save or Publish). Returns Studio's confirmation text, or "" when it shows none."""
    was_hidden = dialog.get_attribute("hide-dialog") is not None     # Studio sets this on its dialog when it closes
    dialog.locator("#done-button").click()
    share = page.locator("ytcp-video-share-dialog")
    got_it = page.get_by_role("button", name="Got it", exact=True).filter(visible=True)
    closed_at = None
    for _ in range(120):
        if share.locator("#dialog-title").is_visible():
            lines = [clean(line) for line in share.inner_text().splitlines() if line.strip()]
            share.locator("#close-button").click()
            return " - ".join(lines[:2])             # e.g. "Video scheduled - Your video will be set to public on ..."
        if got_it.count():                           # "We're still checking your content": it only needs confirming
            log.info("Studio says it is still checking the content; confirming")
            got_it.first.click()
        elif not was_hidden and dialog.get_attribute("hide-dialog") is not None:
            closed_at = closed_at or time.monotonic()
            if time.monotonic() - closed_at > 10:    # closed, and no confirmation dialog followed (a private save)
                return ""
        page.wait_for_timeout(1000)
    raise RuntimeError(f"Studio did not accept the final click. {visible_problems(dialog)}")


def verify(page, job, video_id: str, scheduled: bool) -> None:
    """Open the new video in Studio and check that it exists with the listing's title (and is scheduled)."""
    page.goto(f"{STUDIO}/video/{video_id}/edit", wait_until="domcontentloaded")
    title = page.locator("#title-textarea #textbox")
    title.wait_for(timeout=60_000)
    if clean(title.inner_text()) != clean(job.title):
        raise RuntimeError(f"The saved video's title is '{title.inner_text()}'")
    if scheduled:
        visibility = page.locator("ytcp-video-metadata-visibility #visibility-text")
        visibility.wait_for()
        if "scheduled" not in visibility.inner_text().lower():
            raise RuntimeError(f"The saved video's visibility is '{clean(visibility.inner_text())}', not scheduled")


def upload(page, job) -> str:
    """Upload one video. Returns what Studio reported. Raises NeedsUser once the upload has begun and then failed."""
    pick_slot(job)                                   # stop early when the plan has run out
    link = ""
    for attempt in range(1, config.YOUTUBE_MAX_ATTEMPTS + 1):
        try:
            load(page)
            dialog = open_dialog(page)
            link = hand_over(page, dialog, job)
            break
        except chrome.NeedsUser:
            raise
        except Exception as error:                   # nothing is uploaded yet, so a fresh start is safe
            if not page.context.browser.is_connected():
                raise
            log.warning("%s: could not start the upload (try %d): %s", job.label, attempt, chrome.brief(error))
    else:
        raise RuntimeError("Studio did not take the file")

    video_id = VIDEO_ID.search(link).group(1)
    topics.write_upload_record(job, status="started", video_url=link,
                               started=datetime.now().isoformat(timespec="seconds"))
    log.info("%s: Studio has the file (%s); filling in the details", job.label, link)
    try:
        fill_details(page, dialog, job)
        to_visibility(page, dialog)
        wait_for_upload(page, dialog, job)
        slot = pick_slot(job)
        if slot:
            schedule(page, dialog, slot)
        else:
            publish_now(dialog)
        report = finish(page, dialog)
        verify(page, job, video_id, scheduled=slot is not None)
        if slot:
            try:
                release.mark_done(config.RELEASE_FILE, slot)
            except (OSError, ValueError) as problem:
                log.error("Mark the slot %s as Done in %s yourself: %s", slot.label, config.RELEASE_FILE.name, problem)
        topics.write_upload_record(job, status="scheduled" if slot else "uploaded", video_url=link,
                                   scheduled_for=slot.label if slot else None,
                                   finished=datetime.now().isoformat(timespec="seconds"))
        log.info("%s: %s (%s)", job.label, report or (f"scheduled for {slot.label}" if slot else "saved"), link)
    except chrome.NeedsUser:
        raise
    except Exception as error:
        raise chrome.NeedsUser(
            f"{job.label}: the upload started but did not finish ({chrome.brief(error)}). Look at {link} in Studio: "
            f"finish or delete that video, then delete {job.target.name} in the topic folder to upload again.") from error
    return report


def run(context, jobs) -> int:
    """Upload every video in `jobs`, one after another. Returns how many were saved."""
    page = open_page(context)
    saved = 0
    log.info("%d video(s) to upload", len(jobs))
    for job in jobs:
        if job.target.exists():
            continue
        try:
            upload(page, job)
        except chrome.NeedsUser:
            raise
        except Exception as error:                   # the upload never started; the next pass tries again
            if not context.browser.is_connected():
                raise
            log.error("Giving up on %s for now: %s", job.label, chrome.brief(error))
            continue
        saved += 1
    return saved
