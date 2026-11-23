# YouTube workflow automation

Python scripts that generate the missing voices (ElevenLabs) and video clips (Adobe Firefly) for every topic folder, put
them together in Adobe Premiere and export `final.mp4`, make the thumbnails in ChatGPT, and upload the finished videos to
YouTube Studio, scheduled into the release plan.
Full rules for each step: [WORKFLOW.md](WORKFLOW.md). Prompts to give Copilot: [PROMPTS.md](PROMPTS.md).

## Run

Open a terminal and go to this folder:

```
cd /d D:\youtube\workflow\yt-workflow
```

| Command | What it does |
|---|---|
| `run status` | Lists missing voices, clips, edits, thumbnails and uploads, followed by all the commands and options for reference. Generates and uploads nothing, so it is always safe. |
| `run clips` | Generates all missing Firefly clips, 5 tabs at once. |
| `run audio` | Generates all missing ElevenLabs voices, one after another. |
| `run edit` | Starts Premiere for every topic whose clips and voices are complete, builds `editing.prproj` and exports `final.mp4` (1080 x 1920 for shorts, 4K for long videos). Close Premiere first. |
| `run thumbnails` | Asks ChatGPT for every missing thumbnail (9:16 for shorts, 16:9 for long videos) and saves it as `thumbnail.png` in the topic folder. |
| `run upload` | Uploads every finished video to YouTube Studio and schedules it into the next free slot of `release.txt` (in this folder). |
| `run all` | Audio, then clips, then edits, then thumbnails, then uploads, then exits. |
| `run all --watch` | Same, but never exits. It checks for new work every 5 minutes. |
| `run login` | Opens the automation Chrome so you can sign in again, if a site ever signs you out. |

`run` is `run.cmd` in this folder. It starts `scripts\run.py` with the installed Python, so it works even when the
terminal does not know the `python` command. In PowerShell type `.\run status`. `python run.py status` inside the
`scripts` folder does the same thing.

Options (add to any command):

| Option | What it does |
|---|---|
| `short-N` / `long-N` | Only this video, by its number: `run edit short-11` is `short videos\11. ferrofluid`, `run clips long-3` is `long videos\3. hepatitis virus`. Works with every command. Without it, a command handles all topics. |
| `--topic "folder name"` | Only this topic, with or without its number, e.g. `--topic "quantum tunneling"` or `--topic "6. quantum tunneling"`. |
| `--kind short` / `--kind long` | Only short videos or only long videos. |

Stop with Ctrl+C. Run the same command again to continue; files that already exist are skipped.

Topic folders are numbered (`3. graphene`, `4. liquid metal gallium`, ...; short and long videos separately) and the
scripts handle them in number order, so uploads and release slots follow it. A new topic gets the next number.

## Editing in Premiere

A topic folder (short or long) is edited when every clip in `video_prompts.txt` and every voice exists and the folder has
no final video, no Premiere project and no `youtube_upload.json`. `run edit` starts Premiere once per topic and Premiere
closes itself afterwards:

- The clips (`video_clips\Clip NN.mp4`) go one after another on V1, the voices (`voices\NN.mp3`) one after another on
  the first free audio track.
- The longer side is cut at its end. Clips longer than the voices are trimmed to the voices. Voices longer than the
  clips are cut where the last clip ends, however much that is: the log warns how many seconds of narration were lost,
  so generate more clips first if the ending matters.
- The sequence is 1080 x 1920 for a short video and 3840 x 2160 for a long one. The 720p clips are scaled up until they
  fill the frame (anything that sticks out is cropped).
- The channel logo (`D:\youtube\assets\logo_round.png`) sits small in the bottom right for the whole video. Its size and
  place are `PREMIERE_LOGO_LAYOUT` in `scripts\config.py`; set `PREMIERE_LOGO = None` there for no logo.
- The project is saved as `editing.prproj` in the topic folder and the export as `final.mp4`.

Premiere must be closed before `run edit` starts: a Premiere that is already running cannot be given a script, so the
step stops and says so. A project you made by hand is never touched; delete `editing.prproj` (and `final.mp4`) to have
a topic edited again. A new `final.mp4` is uploaded by the next `run upload` or `run all`, so look at it first if you
want to check it. Frame sizes, the logo and the export preset are in `scripts\config.py`.

## Thumbnails

A topic folder (short or long) that has `youtube_title_description.txt` but no thumbnail gets one: the title and
description are sent to the ChatGPT chat set in `scripts\config.py` (`CHATGPT_URL`) together with the channel logo and a
request for **9:16** (short videos) or **16:9** (long videos), and the image is downloaded and saved as `thumbnail.png`
in the topic folder. Delete `thumbnail.png` and run `run thumbnails` to make another one. The wording of the request,
the logo and the ratios are in `scripts\config.py`. Sign in to ChatGPT once with `run login`.

## Uploading a video

A video is uploaded when its topic folder (short or long) holds `final.mp4`, a thumbnail (`thumbnail.png`) and
`youtube_title_description.txt`, and has no `youtube_upload.json` yet. The video is scheduled into the next `Pending`
slot of its kind in `release.txt` (Short 1-4 for shorts, Long video for long ones) and that slot becomes `Done`.
`release.txt` is the 30-day release plan; it sits in this folder and the scripts edit it (`Pending` to `Done`).
`run status --topic "folder name"` explains why a folder is not uploading. Sign in to YouTube once with `run login`,
using the Google account that owns the channel. Publish straight away instead of scheduling, or change the other upload
settings, in `scripts\config.py`.

A video you publish by hand needs an (empty) `youtube_upload.json` in its folder, so that no thumbnail is made and
nothing is uploaded again for it. The older videos already have one.
