# Long Video Workflow (Telugu science channel)

## How Copilot controls Chrome (ElevenLabs / Firefly steps)
Copilot does **not** use Playwright/DevTools or any script injected into the page. It uses a **Computer Use** tool that
drives the real, already-open Chrome window like a human would:
- Reads the window's OS **accessibility (AX) tree** (the same structure screen readers use) to find buttons/fields by
  label/role, and takes real **screenshots** to check progress (e.g. a generation spinner finishing).
- Sends real **clicks** (by AX element index or screen coordinates) and **keystrokes** (e.g. `Ctrl+V` to paste) to that
  window, same as a person clicking/typing.
- This is why it reuses your already-signed-in sessions (ElevenLabs "invent" account, Adobe "suresh g") with no extra
  login step, but also why element positions/indices can shift between screenshots and have to be re-found each time
  rather than cached.

Three steps. Copy-paste prompts for each: [PROMPTS.md](PROMPTS.md)

| Step | User says | Copilot does | Output |
|---|---|---|---|
| 1 | "generate script for <topic>" | Creates the topic folder and writes the Telugu script | `script.txt` |
| 2 | "generate audio" | Splits the script, generates each section in ElevenLabs, downloads and names the files | `sections\NN.txt`, `voices\NN.mp3` |
| 3 | Adds "N scirtps brake here - time M:SS" markers, then says "generate video prompts" | Writes N English video prompts for the text above each marker | `video_prompts.txt` |

Topic folder: `D:\youtube\long videos\<topic>\`

---

## Step 1. Generate script
1. Create the folder: `powershell -NoProfile -ExecutionPolicy Bypass -File D:\youtube\workflow\yt-workflow\scripts\new_video.ps1 "<topic>"`
   (creates `script.txt`, `voices\`, `video_clips\`).
2. Write `script.txt` in Telugu, science-explainer style:
   - Hook (questions to grab attention), then the explanation sections, then the outro (like / share / subscribe + health or safety note if needed).
   - Separate sections with a line of `--------------------`. Each section is one audio file, so keep sections roughly 20-60 s of narration.
   - Short sentences, one per line, blank line between lines. Use Telugu script for English terms (e.g. లాపరోస్కోపిక్).
3. Stop and let the user review the script before audio.

## Step 2. Generate audio (ElevenLabs) and name the files
1. Split the script: `powershell -NoProfile -ExecutionPolicy Bypass -File D:\youtube\workflow\yt-workflow\scripts\split_script.ps1 "<topic>"`
   -> `sections\01.txt, 02.txt ...` (marker lines are removed automatically, so they are never narrated).
2. **Account safety check (mandatory):** use only the Chrome window signed in to **invent**; confirm the workspace is
   **invent's Workspace**. If it is anything else (e.g. "suresh"), **STOP**: generate nothing and tell the user.
   Re-check after any sign-in, workspace switch or page reload.
3. Text to Speech page, voice **my voice 1**, model **Eleven v4**.
4. Loop for each section NN:
   1. Copy `sections\NN.txt` to the clipboard.
   2. In the editor: click, **Ctrl+A then BackSpace** (clear), then Ctrl+V.
   3. Verify the editor contains only section NN (no text from the previous section) before clicking Generate.
      If old text is left, clear again; never generate merged text (wastes credits).
   4. Generate speech, wait until done, download **Generation 1**.
   5. Move the newest `Downloads\ElevenLabs_*.mp3` to `voices\NN.mp3` (section N = voice N).
5. After the last section, list `voices\` and report lengths/credits to the user.

## Step 3. Video prompts (after the user adds timers + clip counts)
The user marks `script.txt` under each part with a line like:

    6 scirtps brake here  - time 4:40

- The number = how many video clips to make for the text **above that marker** (since the previous marker).
- The time after `-` is the user's timestamp note (where that part ends in the audio); it is not narrated.
- Spelling variations are fine (`scripts break here` also works).

Rules:
1. Only make prompts up to the **last marker** in the file. Text after it waits until the user adds the next marker.
2. Split the block's narration into exactly N clips at sentence boundaries (~10 s each; the video generator max is 10 s).
3. Write them in English into `video_prompts.txt` (topic folder root): one block per marker, one entry per clip with
   clip number, the Telugu narration it covers, and the English prompt.
4. Prompt style: 16:9, 4K, cinematic/realistic, describe camera movement, **no on-screen text, no gore/blood**.
5. Number clips sequentially across the whole video (block 1 -> 01-06, block 2 -> 07-12, ...); the user saves them as `video_clips\NN.mp4`.
6. Keep the line `Done up to: script.txt line X. Next clip number: NN` at the top of `video_prompts.txt` updated and continue from there next time.

---

## Step 4. Generate video clips in Adobe Firefly (only when the user says so)
**Never click Generate unless the user explicitly asks.** Setting up the page and pasting a prompt is fine; generating costs credits.

Link: https://firefly.adobe.com/generate/video (Chrome, Adobe account "suresh g" is already signed in)

Always use these settings (set them before pasting a prompt):

| Setting | Value |
|---|---|
| Model | **Runway Gen-4.5** |
| Resolution | **720p** |
| Aspect ratio | **Widescreen (16:9)** |
| Frames per second | **24 FPS** |
| Duration | **10 seconds** |
| References / Frames | none (leave empty) |
| Seed | empty |

Per clip: copy the English prompt of clip NN from `video_prompts.txt`, paste it in the Prompt box, check the settings above, then wait for the user's go-ahead before clicking Generate. Download and save as `video_clips\Clip NN.mp4`.

### One-by-one loop (same as voices), once the user says "generate"
Files are named like the prompts: `video_clips\Clip 01.mp4`, `Clip 02.mp4`, ... (not `NN.mp4`).
Runway Gen-4.5 in Firefly is an unlimited subscription, so credits are not a concern. Generate ALL clips in the file without waiting for further input.
1. Clear the Prompt box (Ctrl+A, BackSpace), paste prompt NN, confirm the settings, click Generate.
2. A clip takes about 2.5 minutes: wait 1 minute first, then check every 10 seconds until the Download button is enabled (or an error appears).
3. If completed: download it, rename to `Clip NN.mp4` in `video_clips\` (verify the file exists), then delete the generated video in Adobe Firefly to save browser memory.
4. If failed: clear/delete the failed one, paste the same prompt again and retry until it succeeds.
5. Move to prompt NN+1 and continue until all clips are completed.

### Parallel mode (faster): 4 Firefly tabs at once
Open 4 tabs of https://firefly.adobe.com/generate/video (same settings in each; after "Clear all" re-set Duration to 10 seconds). Submit 4 consecutive clips, one per tab, then poll every tab; as each finishes, download, rename to `Clip NN.mp4`, delete it in Firefly, and start the next unassigned clip in that tab. If Firefly limits concurrent runs or a tab fails, reduce the tab count and retry.

---

# Short Video Workflow (Telugu science channel)

Topic folder: `D:\youtube\short videos\<topic>\`. Pick topics from `D:\youtube\short videos\topics.txt` (move a topic from "Pending" to "Done" when its clips are finished).

| Step | User says | Copilot does | Output |
|---|---|---|---|
| 1 | "start short video <topic>" | Writes titles, a ~30-45 s Telugu script (hook, explanation, follow outro), description, tags. No section labels such as [హుక్] / [వివరణ] | `youtube_short_script.txt` |
| 2 | "generate audio" | Writes spoken text only, generates ONE ElevenLabs file (same account safety check, voice and model as Step 2 above) | `narration.txt`, `voices\01.mp3` |
| 3 | User adds a marker line, then says "generate video prompts" | Splits narration into N ~10 s clips as the marker says, English prompts, no on-screen text, no gore | `video_prompts.txt` |
| 4 | "step 4" | Generates clips in Firefly with the short-video settings below, using 4 tabs in parallel | `video_clips\Clip NN.mp4` |

Step 3 for shorts: the user adds one marker line at the end of the script text in `youtube_short_script.txt` (before DESCRIPTION), e.g.

    4 scirtps brake here  - time 40s

- The number = how many clips to make (N); the time = the audio length note (not narrated). Spelling variations are fine.
- Split the narration into exactly N clips at sentence boundaries, in order. Numbering starts at Clip 01.
- Do not generate prompts until the marker exists. Same prompt style and `Done up to: ... Next clip number: NN` header as the long-video Step 3,
  but start each prompt with "Vertical 9:16, 4K" (shorts are generated vertically).

Step 4 for shorts:
1. Shorts use their own Firefly settings: Model **Ray3.14** (not "Ray3.14 HDR"), Resolution **720p**, Aspect ratio
   **Vertical (9:16)**, **24 FPS**, Duration **10 seconds**. Ray3.14 has no Seed box. Older prompts that start with
   "16:9" are pasted as "Vertical 9:16".
2. Create `video_clips\` first. Open 4 tabs (one clip per tab; close any stray blank tab) and set the settings above in each. Paste the prompt and Generate.
3. Wait about 2.5 minutes, then in each finished tab: download, move/rename the newest `Downloads\Firefly*.mp4` to `video_clips\Clip NN.mp4`, verify the file exists, and **only then delete the generated video in Firefly**.
4. A failed clip is retried with the same prompt. Start the next unassigned clip in the freed tab. Finish when every clip exists.
5. Compare the audio length with the total clip length and tell the user if more clips are needed.

---

# Python automation (Steps 2 and 4 without Copilot)

Scripts: `D:\youtube\workflow\yt-workflow\scripts\`. Only `run.py` is run; all settings (tabs, model, voice,
workspace, timeouts) are in `config.py`. Steps 1 and 3 (writing the script and the video prompts) still need Copilot.

The scripts control the real Google Chrome through Playwright. Chrome does not allow this on the everyday profile,
so they use their own profile in `D:\youtube\workflow\yt-workflow\chrome-profile` ("automation Chrome"). Sign in
there once. That folder holds the signed-in sessions, so it is in `.gitignore` (with `downloads\` and `logs\`) and
must never be committed.

Commands and options: [README.md](README.md). `python run.py audio` is Step 2 and `python run.py clips` is Step 4.

How it decides what to do:
- A voice or clip is "missing" when its file does not exist (`voices\NN.mp3`, `video_clips\Clip NN.mp4`). Finished
  files are never generated again, so a stopped or crashed run continues where it left off.
- Clips come from `video_prompts.txt`. Short-video audio comes from `narration.txt`, long-video audio from
  `sections\NN.txt` (split from `script.txt` the first time). Marker lines ("N scirtps brake here") are never narrated.
- To re-split a long script that changed before its audio was finished, delete the `sections\` folder first.

Safety rules built in:
- ElevenLabs: nothing is generated unless the workspace is **invent's Workspace**, the voice is **my voice 1**, the
  model is **Eleven v4**, and the editor holds exactly the section's text. Generate is clicked once per section; if
  the audio cannot be saved afterwards, audio stops (no automatic retry, so credits are not spent twice).
- Firefly: each clip starts from a clean page with the settings for its kind of video (long: the Step 4 table;
  short: Ray3.14, Vertical 9:16; both are in `config.py`). A failed clip is retried up to 5 times.
  The downloaded file name is checked against the prompt before it is saved, then the video is deleted in Firefly.
- Signed out of a site: that step stops with a message; run `python run.py login`, sign in, start again.

Log: `D:\youtube\workflow\yt-workflow\logs\automation.log`. Windows is kept awake while `run.py` is running.
Setup on a new PC: install Python 3.12, then `python -m pip install -r requirements.txt` (no `playwright install`).

---

## Shared assets (`D:\youtube\assets`)
- `logo.jpg`, `subscribe_overlay.png`, `subscribe_ad.mp4`

## Naming rules
- Lowercase, underscores for files; zero-padded numbers (01, 02, ...).
- Folder names are the topic in plain English.

