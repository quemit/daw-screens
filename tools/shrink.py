"""TV-Safe Inbox converter for DaW Now Showing (runs free on GitHub Actions).

Every video dropped in the Drive TV folders that is not yet stamped "tv-safe" is converted to the
recipe PROVEN on the venue Fire TVs on 2026-11-19:
    H.264 High, x264 preset slow defaults (level 5.0, ref 5, 3 B-frames, keyint 250),
    yuv420p, at most 30 fps and 1920x1080, no sound track, 2-pass to stay under 6 MB.
(Files made with preset veryslow / level 4.0 / 8 B-frames "played" but showed WHITE on the TVs.)
The TV script stamps the copy tv-safe and moves the original to Originals. TVs play only stamped videos.

Each run stays awake about 50 minutes and checks every 90 seconds, so a new video plays within minutes.
Talks only to the Now Showing web app, using SHRINK_KEY."""
import base64, json, os, subprocess, sys, time, urllib.request

URL = os.environ["NOW_SHOWING_URL"]
KEY = os.environ["SHRINK_KEY"]
TARGET = 5_700_000          # bytes we aim for; the TV script refuses anything over 6,000,000
HARD_MAX = 6_000_000
RUN_SECONDS = int(os.environ.get("RUN_SECONDS", "3000"))
POLL = 90


def call(action, **kw):
    body = json.dumps(dict(kw, key=KEY, action=action)).encode()
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:  # follows Google's redirect
        out = json.loads(r.read().decode())
    if not out.get("ok"):
        raise RuntimeError(out.get("error"))
    return out


def duration(path):
    s = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", path], capture_output=True, text=True).stdout
    try:
        return max(1.0, float(s.strip()))
    except ValueError:
        return 60.0


def download(it, path):
    with open(path, "wb") as f:
        start = 0
        while start < it["size"]:
            piece = call("chunk", id=it["id"], start=start)
            data = base64.b64decode(piece["data"])
            if not data:
                break
            f.write(data)
            start = piece["next"]


def encode(src, dst, kbps, w, h):
    vf = f"scale='min({w},iw)':'min({h},ih)':force_original_aspect_ratio=decrease:force_divisible_by=2"
    base = ["ffmpeg", "-y", "-v", "error", "-i", src, "-vf", vf, "-fpsmax", "30", "-an",
            "-c:v", "libx264", "-preset", "slow", "-profile:v", "high", "-pix_fmt", "yuv420p",
            "-b:v", f"{kbps}k", "-passlogfile", "x264pass"]
    subprocess.run(base + ["-pass", "1", "-f", "mp4", "/dev/null"], check=True)
    subprocess.run(base + ["-pass", "2", "-movflags", "+faststart", dst], check=True)
    return os.path.getsize(dst)


def verify(path):
    """Decode the whole file once; a copy that will not decode never reaches the TVs."""
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-f", "null", "-"], capture_output=True, text=True)
    return r.returncode == 0 and not r.stderr.strip()


def convert(it):
    print(f"- {it['folder']}/{it['name']} ({it['size'] // 1024} KB)", flush=True)
    src, dst = "in.bin", "out.mp4"
    download(it, src)
    secs = duration(src)
    kbps = min(2500, int(TARGET * 8 / 1000 / secs * 0.97))
    w, h = (1920, 1080) if kbps >= 900 else (1280, 720)   # long videos drop to 720p to stay sharp
    size = 0
    for _ in range(3):
        size = encode(src, dst, max(kbps, 150), w, h)
        if size <= TARGET:
            break
        kbps = int(kbps * TARGET / size * 0.93)
    if size > HARD_MAX or not verify(dst):
        raise RuntimeError(f"copy not TV-safe (size {size})")
    data = base64.b64encode(open(dst, "rb").read()).decode()
    res = call("put", id=it["id"], data=data)
    print(f"  done: {res['name']} ({res['size'] // 1024} KB, {w}x{h} max, {kbps} kbps), original kept in Originals", flush=True)
    for p in (src, dst):
        if os.path.exists(p):
            os.remove(p)


def main():
    start, fails = time.time(), {}
    while True:
        try:
            items = call("list")["items"]
        except Exception as e:  # a hiccup at Google never stops the watcher
            print("list failed:", e, flush=True)
            items = []
        for it in items:
            if fails.get(it["id"], 0) >= 2:
                continue
            try:
                convert(it)
            except Exception as e:
                fails[it["id"]] = fails.get(it["id"], 0) + 1
                print(f"  failed ({fails[it['id']]}): {e}", flush=True)
        if time.time() - start > RUN_SECONDS:
            break
        time.sleep(POLL)
    print("watcher finished this shift", flush=True)


if __name__ == "__main__":
    main()
