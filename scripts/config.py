"""Settings for the YouTube automation scripts. Edit values here, not in the other files."""
from pathlib import Path

ROOT = Path(r"D:\youtube")
SHORTS_DIR = ROOT / "short videos"
LONGS_DIR = ROOT / "long videos"

WORK_DIR = Path(__file__).resolve().parent.parent   # the yt-workflow folder; the three folders below are in .gitignore
PROFILE_DIR = WORK_DIR / "chrome-profile"   # Chrome profile used only by the automation (sign in once)
DOWNLOAD_DIR = WORK_DIR / "downloads"       # Chrome saves files here; the scripts move them to the topic folder
LOG_DIR = WORK_DIR / "logs"

CHROME_CANDIDATES = [
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    Path.home() / r"AppData\Local\Google\Chrome\Application\chrome.exe",
]
CDP_PORT = 9333
LOCK_PORT = 9334                 # held while run.py is working, so two runs cannot fight over the tabs
UI_PORT = 9335                   # "run ui": the page is http://127.0.0.1:9335, reachable from this PC only

# ---- Step 4: Adobe Firefly video clips ----
FIREFLY_URL = "https://firefly.adobe.com/generate/video"
FIREFLY_TABS = 5
FIREFLY_SETTINGS = {             # kind of video -> picker label -> exact option name, applied in this order
    "long": {                    # (the other pickers reset when Model changes)
        "Model": "Runway Gen-4.5",
        "Resolution": "720p",
        "Aspect ratio": "Widescreen (16:9)",
        "Frames per second": "24 FPS",
        "Duration": "10 seconds",
    },
    "short": {
        "Model": "Ray3.14",
        "Resolution": "720p",
        "Aspect ratio": "Vertical (9:16)",
        "Frames per second": "24 FPS",
        "Duration": "10 seconds",
    },
}
FIREFLY_SETTLE = 5               # seconds after loading, while Firefly restores the tab's previous state
FIREFLY_POLL = 10                # seconds between "is it done?" checks
FIREFLY_TIMEOUT = 15 * 60        # give up on one generation after this long, then retry
FIREFLY_MAX_ATTEMPTS = 5         # per clip, before it is skipped until the next pass
FIREFLY_RETRY_PAUSE = 30         # seconds a tab rests after a failure

# ---- Edit: Adobe Premiere Pro (after the clips are generated) ----
ADOBE_DIR = Path(r"C:\Program Files\Adobe")     # the newest "Adobe Premiere Pro <year>" folder in here is used
PREMIERE_PROJECT = "editing.prproj"             # the project saved in the topic folder
PREMIERE_SEQUENCE = "Final"
PREMIERE_FRAME = {                              # kind of video -> frame size of the sequence and of the export.
    "short": (1080, 1920),                      # The 720p clips are scaled up until they fill it; what sticks out
    "long": (3840, 2160),                       # is cropped.
}
PREMIERE_LOGO = ROOT / "assets" / "logo_round.png"   # shown over the whole video, bottom right; None for no logo. It is
                                                # logo.jpg cut round on a transparent background, and must be a PNG.
PREMIERE_LOGO_LAYOUT = {                        # kind of video -> (logo width, gap to the right edge, gap to the
    "short": (0.15, 0.15, 0.04),                # bottom edge), as parts of the frame's width, width and height. The
    "long": (0.05, 0.01, 0.015),                # gap on the right of a short keeps the logo clear of the Shorts buttons.
}
# Export preset, inside the Premiere folder: "Match Source - Adaptive High Bitrate" (H.264). It exports at the
# sequence's frame size. An absolute path to an .epr of your own works too.
PREMIERE_PRESET = r"MediaIO\systempresets\4E49434B_48323634\01 - Match Source - High bitrate.epr"
FINAL_FILE = "final.mp4"                        # the export, in the topic folder (the upload step looks for it)
PREMIERE_STALL_TIMEOUT = 10 * 60 # Premiere is stopped when it has not finished and the export has not grown for this long
PREMIERE_QUIT_WAIT = 60          # seconds Premiere gets to close itself after a topic

# ---- Step 2: ElevenLabs audio ----
ELEVEN_URL = "https://elevenlabs.io/app/speech-synthesis/text-to-speech"
ELEVEN_WORKSPACE = "invent's Workspace"   # safety check: nothing is generated in any other workspace
ELEVEN_VOICE = "my voice 1"
ELEVEN_MODEL = "Eleven v4"
ELEVEN_TIMEOUT = 10 * 60
ELEVEN_MAX_ATTEMPTS = 3          # tries to set up the page for one section (Generate is clicked once only)

# ---- Step 2 alternative: your own fine-tuned voice on a Vast.ai GPU ("run audio vast") ----
# Start the instance on https://cloud.vast.ai/instances/ first. Its SSH address is on the instance card (>_ button,
# "Direct ssh connect": ssh -p PORT root@HOST); it can change when the instance is stopped and started again.
# The SSH key in %USERPROFILE%\.ssh must be added to the Vast account. No passwords or tokens are kept here.
VAST_HOST = "45.173.179.240"
VAST_PORT = 4740
VAST_DIR = "/workspace/tts"                  # project folder on the instance
VAST_HF_HOME = "/workspace/.hf_home"         # model downloads on the instance
VAST_RELEASE = "releases/maya2-suresh-s100"  # the voice model, inside VAST_DIR
VAST_VOICE = "Suresh"
VAST_SEED = 7                                # same seed for every section, so the voice stays the same
VAST_CHECK = True                            # transcribe every file with a Telugu Whisper and log how far it is off
VAST_CHECK_WARN = 0.15                       # log a "listen to it" warning above this difference (numbers count too)
TTS_DIR = ROOT / "TTS-Fine_tuning"           # where a new instance is set up from: its scripts and the voice adapter
VAST_ADAPTER_RUN = "runs/suresh_s100"        # inside TTS_DIR; the release is rebuilt from it on a new instance
VAST_ADAPTER = "adapter_last.pt"
VAST_POLL = 10                               # seconds between "is the next voice ready?" checks
VAST_SETUP_TIMEOUT = 60 * 60                 # setting up a new instance (installing, then rebuilding the voice)
VAST_STALL_TIMEOUT = 20 * 60                 # give up when no voice has arrived for this long (the box keeps going)

# ---- Step 5: ChatGPT thumbnails ----
CHATGPT_URL = "https://chatgpt.com/c/6b045698-8154-83ee-800d-0975811b351d"   # the chat every thumbnail is asked for in
THUMBNAIL_FILE = "thumbnail.png"            # name of the thumbnail in the topic folder
THUMBNAIL_RATIO = {                         # kind of video -> aspect ratio asked for, and how it is described
    "short": ("9:16", "vertical"),
    "long": ("16:9", "horizontal"),
}
THUMBNAIL_RATIO_TOLERANCE = 0.05            # a thumbnail whose width/height differs more than this (5%) from the ratio is refused
THUMBNAIL_ATTACHMENTS = [ROOT / "assets" / "logo.jpg"]   # images sent with every request; [] sends none
THUMBNAIL_LOGO_NOTE = "The attached image is my channel logo: put it in the top-left corner."   # used when there are attachments
THUMBNAIL_PROMPT = (                        # {logo} is THUMBNAIL_LOGO_NOTE and a line break, or nothing
    "Create a YouTube thumbnail for the video below.\n"
    "Aspect ratio: {ratio} ({shape}).\n"
    "{logo}"
    "Generate the image now; do not ask any questions.\n\n"
    "Title: {title}\n\n"
    "Description:\n{description}"
)
CHATGPT_TIMEOUT = 10 * 60        # an image takes about a minute; give up on one request after this long
CHATGPT_MAX_ATTEMPTS = 3         # tries to set up and fill the request (nothing is generated before Send is clicked)

# ---- Step 6: YouTube Studio upload ----
YOUTUBE_CHANNEL_ID = "UCqLtH-2qyKDNW3NPI4gM_pg"   # safety check: nothing is uploaded unless Studio opens this channel
YOUTUBE_STUDIO_URL = f"https://studio.youtube.com/channel/{YOUTUBE_CHANNEL_ID}"
RELEASE_FILE = WORK_DIR / "release.txt"   # each video is scheduled into the next Pending slot of this plan (IST)
SCHEDULE_LEAD = 30 * 60          # a slot must still be this many seconds away when the video is scheduled
YOUTUBE_VISIBILITY = "Public"    # only used when RELEASE_FILE is None: Private, Unlisted or Public straight away
YOUTUBE_MADE_FOR_KIDS = False
# Studio's "AI use" and "Paid promotion" questions are left alone. Only if Studio refuses to continue without an
# answer is "No" chosen.
UPLOAD_SETTLE = 120              # a final.mp4 changed less than this many seconds ago may still be exporting
YOUTUBE_UPLOAD_TIMEOUT = 8 * 60 * 60   # one video from start to scheduled (a 3 GB long video takes an hour or more)
YOUTUBE_STALL_TIMEOUT = 20 * 60        # give up when the upload percentage has not moved for this long
YOUTUBE_MAX_ATTEMPTS = 3         # tries to open the upload dialog and hand over the file (nothing is uploaded before that)

DOWNLOAD_TIMEOUT = 180           # seconds to wait for a clicked download to land on disk
WATCH_INTERVAL = 5 * 60          # with --watch: seconds between scans for new work
