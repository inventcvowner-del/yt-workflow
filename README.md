# YouTube workflow automation

Python scripts that generate the missing voices (ElevenLabs) and video clips (Adobe Firefly) for every topic folder.
Full rules for each step: [WORKFLOW.md](WORKFLOW.md). Prompts to give Copilot: [PROMPTS.md](PROMPTS.md).

## Run

Open a terminal and go to this folder:

```
cd /d D:\youtube\workflow\yt-workflow
```

| Command | What it does |
|---|---|
| `run status` | Lists missing voices and clips. Generates nothing, so it is always safe. |
| `run clips` | Generates all missing Firefly clips, 5 tabs at once. |
| `run audio` | Generates all missing ElevenLabs voices, one after another. |
| `run all` | Audio first, then clips, then exits. |
| `run all --watch` | Same, but never exits. It checks for new work every 5 minutes. |
| `run login` | Opens the automation Chrome so you can sign in again, if a site ever signs you out. |

`run` is `run.cmd` in this folder. It starts `scripts\run.py` with the installed Python, so it works even when the
terminal does not know the `python` command. In PowerShell type `.\run status`. `python run.py status` inside the
`scripts` folder does the same thing.

Options (add to any command):

| Option | What it does |
|---|---|
| `--topic "folder name"` | Only this topic, e.g. `--topic "quantum tunneling"`. |
| `--kind short` / `--kind long` | Only short videos or only long videos. |

Stop with Ctrl+C. Run the same command again to continue; files that already exist are skipped.
