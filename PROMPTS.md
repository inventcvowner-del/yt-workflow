# Reference prompts (copy-paste to Copilot)

Three steps. Replace `<topic>` with the topic name (folder in `D:\youtube\long videos\`, with or without its number).
Full rules: [WORKFLOW.md](WORKFLOW.md)

---

## Step 1. Generate script
```
Generate script for "<topic>". Follow D:\youtube\workflow\yt-workflow\WORKFLOW.md step 1.
```

## Step 2. Generate audio
```
Generate audio for "<topic>". Follow D:\youtube\workflow\yt-workflow\WORKFLOW.md step 2
(invent's Workspace only, my voice 1, save as voices\01.mp3, 02.mp3 ...).
```
Only the first section to check the voice first:
```
Generate audio for "<topic>", only section 01 first and show me.
```
Continue after a stop:
```
Continue the audio for "<topic>" from section NN to the end.
```

## Step 3. Generate video prompts
First add markers in `script.txt` under each part, e.g. `6 scirtps brake here  - time 4:40`
(number = clips for the text above, time = where that part ends). Then:
```
Generate video prompts for "<topic>". Follow D:\youtube\workflow\yt-workflow\WORKFLOW.md step 3
(only up to my last marker, continue from the next clip number).
```

## Step 4. Video clips in Firefly (set up only, no generate)
```
Open https://firefly.adobe.com/generate/video, set Runway Gen-4.5, 720p, 16:9, 24 FPS, 10 seconds (WORKFLOW.md step 4) and paste the prompt of clip NN for "<topic>". Do NOT click Generate until I say.
```

Generate clips one by one (Step 4 loop): generate prompt NN, check every 10s, download as video_clips\NN.mp4, delete it in Firefly, then go to the next.

Generate ALL clips (unlimited plan): check every 10s, download as 'Clip NN.mp4', delete in Firefly, retry failed ones, continue to the end.

## Edit in Premiere (after Step 4)
Not a Copilot step: when a topic has all its clips and voices, close Premiere and run `run edit` (see
[README.md](README.md)). It builds `editing.prproj` and exports `final.mp4`.

## Step 5. Thumbnail in ChatGPT
Not a Copilot step: once a topic folder has `youtube_title_description.txt`, run `run thumbnails` (see
[README.md](README.md)). It asks ChatGPT for a 9:16 (short) or 16:9 (long) thumbnail and saves `thumbnail.png`.

## Step 6. Upload to YouTube
Not a Copilot step: put `final.mp4`, `thumbnail.png` and `youtube_title_description.txt` in the topic folder and run
`run upload` (see [README.md](README.md)). To have Copilot write the title and description file:
```
Write youtube_title_description.txt for "<topic>" in the layout of WORKFLOW.md step 6 (TITLE, DESCRIPTION, TAGS).
```
