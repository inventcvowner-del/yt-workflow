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

# ---- Step 2: ElevenLabs audio ----
ELEVEN_URL = "https://elevenlabs.io/app/speech-synthesis/text-to-speech"
ELEVEN_WORKSPACE = "invent's Workspace"   # safety check: nothing is generated in any other workspace
ELEVEN_VOICE = "my voice 1"
ELEVEN_MODEL = "Eleven v4"
ELEVEN_TIMEOUT = 10 * 60
ELEVEN_MAX_ATTEMPTS = 3          # tries to set up the page for one section (Generate is clicked once only)

DOWNLOAD_TIMEOUT = 180           # seconds to wait for a clicked download to land on disk
WATCH_INTERVAL = 5 * 60          # with --watch: seconds between scans for new work
