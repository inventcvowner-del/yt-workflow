"""Audio step on a Vast.ai GPU with your fine-tuned voice ("run audio vast"), instead of ElevenLabs.

The instance must be running (start it on cloud.vast.ai; its SSH address is VAST_HOST/VAST_PORT in config.py). An
instance that does not have the voice yet is set up from TTS_DIR first (about 15 minutes, once). The narration texts
go over as a UTF-8 file, the GPU box makes every voice in one background batch (finetune/batch_tts.py) and each mp3 is
downloaded as soon as it is ready, so a dropped connection or Ctrl+C loses nothing: run the command again and it
carries on. Finished files on the box are named by a hash of their text, so editing a section makes it new.
"""
import hashlib
import json
import logging
import subprocess
import tempfile
import time
from pathlib import Path

import chrome
import config
import topics

log = logging.getLogger("vast")
ENV = (f"cd {config.VAST_DIR} && source .venv/bin/activate && source env.sh && "
       f"export HF_HOME={config.VAST_HF_HOME} PYTHONIOENCODING=utf-8")
JOBS_DIR = f"{config.VAST_DIR}/jobs"
OUT_DIR = f"{JOBS_DIR}/out"


class Unreachable(chrome.NeedsUser):
    pass


def ssh_args() -> list[str]:
    return ["-o", "BatchMode=yes", "-o", "ConnectTimeout=20", "-o", "ServerAliveInterval=15",
            "-o", "ServerAliveCountMax=4", "-o", "StrictHostKeyChecking=accept-new"]


def ssh(command: str, timeout: float = 120, check: bool = True) -> str:
    """Run bash commands on the box and return what they printed (the Vast welcome banner goes to stderr).

    The commands go in on stdin, so nothing in them is quoted twice."""
    done = subprocess.run(["ssh", *ssh_args(), "-p", str(config.VAST_PORT), f"root@{config.VAST_HOST}", "bash -s"],
                          input=command.encode("utf-8"), capture_output=True, timeout=timeout)
    output = done.stdout.decode("utf-8", "replace")
    if check and done.returncode != 0:
        error = done.stderr.decode("utf-8", "replace").strip().splitlines()
        raise RuntimeError(f"ssh command failed ({done.returncode}): {command[:80]}... {error[-1:] or ''}")
    return output


def copy(source: str, target: str, timeout: float = 30 * 60) -> None:
    """scp one file. Remote paths start with ':'."""
    def side(path):
        return f"root@{config.VAST_HOST}{path}" if path.startswith(":") else path
    done = subprocess.run(["scp", *ssh_args(), "-P", str(config.VAST_PORT), side(source), side(target)],
                          capture_output=True, timeout=timeout)
    if done.returncode != 0:
        raise RuntimeError(f"scp {source} -> {target} failed: "
                           f"{done.stderr.decode('utf-8', 'replace').strip().splitlines()[-1:]}")


def retry(action, what: str, attempts: int = 4):
    for attempt in range(1, attempts + 1):
        try:
            return action()
        except (RuntimeError, subprocess.TimeoutExpired) as error:
            if attempt == attempts:
                raise
            log.warning("%s failed (try %d), retrying: %s", what, attempt, error)
            time.sleep(5 * attempt)


def connect() -> None:
    try:
        retry(lambda: ssh("true", timeout=60), "Connecting to Vast", attempts=2)
    except Exception as error:
        raise Unreachable(
            f"Cannot reach the Vast instance at root@{config.VAST_HOST} port {config.VAST_PORT} ({error}). "
            "Start it on https://cloud.vast.ai/instances/ and, if its SSH address changed (>_ button, "
            "'Direct ssh connect'), put the new host and port in VAST_HOST / VAST_PORT in scripts\\config.py.") from None


def background(script: str, path: str, log_file: str, done: str = "") -> None:
    """Start a bash script on the box that keeps running when the connection drops. `done` runs after it."""
    ssh(f"mkdir -p {JOBS_DIR}\ncat > {path} <<'VAST_EOF'\nset -e\n{script}\nVAST_EOF\n"
        f"nohup bash -c 'bash {path} > {log_file} 2>&1 {done}' > /dev/null 2>&1 < /dev/null &\n")


def wait_remote(script: str, name: str, timeout: float) -> None:
    """Run a bash script on the box in the background and wait until it has finished."""
    marker = f"{JOBS_DIR}/{name}"
    ssh(f"rm -f {marker}.ok {marker}.failed")
    background(script, f"{marker}.sh", f"{marker}.log", f"&& touch {marker}.ok || touch {marker}.failed")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(config.VAST_POLL * 3)
        state = retry(lambda: ssh(f"ls {marker}.ok {marker}.failed 2>/dev/null; true"), f"Checking {name}")
        if ".ok" in state:
            return
        if ".failed" in state:
            tail = ssh(f"tail -5 {marker}.log", check=False)
            raise chrome.NeedsUser(f"{name} failed on the Vast box (log {marker}.log):\n{tail}")
    raise chrome.NeedsUser(f"{name} did not finish in {timeout // 60:.0f} minutes; see {marker}.log on the box")


def ensure_voice() -> None:
    """Set up a fresh instance: the engine, then the voice rebuilt from the adapter (no Hugging Face token needed)."""
    release = f"{config.VAST_DIR}/{config.VAST_RELEASE}"
    ready = ssh(f"test -x {config.VAST_DIR}/.venv/bin/python && test -f {release}/voices/voices.json "
                f"&& ls {release}/*.safetensors > /dev/null && echo READY; true")
    if "READY" in ready:
        return
    tts = config.TTS_DIR
    run_dir = f"runs/{Path(config.VAST_ADAPTER_RUN).name}"
    log.info("This Vast instance does not have the voice yet: setting it up (about 15 minutes, only once)")
    ssh(f"mkdir -p {config.VAST_DIR}/finetune {config.VAST_DIR}/{run_dir} {config.VAST_DIR}/data")
    uploads = [(tts / "setup_vast.sh", "setup_vast.sh"), (tts / "data" / "dataset.pt", "data/dataset.pt"),
               (tts / config.VAST_ADAPTER_RUN / config.VAST_ADAPTER, f"{run_dir}/{config.VAST_ADAPTER}"),
               (tts / config.VAST_ADAPTER_RUN / "train_config.json", f"{run_dir}/train_config.json")]
    uploads += [(f, f"finetune/{f.name}") for f in sorted((tts / "finetune").glob("*.py"))]
    for local, remote in uploads:
        log.info("Uploading %s", local.name)
        retry(lambda: copy(str(local), f":{config.VAST_DIR}/{remote}"), f"Uploading {local.name}")
    ssh(f"sed -i 's/\\r$//' {config.VAST_DIR}/setup_vast.sh")    # in case it was saved with Windows line ends
    wait_remote(f"cd {config.VAST_DIR} && export HF_HOME={config.VAST_HF_HOME} && bash setup_vast.sh",
                "setup", config.VAST_SETUP_TIMEOUT)
    log.info("Engine installed; rebuilding the voice from %s", config.VAST_ADAPTER)
    wait_remote(f"{ENV} && pip install -q rapidfuzz && python finetune/export_release.py --run {run_dir} "
                f"--name {config.VAST_VOICE} --adapter {config.VAST_ADAPTER} --data data --out {config.VAST_RELEASE}",
                "export", config.VAST_SETUP_TIMEOUT)
    log.info("The Vast instance is ready")


def remote_name(job) -> str:
    """Unique per topic, section and text: an edited section is generated again."""
    digest = hashlib.sha1(f"{config.VAST_RELEASE}|{config.VAST_VOICE}|{config.VAST_SEED}|{job.text}"
                          .encode("utf-8")).hexdigest()[:10]
    topic = hashlib.sha1(job.topic.label.encode("utf-8")).hexdigest()[:8]
    return f"{job.topic.kind}-{topic}-{job.number:02d}-{digest}"


def start_batch(jobs) -> str:
    """Upload the texts and start the batch in the background. Returns its log file on the box."""
    batch = [{"name": remote_name(job), "text": job.text} for job in jobs]
    stamp = time.strftime("%Y%m%d-%H%M%S")
    with tempfile.TemporaryDirectory() as folder:
        local = Path(folder) / "jobs.json"
        local.write_text(json.dumps(batch, ensure_ascii=False, indent=1), encoding="utf-8")
        ssh(f"mkdir -p {OUT_DIR}")
        retry(lambda: copy(str(local), f":{JOBS_DIR}/jobs-{stamp}.json"), "Uploading the texts")
    retry(lambda: copy(str(config.TTS_DIR / "finetune" / "batch_tts.py"), f":{config.VAST_DIR}/finetune/batch_tts.py"),
          "Uploading batch_tts.py")
    log_file = f"{JOBS_DIR}/batch-{stamp}.log"
    check = " --check" if config.VAST_CHECK else ""
    # flock: a batch still running from an earlier, interrupted run finishes first; this one then skips its files
    command = (f"{ENV} && flock {JOBS_DIR}/gpu.lock python finetune/batch_tts.py --jobs {JOBS_DIR}/jobs-{stamp}.json "
               f"--out {OUT_DIR} --release {config.VAST_RELEASE} --voice {config.VAST_VOICE} "
               f"--seed {config.VAST_SEED}{check}")
    background(command, f"{JOBS_DIR}/batch-{stamp}.sh", log_file)
    return log_file


def download(job, name: str) -> None:
    part = job.target.with_name(job.target.name + ".part")
    job.target.parent.mkdir(parents=True, exist_ok=True)

    def fetch():
        copy(f":{OUT_DIR}/{name}.mp3", str(part), timeout=10 * 60)
        if part.stat().st_size < 2_000:
            raise RuntimeError(f"{part.name} is too small to be real")
    retry(fetch, f"Downloading {job.label}")
    part.replace(job.target)


def results() -> dict[str, tuple[float, float]]:
    text = ssh(f"cat {OUT_DIR}/results.tsv 2>/dev/null; true")
    found = {}
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            found[parts[0]] = (float(parts[1]), float(parts[2]))
    return found


def batch_running() -> bool:
    return "RUNNING" in ssh("pgrep -f 'finetune/batch_tts.py' > /dev/null && echo RUNNING; true")


def run(context, jobs) -> int:
    """Generate every voice in `jobs` on the Vast box. `context` (Chrome) is not used. Returns how many were saved."""
    jobs = [job for job in jobs if not job.target.exists()]
    if not jobs:
        return 0
    connect()
    ensure_voice()
    for topic in {job.topic for job in jobs}:
        topics.save_sections(topic)
    names = {remote_name(job): job for job in jobs}
    log.info("%d voice files to generate on Vast (%s, voice %s)", len(jobs), config.VAST_RELEASE, config.VAST_VOICE)
    log_file = start_batch(jobs)
    saved, last_progress = 0, time.monotonic()
    while names:
        time.sleep(config.VAST_POLL)
        try:
            ready = results()
            for name in [n for n in names if n in ready]:
                job = names.pop(name)
                download(job, name)
                seconds, cer = ready[name]
                saved += 1
                last_progress = time.monotonic()
                note = ""
                if cer >= config.VAST_CHECK_WARN:
                    note = f"  CHECK: Whisper heard {cer:.0%} different text (numbers count too), listen to it"
                elif cer >= 0:
                    note = f", text check {cer:.0%}"
                log.info("Saved %s (%.1f s%s) [%d left]", job.target, seconds, note, len(names))
            if names and not batch_running() and not (set(names) & set(results())):
                tail = ssh(f"tail -8 {log_file}", check=False)
                raise chrome.NeedsUser(f"The Vast batch stopped with {len(names)} voices missing. "
                                       f"Its log ({log_file}):\n{tail}")
        except (RuntimeError, subprocess.TimeoutExpired) as error:   # the connection dropped: keep waiting
            log.warning("Vast connection problem, retrying: %s", error)
        if time.monotonic() - last_progress > config.VAST_STALL_TIMEOUT:
            raise chrome.NeedsUser(f"No voice arrived from Vast for {config.VAST_STALL_TIMEOUT // 60} minutes; "
                                   f"see {log_file} on the box. Run the command again to carry on.")
    return saved
