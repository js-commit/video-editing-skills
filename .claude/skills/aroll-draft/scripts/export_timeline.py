#!/usr/bin/env python3
"""Turn a TimeBolt-format cut list (keep/remove ops in seconds) into timelines
DaVinci Resolve imports with File > Import > Timeline: an XMEML (FCP7 XML v4)
`.xml` and a CMX3600 `.edl`.

Frame math (the Video Haircut scheme): clip math runs at the native fps (e.g.
23.976) so nothing drifts, while the XML timebase is the standard rate (24) plus
the NTSC flag. Record-side placement distributes rounding error Bresenham-style,
and each source span takes its length from its record span, so every event's
source and record durations match (CMX3600 requires it).

The source file's embedded start timecode (cameras often record one, e.g.
02:00:06:00) is written into both files: Resolve matches EDL events to media by
source timecode, so an EDL that assumed 00:00:00:00 would not link.

Usage:
  python3 export_timeline.py <cuts.tb.json> <media-file> [-o outdir] [--fps 23.976]
      [--formats xml,edl] [--name "<timeline name>"]

Writes <stem>.aroll.xml / <stem>.aroll.edl into -o (default: next to the cut
list). Summary JSON on stdout.

Exit codes: 0 ok, 2 usage/input error.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path, PurePosixPath
from urllib.parse import quote
from xml.sax.saxutils import escape

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))
from vidkit import media  # noqa: E402

STANDARD_RATES = [23.976, 24, 25, 29.97, 30, 50, 59.94, 60]


def die(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(2)


def probe_media(path):
    """(fps, total_frames, width, height, duration, start_timecode or None)."""
    out = subprocess.run(
        [media.ffprobe(), "-v", "error",
         "-show_entries", "stream=codec_type,r_frame_rate,width,height,nb_frames:stream_tags=timecode"
                          ":format=duration:format_tags=timecode",
         "-of", "json", str(path)],
        capture_output=True, text=True)
    if out.returncode != 0:
        die(f"ffprobe failed on {path}: {out.stderr.strip()}")
    data = json.loads(out.stdout or "{}")
    streams = data.get("streams") or []
    video = [s for s in streams if s.get("codec_type") == "video"]
    if not video:
        die(f"no video stream in {path}: the timeline exports need video")
    stream = video[0]
    num, den = (stream.get("r_frame_rate") or "0/1").split("/")
    fps = float(num) / float(den) if float(den) else None
    duration = float(data.get("format", {}).get("duration", 0) or 0) or None
    nb = stream.get("nb_frames")
    total_frames = int(nb) if nb and str(nb).isdigit() else None
    if total_frames is None and duration and fps:
        total_frames = math.floor(duration * fps)
    width = stream.get("width") or 3840
    height = stream.get("height") or 2160
    if width < 100 or height < 100:
        width, height = 3840, 2160
    tc = (data.get("format", {}).get("tags") or {}).get("timecode")
    for s in streams:
        tc = tc or (s.get("tags") or {}).get("timecode")
    return fps, total_frames, width, height, duration, tc


def standard_fps(fps):
    ntsc_map = {23.976: 24, 29.97: 30, 59.94: 60}
    best = min(STANDARD_RATES, key=lambda r: abs(r - fps))
    if abs(best - fps) < 0.05 and best in ntsc_map:
        return ntsc_map[best], True
    return round(fps), False


def tc_to_frames(tc, timebase):
    """'HH:MM:SS:FF' (or ';' drop-frame separators, read as non-drop) -> frames; 0 if unparseable."""
    m = re.match(r"^(\d+):(\d+):(\d+)[:;.](\d+)$", (tc or "").strip())
    if not m:
        return 0
    h, mi, s, f = (int(x) for x in m.groups())
    return ((h * 60 + mi) * 60 + s) * timebase + f


def frames_to_tc(frame_count, timebase):
    f = int(frame_count)
    hours, rem = divmod(f, timebase * 3600)
    minutes, rem = divmod(rem, timebase * 60)
    secs, frames = divmod(rem, timebase)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}:{frames:02d}"


def distribute_frames(keeps, fps):
    """Bresenham frame distribution for record-side placement."""
    placed, distributed, cum_err = [], 0, 0.0
    for seg in keeps:
        exact = seg["duration"] * fps
        base = math.floor(exact)
        cum_err += exact - base
        extra = 1 if cum_err >= 0.5 else 0
        cum_err -= extra
        frames = base + extra
        placed.append({"seg": seg, "start": distributed, "end": distributed + frames})
        distributed += frames
    return placed, distributed


def source_span(pl, native_fps, total_frames):
    """Source in/out frames for a placed clip. Length comes from the record span;
    past the media end the span shifts earlier instead of shrinking."""
    i = math.floor(pl["seg"]["start"] * native_fps)
    o = i + (pl["end"] - pl["start"])
    if o > total_frames:
        i = max(0, i - (o - total_frames))
        o = total_frames
    return i, o


def file_url(path):
    p = Path(os.path.abspath(path)).as_posix()
    if not p.startswith("/"):
        p = "/" + p          # Windows: C:/... -> /C:/...
    return "file://localhost" + "/".join(quote(part) for part in PurePosixPath(p).as_posix().split("/"))


# ---------------------------------------------------------------- XMEML

def build_xmeml(keeps, media_path, native_fps, total_frames, width, height, name, start_tc):
    tb_fps, ntsc = standard_fps(native_fps)
    ntsc_s = "TRUE" if ntsc else "FALSE"
    placed, out_total = distribute_frames(keeps, native_fps)
    file_name = escape(os.path.basename(media_path))
    seq_name = escape(name)
    tc_frames = tc_to_frames(start_tc, tb_fps) if start_tc else 0
    tc_string = frames_to_tc(tc_frames, tb_fps)
    seq_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, file_url(media_path) + "#" + name))

    rate = (f"<rate>\n<timebase>{tb_fps}</timebase>\n"
            f"<ntsc>{ntsc_s}</ntsc>\n</rate>")

    file_block_full = f"""<file id="file-1">
<name>{file_name}</name>
<pathurl>{file_url(media_path)}</pathurl>
{rate}
<duration>{total_frames}</duration>
<timecode>
{rate}
<string>{tc_string}</string>
<frame>{tc_frames}</frame>
<displayformat>NDF</displayformat>
</timecode>
<media>
<video>
<samplecharacteristics>
{rate}
<width>{width}</width>
<height>{height}</height>
<pixelaspectratio>square</pixelaspectratio>
<fielddominance>none</fielddominance>
</samplecharacteristics>
</video>
<audio>
<samplecharacteristics>
<depth>16</depth>
<samplerate>48000</samplerate>
<channelcount>2</channelcount>
</samplecharacteristics>
<channelcount>2</channelcount>
<audiochannel>
<sourcechannel>1</sourcechannel>
</audiochannel>
</audio>
</media>
</file>"""

    def link(ref, mediatype, track, i):
        return (f"<link>\n<linkclipref>clipitem-{ref}</linkclipref>\n<mediatype>{mediatype}</mediatype>\n"
                f"<trackindex>{track}</trackindex>\n<clipindex>{i + 1}</clipindex>\n"
                f"<groupindex>1</groupindex>\n</link>")

    def clip_head(cid, pl, extra_attr=""):
        inf, outf = source_span(pl, native_fps, total_frames)
        return (f"<clipitem id=\"clipitem-{cid}\"{extra_attr}>\n<masterclipid>masterclip-1</masterclipid>\n"
                f"<name>{file_name}</name>\n<enabled>TRUE</enabled>\n<duration>{total_frames}</duration>\n"
                f"{rate}\n<start>{pl['start']}</start>\n<end>{pl['end']}</end>\n<in>{inf}</in>\n<out>{outf}</out>")

    labels = "<labels>\n<label2>Iris</label2>\n</labels>"
    parts = [f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE xmeml>
<xmeml version="4">
<sequence>
<uuid>{seq_uuid}</uuid>
<duration>{out_total}</duration>
{rate}
<name>{seq_name}</name>
<media>
<video>
<format>
<samplecharacteristics>
{rate}
<codec>
<name>Apple ProRes 422</name>
<appspecificdata>
<appname>Final Cut Pro</appname>
<appmanufacturer>Apple Inc.</appmanufacturer>
<appversion>7.0</appversion>
<data>
<qtcodec>
<codecname>Apple ProRes 422</codecname>
<codectypename>Apple ProRes 422</codectypename>
<codectypecode>apcn</codectypecode>
<codecvendorcode>appl</codecvendorcode>
<spatialquality>1024</spatialquality>
<temporalquality>0</temporalquality>
<keyframerate>0</keyframerate>
<datarate>0</datarate>
</qtcodec>
</data>
</appspecificdata>
</codec>
<width>{width}</width>
<height>{height}</height>
<pixelaspectratio>square</pixelaspectratio>
<fielddominance>none</fielddominance>
<colordepth>24</colordepth>
</samplecharacteristics>
</format>
<track>"""]

    # video track: clipitem ids 1, 4, 7, ...
    for i, pl in enumerate(placed):
        cid = 1 + i * 3
        parts.append("\n".join([
            clip_head(cid, pl), "<pixelaspectratio>square</pixelaspectratio>",
            file_block_full if i == 0 else '<file id="file-1"/>', labels,
            link(cid, "video", 1, i), link(cid + 1, "audio", 1, i), link(cid + 2, "audio", 2, i),
            "</clipitem>"]))

    parts.append("""<enabled>TRUE</enabled>
<locked>FALSE</locked>
</track>
</video>
<audio>
<numOutputChannels>2</numOutputChannels>
<format>
<samplecharacteristics>
<depth>16</depth>
<samplerate>48000</samplerate>
</samplecharacteristics>
</format>
<outputs>
<index>1</index>
<numchannels>1</numchannels>
<downmix>0</downmix>
<channel>
<index>1</index>
</channel>
</outputs>
<outputs>
<index>2</index>
<numchannels>1</numchannels>
<downmix>0</downmix>
<channel>
<index>2</index>
</channel>
</outputs>
<track currentExplodedTrackIndex="0" totalExplodedTrackCount="2" premiereTrackType="Stereo">""")

    source_track = "<sourcetrack>\n<mediatype>audio</mediatype>\n<trackindex>1</trackindex>\n</sourcetrack>"
    # audio track 1: clipitem ids 2, 5, 8, ...
    for i, pl in enumerate(placed):
        cid = 2 + i * 3
        parts.append("\n".join([
            clip_head(cid, pl, ' premiereChannelType="stereo"'), '<file id="file-1"/>', source_track,
            link(cid - 1, "video", 1, i), link(cid, "audio", 1, i), link(cid + 1, "audio", 2, i),
            labels, "</clipitem>"]))

    parts.append("""<enabled>TRUE</enabled>
<locked>FALSE</locked>
<outputchannelindex>1</outputchannelindex>
</track>
<track currentExplodedTrackIndex="1" totalExplodedTrackCount="2" premiereTrackType="Stereo">""")

    # audio track 2: clipitem ids 3, 6, 9, ...
    for i, pl in enumerate(placed):
        cid = 3 + i * 3
        parts.append("\n".join([
            clip_head(cid, pl, ' premiereChannelType="stereo"'), '<file id="file-1"/>', source_track,
            labels, "</clipitem>"]))

    parts.append(f"""<enabled>TRUE</enabled>
<locked>FALSE</locked>
<outputchannelindex>2</outputchannelindex>
</track>
</audio>
</media>
<timecode>
{rate}
<string>00:00:00:00</string>
<frame>0</frame>
<displayformat>NDF</displayformat>
</timecode>
</sequence>
</xmeml>""")
    return "\n".join(parts), out_total


# ---------------------------------------------------------------- EDL

def build_edl(keeps, media_path, native_fps, total_frames, name, start_tc):
    tb_fps, _ = standard_fps(native_fps)
    placed, _ = distribute_frames(keeps, native_fps)
    file_name = os.path.basename(media_path)
    src0 = tc_to_frames(start_tc, tb_fps) if start_tc else 0
    lines = [f"TITLE: {name}", "FCM: NON-DROP FRAME", ""]
    edit = 1
    for pl in placed:
        src_in, src_out = source_span(pl, native_fps, total_frames)
        si, so = frames_to_tc(src0 + src_in, tb_fps), frames_to_tc(src0 + src_out, tb_fps)
        ri, ro = frames_to_tc(pl["start"], tb_fps), frames_to_tc(pl["end"], tb_fps)
        for kind, extra in (("V    ", None), ("AA   ", None), ("NONE ", "AUD  3    4")):
            lines += [f"{edit:03d}  AX       {kind} C        {si} {so} {ri} {ro}",
                      f"* FROM CLIP NAME: {file_name}"]
            if extra:
                lines.append(extra)
            lines.append("")
            edit += 1
    return "\n".join(lines)


# ---------------------------------------------------------------- main

def export(cutlist, media_path, outdir=None, fps=None, formats=("xml", "edl"), name=None):
    with open(cutlist, encoding="utf-8") as f:
        ops = json.load(f)
    keeps = [o for o in ops if o["operation"] == "keep"]
    if not keeps:
        die("cut list has no keep ops")
    pfps, total_frames, width, height, _duration, start_tc = probe_media(media_path)
    native_fps = fps or pfps
    if not native_fps:
        die("could not determine fps; pass --fps")
    if total_frames is None:
        die("could not determine the total frame count")
    tb_fps, ntsc = standard_fps(native_fps)
    stem = Path(media_path).stem
    name = name or f"{stem} first cut"
    outdir = outdir or os.path.dirname(os.path.abspath(cutlist))
    os.makedirs(outdir, exist_ok=True)

    written = {}
    if "xml" in formats:
        xml, _ = build_xmeml(keeps, media_path, native_fps, total_frames, width, height, name, start_tc)
        path = os.path.join(outdir, f"{stem}.aroll.xml")
        with open(path, "w", encoding="utf-8") as f:
            f.write(xml)
        written["xml"] = path
    if "edl" in formats:
        path = os.path.join(outdir, f"{stem}.aroll.edl")
        with open(path, "w", encoding="utf-8") as f:
            f.write(build_edl(keeps, media_path, native_fps, total_frames, name, start_tc))
        written["edl"] = path
    return {"written": written, "timeline_name": name, "clips": len(keeps),
            "native_fps": round(native_fps, 3), "timebase_fps": tb_fps, "ntsc": ntsc,
            "source_start_timecode": start_tc,
            "timeline_duration_s": round(sum(k["duration"] for k in keeps), 2)}


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cutlist")
    p.add_argument("media")
    p.add_argument("-o", "--outdir")
    p.add_argument("--fps", type=float, help="override the probed frame rate")
    p.add_argument("--formats", default="xml,edl")
    p.add_argument("--name", help="timeline name shown in Resolve (default '<stem> first cut')")
    args = p.parse_args()
    formats = {f.strip() for f in args.formats.split(",")}
    print(json.dumps(export(args.cutlist, args.media, args.outdir, args.fps, formats, args.name)))


if __name__ == "__main__":
    main()
