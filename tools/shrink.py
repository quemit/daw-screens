"""Shrinks oversized TV videos in the DaW Now Showing Drive folder.
Runs on GitHub every few minutes. Talks only to the Now Showing web app."""
import base64, json, os, subprocess, sys, urllib.request

URL = os.environ["NOW_SHOWING_URL"]
KEY = os.environ["SHRINK_KEY"]
TARGET = 9 * 1024 * 1024  # leave room under the 12 MB TV limit


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
    return max(1.0, float(s.strip() or 60))


def has_audio(path):
    s = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
                        "stream=index", "-of", "csv=p=0", path], capture_output=True, text=True).stdout
    return bool(s.strip())


def encode(src, dst, kbps):
    big = kbps >= 1100
    w, h = (1920, 1080) if big else (1280, 720)
    vf = f"scale='min({w},iw)':'min({h},ih)':force_original_aspect_ratio=decrease:force_divisible_by=2"
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", src, "-vf", vf, "-c:v", "libx264", "-preset", "veryfast",
           "-profile:v", "high", "-level", "4.0", "-pix_fmt", "yuv420p", "-r", "30",
           "-b:v", f"{kbps}k", "-maxrate", f"{kbps}k", "-bufsize", f"{kbps * 2}k"]
    cmd += ["-c:a", "aac", "-b:a", "64k"] if has_audio(src) else ["-an"]
    cmd += ["-movflags", "+faststart", dst]
    subprocess.run(cmd, check=True)
    return os.path.getsize(dst)


def main():
    items = call("list")["items"]
    print(f"{len(items)} video(s) waiting")
    for it in items:
        print(f"- {it['folder']}/{it['name']} ({it['size'] // 1048576} MB)")
        src, dst = "in.bin", "out.mp4"
        with open(src, "wb") as f:
            start = 0
            while start < it["size"]:
                piece = call("chunk", id=it["id"], start=start)
                data = base64.b64decode(piece["data"])
                if not data:
                    break
                f.write(data)
                start = piece["next"]
        secs = duration(src)
        audio = 64 if has_audio(src) else 0
        kbps = int(min(1600, TARGET * 8 / 1000 / secs - audio))
        for _ in range(3):
            size = encode(src, dst, max(kbps, 150))
            if size <= TARGET:
                break
            kbps = int(kbps * TARGET / size * 0.9)
        data = base64.b64encode(open(dst, "rb").read()).decode()
        res = call("put", id=it["id"], data=data)
        print(f"  done: {res['name']} ({res['size'] // 1024} KB), original kept in Originals")
        os.remove(src); os.remove(dst)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("error:", e)
        sys.exit(1)
