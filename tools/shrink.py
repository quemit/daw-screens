"""Keeps the DaW Now Showing TV videos playable on the Fire TVs.
1. Shrinks oversized videos in the Drive folders (TV copy in Drive, original to Originals).
2. Keeps a streaming copy of every TV video in media/ on GitHub Pages, so the TVs play
   them straight from the web instead of loading whole files into their small memory.
Runs on GitHub every few minutes. Talks only to the Now Showing web app."""
import base64, json, os, subprocess, sys, urllib.request
from pathlib import Path

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


def verify(path):
    """Decode the whole file once; a copy that will not decode never reaches the TVs."""
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-f", "null", "-"], capture_output=True, text=True)
    return r.returncode == 0 and not r.stderr.strip()


def mirror():
    media = Path("media"); media.mkdir(exist_ok=True)
    man_path = media / "manifest.json"
    man = json.loads(man_path.read_text()) if man_path.exists() else {"files": {}}
    files = man["files"]
    vids = call("videos")["items"]
    keep = set()
    changed = False
    for it in vids:
        keep.add(it["id"])
        if files.get(it["id"], {}).get("v") == it["version"] and (media / f"{it['id']}.mp4").exists():
            continue
        print(f"stream copy: {it['folder']}/{it['name']}")
        download(it, "m_in.bin")
        out = media / f"{it['id']}.mp4"
        # the exact settings proven to play on the Fire TVs: 1080p H.264, about 1.6 Mbps peak, no sound track
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", "m_in.bin",
                        "-vf", "scale='min(1920,iw)':'min(1080,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2",
                        "-c:v", "libx264", "-preset", "veryfast", "-profile:v", "high", "-level", "4.0", "-pix_fmt", "yuv420p",
                        "-crf", "25", "-maxrate", "1600k", "-bufsize", "3200k", "-an", "-movflags", "+faststart", str(out)], check=True)
        os.remove("m_in.bin")
        if not verify(str(out)):
            print("  copy failed its check, skipped"); out.unlink(); continue
        files[it["id"]] = {"v": it["version"], "f": f"media/{it['id']}.mp4", "name": it["name"]}
        changed = True
    for vid in list(files):
        if vid not in keep:
            print(f"removing stream copy of {files[vid].get('name')}")
            p = media / f"{vid}.mp4"
            if p.exists(): p.unlink()
            del files[vid]; changed = True
    if changed:
        man_path.write_text(json.dumps(man, indent=1))
    print(f"{len(files)} streaming copies")


def main():
    items = call("list")["items"]
    print(f"{len(items)} video(s) waiting")
    for it in items:
        print(f"- {it['folder']}/{it['name']} ({it['size'] // 1048576} MB)")
        src, dst = "in.bin", "out.mp4"
        download(it, src)
        secs = duration(src)
        audio = 64 if has_audio(src) else 0
        kbps = int(min(1600, TARGET * 8 / 1000 / secs - audio))
        for _ in range(3):
            size = encode(src, dst, max(kbps, 150))
            if size <= TARGET:
                break
            kbps = int(kbps * TARGET / size * 0.9)
        if not verify(dst):
            print("  TV copy failed its check, left as is"); continue
        data = base64.b64encode(open(dst, "rb").read()).decode()
        res = call("put", id=it["id"], data=data)
        print(f"  done: {res['name']} ({res['size'] // 1024} KB), original kept in Originals")
        os.remove(src); os.remove(dst)
    try:
        mirror()
    except Exception as e:  # streaming copies are extra; never let them stop the shrinker
        print("streaming copies skipped:", e)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("error:", e)
        sys.exit(1)
