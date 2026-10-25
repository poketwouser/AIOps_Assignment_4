"""Builds the test inputs from COCO val2017 (http://images.cocodataset.org/zips/val2017.zip).

    python make_test_zips.py ~/Desktop/datasets/coco_val2017/val2017

Writes to test_data/:
  single/            6 images for the Single tab
  bulk_20.zip  bulk_50.zip  bulk_100.zip      random COCO images
  bulk_dirty.zip     10 good images + a corrupt jpg, a truncated jpg, a .txt,
                     macOS metadata and a hidden file (checks the error paths)
  not_a_zip.zip      a text file with a .zip name

Images are re-saved at JPEG quality 80 so the ZIPs stay under 10 MB.
"""
import io
import random
import shutil
import sys
import zipfile
from pathlib import Path

from PIL import Image

SEED = 3408
OUT = Path(__file__).parent / "test_data"


def jpeg_bytes(path):
    buf = io.BytesIO()
    Image.open(path).convert("RGB").save(buf, "JPEG", quality=80)
    return buf.getvalue()


def write_zip(name, files):
    with zipfile.ZipFile(OUT / name, "w", zipfile.ZIP_DEFLATED) as zf:
        for arcname, data in files:
            zf.writestr(arcname, data)
    size = (OUT / name).stat().st_size / 1e6
    print(f"{name:16} {len(files):4} entries  {size:5.1f} MB")


def main(coco_dir):
    images = sorted(Path(coco_dir).glob("*.jpg"))
    random.Random(SEED).shuffle(images)
    shutil.rmtree(OUT, ignore_errors=True)
    (OUT / "single").mkdir(parents=True)

    for p in images[:6]:
        shutil.copy(p, OUT / "single" / p.name)
    print(f"single/          6 images")

    pool = images[6:]
    for n in (20, 50, 100):
        write_zip(f"bulk_{n}.zip", [(f"bulk_{n}/{p.name}", jpeg_bytes(p)) for p in pool[:n]])
        pool = pool[n:]

    good = [(f"photos/{p.name}", jpeg_bytes(p)) for p in pool[:10]]
    whole = jpeg_bytes(pool[10])
    dirty = good + [
        ("photos/corrupt.jpg", bytes(random.Random(SEED).getrandbits(8) for _ in range(5000))),
        ("photos/truncated.jpg", whole[: len(whole) // 3]),
        ("photos/notes.txt", b"not an image"),
        ("__MACOSX/photos/._" + pool[0].name, b"\x00\x05\x16\x07"),
        ("photos/.DS_Store", b"\x00\x00\x00\x01Bud1"),
    ]
    write_zip("bulk_dirty.zip", dirty)
    (OUT / "not_a_zip.zip").write_text("this is a text file pretending to be a zip\n")
    print("not_a_zip.zip    text file")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else Path.home() / "Desktop/datasets/coco_val2017/val2017")
