"""Sample music, audiobooks, ebooks and comics for trying GharBox (and for its tests).

    python3 scripts/sample_shelf.py ./sample-media

Needs ffmpeg and Pillow. Everything is generated: tones, coloured pages, short chapters.
"""
from __future__ import annotations

import io
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw


def picture(text: str, color: tuple[int, int, int], size: tuple[int, int] = (600, 600)) -> Image.Image:
    im = Image.new("RGB", size, color)
    d = ImageDraw.Draw(im)
    d.rectangle([20, 20, size[0] - 20, size[1] - 20], outline=(255, 255, 255), width=6)
    d.text((50, size[1] // 2 - 10), text, fill=(255, 255, 255))
    return im


def png_bytes(im: Image.Image, fmt: str = "PNG") -> bytes:
    out = io.BytesIO()
    im.save(out, fmt)
    return out.getvalue()


def tone(path: Path, seconds: float = 3, freq: int = 440, tags: dict | None = None,
         cover: Image.Image | None = None, codec: list[str] | None = None, chapters: list[tuple[str, float]] | None = None) -> Path:
    """An audio file with tags, optional embedded cover art and optional chapters."""
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}"]
    tmp = []
    if cover is not None:
        art = path.with_name(f"_{path.stem}.jpg")
        cover.save(art, "JPEG")
        tmp.append(art)
        cmd += ["-i", str(art)]
    if chapters:
        meta = path.with_name(f"_{path.stem}.txt")
        lines = [";FFMETADATA1"]
        for i, (title, start) in enumerate(chapters):
            end = chapters[i + 1][1] if i + 1 < len(chapters) else seconds
            lines += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={int(start * 1000)}", f"END={int(end * 1000)}", f"title={title}"]
        meta.write_text("\n".join(lines) + "\n")
        tmp.append(meta)
        cmd += ["-i", str(meta), "-map_chapters", str(1 + (cover is not None))]
    cmd += ["-map", "0:a"]
    if cover is not None:
        cmd += ["-map", "1:v", "-c:v", "mjpeg", "-disposition:v", "attached_pic"]
    for k, v in (tags or {}).items():
        cmd += ["-metadata", f"{k}={v}"]
    ext = path.suffix.lower()
    cmd += codec or {".mp3": ["-c:a", "libmp3lame", "-b:a", "96k", "-id3v2_version", "3"],
                     ".m4a": ["-c:a", "aac", "-b:a", "96k"], ".m4b": ["-c:a", "aac", "-b:a", "64k"],
                     ".flac": ["-c:a", "flac"], ".ogg": ["-c:a", "libvorbis"], ".opus": ["-c:a", "libopus"],
                     ".wma": ["-c:a", "wmav2", "-b:a", "96k"]}.get(ext, [])
    cmd.append(str(path))
    subprocess.run(cmd, check=True)
    for t in tmp:
        t.unlink()
    return path


def music(root: Path) -> None:
    red = picture("Monsoon Songs", (170, 40, 60))
    for n, title in enumerate(["Rain on Tin", "Rickshaw Bell", "Evening Tea"], 1):
        tone(root / "Shonar Band" / "Monsoon Songs (2021)" / f"{n:02d} - {title}.mp3", 3, 300 + n * 80,
             {"title": title, "artist": "Shonar Band", "album": "Monsoon Songs", "track": f"{n}/3",
              "date": "2021", "genre": "Folk"}, cover=red if n == 1 else None)
    # Untagged files: names and folders are used
    folder = root / "Old Tapes" / "Live at Home"
    for n, title in enumerate(["Opening", "Closing Song"], 1):
        tone(folder / f"{n:02d} {title}.flac", 2, 500 + n * 50)
    picture("Live at Home", (40, 90, 160)).save(folder / "cover.jpg", "JPEG")
    # Browsers can't play WMA: GharBox converts it once
    tone(root / "Singles" / "Old Radio.wma", 2, 700, {"title": "Old Radio", "artist": "Radio Days"})


def audiobooks(root: Path) -> None:
    folder = root / "Rabindra Thakur" / "Short Stories"
    cover = picture("Short Stories", (30, 110, 80))
    for n, title in enumerate(["The Postmaster", "Kabuliwala", "Subha"], 1):
        tone(folder / f"{n:02d} {title}.mp3", 4, 220 + n * 40,
             {"title": title, "album": "Short Stories", "artist": "Rabindra Thakur", "composer": "Amio Reader",
              "track": str(n)}, cover=cover if n == 1 else None)
    tone(root / "The River Journey.m4b", 12, 330, {"title": "The River Journey", "album": "The River Journey",
                                                  "artist": "Nadi Writer", "genre": "Audiobook"},
         cover=picture("The River Journey", (20, 60, 120)),
         chapters=[("Chapter 1: Departure", 0), ("Chapter 2: The Delta", 4), ("Chapter 3: Home", 8)])


EPUB_CONTAINER = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""


def epub(path: Path, title: str, author: str, chapters: int = 3, series: tuple[str, int] | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    series_meta = (f'<meta name="calibre:series" content="{series[0]}"/>'
                   f'<meta name="calibre:series_index" content="{series[1]}"/>') if series else ""
    items, spine, nav, ncx = [], [], [], []
    para = ("<p>The river was wide and slow, and the boat moved with it as if it had all the time in the "
            "world. Children waved from the bank; a heron lifted off the water and settled again further on.</p>")
    for n in range(1, chapters + 1):
        items.append(f'<item id="c{n}" href="ch{n}.xhtml" media-type="application/xhtml+xml"/>')
        spine.append(f'<itemref idref="c{n}"/>')
        nav.append(f'<li><a href="ch{n}.xhtml">Chapter {n}</a></li>')
        ncx.append(f'<navPoint id="n{n}" playOrder="{n}"><navLabel><text>Chapter {n}</text></navLabel>'
                   f'<content src="ch{n}.xhtml"/></navPoint>')
    opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="id">urn:gharbox:{title.replace(' ', '-').lower()}</dc:identifier>
    <dc:title>{title}</dc:title><dc:creator>{author}</dc:creator><dc:language>en</dc:language>
    <dc:date>2020-01-01</dc:date><dc:description>&lt;p&gt;A short sample book about {title.lower()}.&lt;/p&gt;</dc:description>
    <meta name="cover" content="cover-img"/>{series_meta}
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="cover-img" href="images/cover.png" media-type="image/png" properties="cover-image"/>
    <item id="css" href="style.css" media-type="text/css"/>
    {''.join(items)}
  </manifest>
  <spine toc="ncx">{''.join(spine)}</spine>
</package>"""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip")  # stored, first
        z.writestr("META-INF/container.xml", EPUB_CONTAINER)
        z.writestr("OEBPS/content.opf", opf)
        z.writestr("OEBPS/style.css", "body { font-family: serif; line-height: 1.5; } h1 { color: #7a3; }")
        z.writestr("OEBPS/images/cover.png", png_bytes(picture(title, (120, 70, 30), (400, 600))))
        z.writestr("OEBPS/nav.xhtml", f'<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml" '
                   f'xmlns:epub="http://www.idpf.org/2007/ops"><head><title>Contents</title></head><body>'
                   f'<nav epub:type="toc"><ol>{"".join(nav)}</ol></nav></body></html>')
        z.writestr("OEBPS/toc.ncx", f'<?xml version="1.0"?><ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
                   f'<head/><docTitle><text>{title}</text></docTitle><navMap>{"".join(ncx)}</navMap></ncx>')
        for n in range(1, chapters + 1):
            z.writestr(f"OEBPS/ch{n}.xhtml", f'<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml">'
                       f'<head><title>Chapter {n}</title><link rel="stylesheet" href="style.css" type="text/css"/></head>'
                       f'<body><h1>Chapter {n}</h1>{para * 14}<p id="end{n}">End of chapter {n}.</p></body></html>')
    return path


def pdf(path: Path, title: str, pages: int = 4) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    ims = [picture(f"{title} - page {n}", (240, 240, 235) if n > 1 else (60, 60, 90), (595, 842)) for n in range(1, pages + 1)]
    for n, im in enumerate(ims[1:], 2):
        ImageDraw.Draw(im).text((60, 80), f"Page {n} of {title}", fill=(20, 20, 20))
    ims[0].save(path, "PDF", save_all=True, append_images=ims[1:], title=title, author="Sample Author")
    return path


COMIC_INFO = """<?xml version="1.0"?>
<ComicInfo><Series>{series}</Series><Number>{number}</Number><Title>{title}</Title><Writer>{writer}</Writer>
<Year>2022</Year><Summary>A sample comic.</Summary><Manga>{manga}</Manga></ComicInfo>"""


def comic_pages(name: str, count: int, base: tuple[int, int, int]) -> list[bytes]:
    return [png_bytes(picture(f"{name} p{n}", tuple(min(255, c + n * 12) for c in base), (500, 750)), "JPEG")
            for n in range(1, count + 1)]


def cbz(path: Path, series: str, number: int, pages: int = 5, manga: bool = False, info: bool = True) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        for n, data in enumerate(comic_pages(f"{series} {number}", pages, (30, 80, 140)), 1):
            z.writestr(f"{series} {number:03d}/page{n}.jpg", data)  # page10 must sort after page9
        if info:
            z.writestr("ComicInfo.xml", COMIC_INFO.format(series=series, number=number, title=f"Issue {number}",
                                                          writer="Sample Writer",
                                                          manga="YesAndRightToLeft" if manga else "No"))
    return path


def cb7(path: Path, name: str, pages: int = 3) -> Path | None:
    """A 7-Zip comic, made with bsdtar when it's installed (stands in for CBR: same code path)."""
    exe = shutil.which("bsdtar")
    if not exe:
        return None
    work = path.with_name(f"_{path.stem}")
    work.mkdir(parents=True, exist_ok=True)
    for n, data in enumerate(comic_pages(name, pages, (120, 40, 120)), 1):
        (work / f"{n:02d}.jpg").write_bytes(data)
    subprocess.run([exe, "--format", "7zip", "-cf", str(path), "-C", str(work), "."], check=True)
    shutil.rmtree(work)
    return path


def books(root: Path) -> None:
    epub(root / "Nadi Writer" / "The River Journey.epub", "The River Journey", "Nadi Writer", 4)
    epub(root / "Delta Tales 1.epub", "Delta Tales: Book One", "Mira Das", 2, series=("Delta Tales", 1))
    epub(root / "Delta Tales 2.epub", "Delta Tales: Book Two", "Mira Das", 2, series=("Delta Tales", 2))
    pdf(root / "Cooking with Mustard Oil.pdf", "Cooking with Mustard Oil", 4)


def comics(root: Path) -> None:
    cbz(root / "Sky Rider" / "Sky Rider 001.cbz", "Sky Rider", 1, pages=12)
    cbz(root / "Sky Rider" / "Sky Rider 002.cbz", "Sky Rider", 2)
    cbz(root / "Moon Cat v01.cbz", "Moon Cat", 1, manga=True)
    cb7(root / "Tiger Tales 01.cb7", "Tiger Tales 01")
    chapter = root / "Hero Academy" / "Chapter 001"
    chapter.mkdir(parents=True, exist_ok=True)
    for n, data in enumerate(comic_pages("Hero Academy ch1", 4, (20, 120, 60)), 1):
        (chapter / f"{n:03d}.jpg").write_bytes(data)


def make_all(out: Path) -> None:
    music(out / "Music")
    audiobooks(out / "Audiobooks")
    books(out / "Ebooks")
    comics(out / "Comics")


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "./sample-media")
    make_all(target)
    print(f"Music, audiobooks, ebooks and comics written to {target}")
