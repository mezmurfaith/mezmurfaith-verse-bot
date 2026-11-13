"""Turns the 4:5 verse poster into a 9:16 Reel video (the mezmur is attached by Instagram).

The video itself is silent: Instagram adds the song from its music library using the
audio_id of a mezmur already used on this account's own Reels.
"""
import pathlib
import subprocess

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from bot import render

RW, RH = 1080, 1920


def tall_canvas(poster: Image.Image, seed: int = 7) -> Image.Image:
    """Put the poster in the middle of a tall cream page, blending its edges softly."""
    bg = render.paper(seed).resize((RW, RH), Image.BICUBIC)
    # re-add fine grain so the stretched paper doesn't look smooth
    grain = Image.effect_noise((RW, RH), 14).filter(ImageFilter.GaussianBlur(0.6)).convert("RGB")
    bg = Image.blend(bg, ImageChops.multiply(bg, Image.merge("RGB", [grain.getchannel(0)] * 3).point(
        lambda v: 235 + v // 12)), 0.5)
    top = (RH - poster.height) // 2
    mask = Image.new("L", poster.size, 0)
    ImageDraw.Draw(mask).rectangle([0, 40, poster.width, poster.height - 40], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(26))
    bg.paste(poster.convert("RGB"), (0, top), mask)
    return bg


def make_video(poster: Image.Image, out_path, seconds: int = 30) -> pathlib.Path:
    """Silent H.264 MP4, 1080x1920, with a very slow gentle zoom."""
    import imageio_ffmpeg

    out_path = pathlib.Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    still = out_path.with_suffix(".frame.jpg")
    tall_canvas(poster).save(still, "JPEG", quality=95)
    fps = 30
    frames = seconds * fps
    zoom = f"zoompan=z='1+0.04*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={RW}x{RH}:fps={fps}"
    cmd = [
        imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
        "-loop", "1", "-i", str(still),
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-vf", f"scale={RW * 2}:{RH * 2},{zoom},format=yuv420p",
        "-t", str(seconds), "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-r", str(fps),
        "-pix_fmt", "yuv420p", "-color_range", "tv",
        "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart",
        str(out_path),
    ]
    subprocess.run(cmd, check=True)
    still.unlink(missing_ok=True)
    return out_path
