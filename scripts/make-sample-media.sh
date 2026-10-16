#!/usr/bin/env bash
# Makes a small media folder with every kind of category, for trying GharBox or for tests.
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
clip "$OUT/Animation/Avatar The Last Airbender/Book 1/Avatar.S01E01.mp4"
echo "Sample media written to $OUT"
