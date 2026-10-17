#!/usr/bin/env bash
# Makes a small media folder with every kind of category, for trying ZiraHive or for tests.
#   scripts/make-sample-media.sh ./sample-media
set -euo pipefail
OUT="${1:-./sample-media}"
clip() {
  mkdir -p "$(dirname "$1")"
  ffmpeg -y -v error -f lavfi -i "testsrc2=duration=4:size=640x360:rate=24" \
    -f lavfi -i "sine=duration=4" -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest "$1"
}
clip "$OUT/English Movies/Inception (2010)/Inception (2010).mp4"
clip "$OUT/English Movies/The.Matrix.1999.1080p.BluRay.mp4"
clip "$OUT/Hindi Movies/3 Idiots (2009).mp4"
clip "$OUT/Bangla Movies/Aynabaji (2016).mp4"
for e in 1 2 3; do clip "$OUT/Web Series/Mirzapur/Season 1/Mirzapur.S01E0$e.mp4"; done
clip "$OUT/Web Series/Mirzapur/Season 2/Mirzapur.S02E01.mp4"
clip "$OUT/Animation/Kung Fu Panda (2008).mp4"

# A film like a real download: MKV, AC-3 sound (browsers can't play it, so ZiraHive converts),
# Bangla + English audio, built-in Bangla subtitles, Intro chapter, and an English .srt beside it.
RICH="$OUT/Bangla Movies/Dhaka Nights (2024)"
mkdir -p "$RICH"
printf '1\n00:00:01,000 --> 00:00:04,000\nআমি বাংলায় কথা বলি\n\n' > "$RICH/_bn.srt"
printf ';FFMETADATA1\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=5000\ntitle=Intro\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=5000\nEND=40000\ntitle=Film\n' > "$RICH/_ch.txt"
ffmpeg -y -v error -f lavfi -i "testsrc=duration=40:size=640x360:rate=24" \
  -f lavfi -i "sine=frequency=440:duration=40" -f lavfi -i "sine=frequency=880:duration=40" \
  -i "$RICH/_bn.srt" -i "$RICH/_ch.txt" -map 0:v -map 1:a -map 2:a -map 3:s -map_chapters 4 \
  -c:v libx264 -pix_fmt yuv420p -c:a ac3 -c:s srt \
  -metadata:s:a:0 language=ben -metadata:s:a:1 language=eng -metadata:s:s:0 language=ben \
  "$RICH/Dhaka Nights (2024).mkv"
rm "$RICH/_bn.srt" "$RICH/_ch.txt"
printf '1\n00:00:02,000 --> 00:00:05,000\nHello from the side file\n\n' > "$RICH/Dhaka Nights (2024).en.srt"
clip "$OUT/Animation/Avatar The Last Airbender/Book 1/Avatar.S01E01.mp4"

# VP9 + Opus WebM: every browser plays it as it is, including the open-source Chromium
# that the watch-party test drives (it has no H.264).
mkdir -p "$OUT/Animation/Big Garden (2021)"
ffmpeg -y -v error -f lavfi -i "testsrc2=duration=60:size=640x360:rate=24" -f lavfi -i "sine=duration=60" \
  -c:v libvpx-vp9 -b:v 300k -deadline realtime -cpu-used 8 -c:a libopus -shortest "$OUT/Animation/Big Garden (2021)/Big Garden (2021).webm"


# Music, audiobooks, ebooks and comics (needs Python 3 with Pillow: pip install pillow)
python3 "$(dirname "$0")/sample_shelf.py" "$OUT"
echo "Sample media written to $OUT"
