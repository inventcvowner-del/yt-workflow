# YouTube workflow automation

Python scripts that generate the missing voices (ElevenLabs) and video clips (Adobe Firefly) for every topic folder, make
the thumbnails in ChatGPT, and upload the finished videos to YouTube Studio, scheduled into the release plan.
Full rules for each step: [WORKFLOW.md](WORKFLOW.md). Prompts to give Copilot: [PROMPTS.md](PROMPTS.md).

## Run

Open a terminal and go to this folder:

```
cd /d D:\youtube\workflow\yt-workflow
```

| Command | What it does |
|---|---|
| `run status` | Lists missing voices, clips, thumbnails and uploads. Generates and uploads nothing, so it is always safe. |
| `run clips` | Generates all missing Firefly clips, 5 tabs at once. |
| `run audio` | Generates all missing ElevenLabs voices, one after another. |
| `run thumbnails` | Asks ChatGPT for every missing thumbnail (9:16 for shorts, 16:9 for long videos) and saves it as `thumbnail.png` in the topic folder. |
| `run upload` | Uploads every finished video to YouTube Studio and schedules it into the next free slot of `release.txt` (in this folder). |
| `run all` | Audio, then clips, then thumbnails, then uploads, then exits. |
| `run all --watch` | Same, but never exits. It checks for new work every 5 minutes. |
| `run login` | Opens the automation Chrome so you can sign in again, if a site ever signs you out. |

`run` is `run.cmd` in this folder. It starts `scripts\run.py` with the installed Python, so it works even when the
terminal does not know the `python` command. In PowerShell type `.\run status`. `python run.py status` inside the
`scripts` folder does the same thing.

Options (add to any command):

| Option | What it does |
|---|---|
| `--topic "folder name"` | Only this topic, with or without its number, e.g. `--topic "quantum tunneling"` or `--topic "6. quantum tunneling"`. |
| `--kind short` / `--kind long` | Only short videos or only long videos. |

Stop with Ctrl+C. Run the same command again to continue; files that already exist are skipped.

Topic folders are numbered (`3. graphene`, `4. liquid metal gallium`, ...; short and long videos separately) and the
scripts handle them in number order, so uploads and release slots follow it. A new topic gets the next number.

## Thumbnails

A topic folder (short or long) that has `youtube_title_description.txt` but no thumbnail gets one: the title and
description are sent to the ChatGPT chat set in `scripts\config.py` (`CHATGPT_URL`) together with the channel logo and a
request for **9:16** (short videos) or **16:9** (long videos), and the image is downloaded and saved as `thumbnail.png`
in the topic folder. Delete `thumbnail.png` and run `run thumbnails` to make another one. The wording of the request,
the logo and the ratios are in `scripts\config.py`. Sign in to ChatGPT once with `run login`.

## Uploading a video

A video is uploaded when its topic folder (short or long) holds `Final.mp4`, a thumbnail (`thumbnail.png`) and
`youtube_title_description.txt`, and has no `youtube_upload.json` yet. The video is scheduled into the next `Pending`
slot of its kind in `release.txt` (Short 1-4 for shorts, Long video for long ones) and that slot becomes `Done`.
`release.txt` is the 30-day release plan; it sits in this folder and the scripts edit it (`Pending` to `Done`).
`run status --topic "folder name"` explains why a folder is not uploading. Sign in to YouTube once with `run login`,
using the Google account that owns the channel. Publish straight away instead of scheduling, or change the other upload
settings, in `scripts\config.py`.

A video you publish by hand needs an (empty) `youtube_upload.json` in its folder, so that no thumbnail is made and
nothing is uploaded again for it. The older videos already have one.
