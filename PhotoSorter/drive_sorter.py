import json
from typing import Tuple, Dict
from dateutil import parser
from datetime import datetime

from .ms_graph import Graph, BatchMoveQueue
from . import main_log

logging = main_log.getChild(__name__)

REPORT_PERIOD = 50
"""How often to log how many files were checked"""


def sort_photos(graph: Graph, in_path: str, out_path: str):
    """Sort photos using the Microsoft Graph API

    Args:
        graph: The Graph API instance referencing the OneDrive with the photos
        in_path: The human-readable path from the OneDrive root to the photos
            that will be sorted.
        out_path: The human-readable path from the OneDrive root to the
        top-level destination folder for the newly sorted photos and the folder
        hierarchy by which they are sorted. Can be the same as ``in_path``.
    """
    in_folder = graph.get_file_id(in_path)
    out_folder = graph.get_file_id(out_path)

    all_files = graph.get_file_children(
        in_folder, select=["name", "id", "file", "photo", "createdDateTime"]
    )

    subfolder_cache: Dict[str, str] = dict()

    batch_mover = BatchMoveQueue(graph)
    batch_mover.start()

    moved = 0

    for i, file in enumerate(all_files):
        if i % REPORT_PERIOD == 0 and i != 0:
            logging.info(f"{i} files examined")

        if not should_move(file):
            continue

        try:
            dt = get_timestamp(file)
        except ValueError:
            continue

        # Format month and year strings to have leading zeros. If someone
        # manages to find a non-four-digit year, I will be impressed.
        year = f"{dt.year:0>4}"
        month = f"{dt.month:0>2}"
        subfolder = f"{year}/{month}"

        if not (new_loc := subfolder_cache.get(subfolder, None)):
            logging.debug(f"Ensuring path\t{subfolder}")

            new_loc = graph.ensure_path(out_folder, [year, month])
            subfolder_cache[subfolder] = new_loc

        logging.debug(f"Creating Move task\t{file['id']}")

        batch_mover.put(file["id"], new_loc)
        moved += 1

    batch_mover.done_adding()
    logging.info("Done adding move tasks")

    batch_mover.join()
    logging.info("Moves complete")

    logging.info(f"Sortation complete. {i} files processed, {moved} files moved.")


def should_move(json_data: dict, allowed_types=["image", "video"]) -> bool:
    """Looks at a file object and determines whether it can and should be
    sorted.

    Args:
        json_data: The attributes of the file
        allowed_types: The file types that will be sorted"""

    file = json_data.get("file")
    if not file:
        # File is not a file (i.e. a folder), do not move
        return False

    file_type: str = file.get("mimeType")
    if not file_type:
        # File does not have a mime-type, so it probably shouldn't be moved
        return False

    for allowed_type in allowed_types:
        if file_type.startswith(allowed_type):
            # We want to move this file
            return True

    return False


def get_timestamp(json_data: dict) -> datetime:
    """Try to get an accurate timestamp of when the photo was taken from the
    file metadata.

    If a photo does not have metadata pertaining explicitly to when the photo
    was taken, other date information (such as when the file was created) is
    arbitrary, and may not be related to the image capture date, so this
    function is conservative and ignores that data.

    Args:
        json_data: The file metadata, as JSON

    Returns:
        A datetime object describing when the photo was taken

    Raises:
        ValueError:
            If no timestamp can be found for the file.
    """
    timestamp = None
    if photo := json_data.get("photo"):
        timestamp = photo.get("takenDateTime")
    else:
        # I think the line below is for if we want to accept the created time
        # as the time the photo was taken for all files. Uncomment it if you
        # want to find a timestamp for more files (at the sacrifice of
        # timestamp accuracy)
        #
        # timestamp = json_data.get("createdDateTime")
        pass

    if not timestamp:
        # This info might also be missing, but it'll just be none and we'll
        # have no idea to which file the error pertains. But it shouldn't cause
        # any further errors
        name = json_data.get("name")
        id = json_data.get("id")

        raise ValueError("No timestamp found", name, id)

    return parser.parse(timestamp)
