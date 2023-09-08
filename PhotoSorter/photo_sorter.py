from PIL import Image, ExifTags
from pathlib import Path
import logging
import shutil
import os

logging.basicConfig(
    filename="log.txt", encoding="utf-8", level=logging.WARNING, filemode="w"
)


def move_photos(source: Path, out: Path, max_files=float("inf")):
    if not source.exists():
        raise ValueError("source path does not exist")
    if not out.exists():
        raise ValueError("out path does not exist")

    if not source.is_dir():
        raise ValueError("source path is not a directory")
    if not out.is_dir():
        raise ValueError("out path is not a directory")

    for i, file in enumerate(source.iterdir()):
        if i % 1000 == 0:
            print(f"Moved {i} files")

        if i > max_files:
            logging.info(f"Maximum files ({max_files}) reached. Stopping")
            break

        if not file.is_file():
            logging.info(f"Skipping {file.name}: not a file")
            continue

        if file.name.endswith(".mp4"):
            logging.info(f"Skipping {file.name}: mp4")
            continue

        try:
            image = Image.open(file)
        except OSError as err:
            logging.warning(f"Skipping {file.name}: PIL failed to open image")
            # logging.warning(f"{err}")
            continue

        try:
            exif_data = image.getexif()
        except Exception as err:
            logging.warning(f"Skipping {file.name}: Unable to retrieve EXIF data")
            continue

        # Exif.Image.DateTime, hex: 0x0132, dec: 306
        timestamp = exif_data.get(ExifTags.Base.DateTime)

        # Try something else if the timestamp doesn't exist
        if not timestamp:
            # Exif.Photo.DateTimeOriginal, hex: 0x9003, dec: 36867
            timestamp = exif_data.get_ifd(ExifTags.IFD.Exif).get(
                ExifTags.Base.DateTimeOriginal
            )

        if not timestamp:
            logging.warning(f"Skipping {file.name}: Unable to retrieve timestamp")

        try:
            date, time = timestamp.split(" ")
            year, month, day = date.split(":")
        except Exception as err:
            logging.warning(f"Skipping {file.name}: Unable to parse timestamp")

        image.close()
        filename = file.name

        logging.debug(f"Moving {filename}, date: {year}-{month}")

        out_dir = out / f"{year}" / f"{month}"

        if not out_dir.exists():
            logging.debug(f"Creating output directory {year}/{month}")
            os.makedirs(out_dir)
        if (out_dir / file.name).exists():
            logging.warning(f"Skipping {filename}: already exists at out directory")

        try:
            shutil.move(file, out_dir)
        except Exception as err:
            logging.error(f"Failed to move file {filename}. Skipping.")
            logging.error(f"{err}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        prog="photo_sorter",
    )

    parser.add_argument("in_dir", action="store")
    parser.add_argument("out_dir", action="store")
    parser.add_argument("-m", "--max-files", action="store")

    args = parser.parse_args()

    source = Path(args.in_dir)
    out = Path(args.out_dir)

    if args.max_files:
        max_files = int(args.max_files)
    else:
        max_files = float("inf")

    move_photos(source, out, max_files)
