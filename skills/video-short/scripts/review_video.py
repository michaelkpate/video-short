"""Review any video on the frame-comment page, outside a Video Short project: a music video, a lyric video, any render.
The page plays the video on a timeline split into bands. Pause on any frame, press C to comment, and click Send:
the notes are saved and printed with a still of each commented frame, and the script exits.
usage: review_video.py VIDEO [--scenes FILE] [--every SECONDS] [--out DIR] [--no-open] [--port 8791] [--timeout 7200]

Bands come from --scenes:
  .json      a list of {"start", "end"} with optional "id", "label" (a short tag shown with the band) and "text"
             (shown on hover and quoted in the notes), or {"scenes": [...]}
  .srt .vtt  one band per cue, its text quoted
  .lrc       one band per timed lyric line, running to the next line
Without --scenes, the timeline is cut into --every second bands (default 10). Gaps between cues become unlabelled bands.
Notes go to OUT/feedback.md and stills to OUT/review-frames/. OUT defaults to a "<video name>-review" folder beside
the video, and must be on the same drive. Needs only Python 3.10+ and ffmpeg/ffprobe, so it runs without the venv.
Run it again with --no-open after re-rendering to the same path: the open page reloads itself."""
import argparse, json, os, re, sys

from review_page import probe, serve, write_page

TIME = r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})"


def secs(h, m, s, frac):
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(frac.ljust(3, "0")[:3]) / 1000


def from_subtitles(text):
    """SRT or WebVTT cues: [(start, end, text)]."""
    cues = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        lines = block.strip().split("\n")
        for i, line in enumerate(lines):
            m = re.match(rf"\s*{TIME}\s*-->\s*{TIME}", line)
            if m:
                g = m.groups()
                body = " ".join(re.sub(r"<[^>]+>", "", x).strip() for x in lines[i + 1:] if x.strip())
                cues.append((secs(*g[:4]), secs(*g[4:]), body))
                break
    return cues


def from_lrc(text, duration):
    """LRC lyrics: each [mm:ss.xx] line runs until the next timed line, the last until the end."""
    timed = []
    for line in text.replace("\r\n", "\n").split("\n"):
        tags = re.findall(r"\[(\d+):(\d{2})(?:[.:](\d{1,3}))?\]", line)
        body = re.sub(r"\[[^\]]*\]", "", line).strip()
        timed += [(int(m) * 60 + int(s) + int((f or "0").ljust(3, "0")[:3]) / 1000, body) for m, s, f in tags]
    timed.sort()
    return [(t, timed[i + 1][0] if i + 1 < len(timed) else duration, body) for i, (t, body) in enumerate(timed)]


def from_json(data):
    items = data.get("scenes", []) if isinstance(data, dict) else data
    return [(float(x["start"]), float(x["end"]), x.get("text", x.get("spoken", "")), x.get("label", x.get("layout", "")),
             str(x.get("id", ""))) for x in items]


def build_scenes(cues, duration):
    """Cues [(start, end, text[, label[, id]])] -> page scenes covering 0..duration, in order, with gaps filled."""
    scenes, t = [], 0.0
    for cue in sorted(cues, key=lambda c: c[0]):
        start, end, text = max(cue[0], t), min(cue[1], duration), cue[2]
        if end - start < 0.05:
            continue
        if start - t >= 0.05:
            scenes.append({"start": t, "end": start, "layout": "", "spoken": "", "own_id": ""})
        scenes.append({"start": start, "end": end, "layout": cue[3] if len(cue) > 3 else "", "spoken": text,
                       "own_id": cue[4] if len(cue) > 4 else ""})
        t = end
    if duration - t >= 0.05 or not scenes:
        scenes.append({"start": t, "end": duration, "layout": "", "spoken": "", "own_id": ""})
    scenes[-1]["end"] = duration
    own = [s["own_id"] for s in scenes]
    keep_own = all(own) and len(set(own)) == len(own)   # the file's ids only when every band has a unique one
    width = max(2, len(str(len(scenes))))
    return [{"id": s["own_id"] if keep_own else f"s{i + 1:0{width}d}", "start": round(s["start"], 3), "end": round(s["end"], 3),
             "layout": s["layout"], "visual": "", "spoken": s["spoken"]} for i, s in enumerate(scenes)]


def load_scenes(path, every, duration):
    if not path:
        n = max(1, int(-(-duration // every)))
        return build_scenes([(i * every, min((i + 1) * every, duration), "") for i in range(n)], duration)
    text = open(path, encoding="utf-8-sig").read()
    ext = os.path.splitext(path)[1].lower()
    if ext == ".json":
        cues = from_json(json.loads(text))
    elif ext == ".lrc":
        cues = from_lrc(text, duration)
    elif ext in (".srt", ".vtt"):
        cues = from_subtitles(text)
    else:
        sys.exit(f"error: --scenes takes .json, .srt, .vtt or .lrc, not {ext or 'a file with no extension'}")
    if not cues:
        sys.exit(f"error: no timed entries found in {path}")
    return build_scenes(cues, duration)


def main():
    for stream in (sys.stdout, sys.stderr):   # notes quote text with curly quotes; Windows consoles default to cp1252
        stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Review any video on the frame-comment page.")
    ap.add_argument("video")
    ap.add_argument("--scenes", help=".json, .srt, .vtt or .lrc file that splits the timeline into bands")
    ap.add_argument("--every", type=float, default=10.0, help="band length in seconds when there is no --scenes file")
    ap.add_argument("--out", help='folder for the page, notes and stills (default: "<video name>-review" beside the video)')
    ap.add_argument("--no-open", action="store_true", help="don't open a browser tab (an open page reloads itself)")
    ap.add_argument("--port", type=int, default=8791)
    ap.add_argument("--timeout", type=int, default=7200, help="seconds to wait for Send")
    a = ap.parse_args()

    video = os.path.abspath(a.video)
    if not os.path.isfile(video):
        sys.exit(f"error: no video at {video}")
    if a.every <= 0:
        sys.exit("error: --every must be more than 0")
    stem = os.path.splitext(os.path.basename(video))[0]
    out = os.path.abspath(a.out or os.path.join(os.path.dirname(video), f"{stem}-review"))
    try:
        root = os.path.commonpath([os.path.dirname(video), out])   # the server shares this folder, so it must hold both
    except ValueError:
        sys.exit(f"error: --out must be on the same drive as the video ({video})")
    os.makedirs(out, exist_ok=True)

    duration, _ = probe(video)
    scenes = load_scenes(a.scenes, a.every, duration)
    page = os.path.join(out, "index.html")
    write_page(root, page, video, scenes)
    print(f"{len(scenes)} bands over {duration:.2f}s.", flush=True)
    serve(root, page, os.path.join(out, "feedback.md"), scenes, video, a.port, not a.no_open, a.timeout)


if __name__ == "__main__":
    main()
