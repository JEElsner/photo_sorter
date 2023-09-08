import json
from typing import Tuple, Dict
from dateutil import parser
from datetime import datetime

from ms_graph import Graph


def sort_photos(graph: Graph, in_path: str, out_path: str):
    in_folder = graph.get_file_id(in_path)
    out_folder = graph.get_file_id(out_path)

    all_files = graph.get_file_children(
        in_folder, select=["name", "id", "file", "photo"]
    )

    subfolder_cache: Dict[str, str] = dict()

    for file in all_files:
        if not should_move(file):
            continue

        dt = get_timestamp(file)
        # Format month and year strings to have leading zeros. If someone
        # manages to find a non-four-digit year, I will be impressed.
        year = f"{dt.year:0>4}"
        month = f"/{dt.month:0>2}"
        subfolder = f"{year}/{month}"

        if not (new_loc := subfolder_cache.get(subfolder, None)):
            new_loc = graph.ensure_path(out_folder, [year, month])
            subfolder_cache[subfolder] = new_loc

        graph.move_file(file["id"], new_loc)


def should_move(json_data: dict, allowed_types=["image", "video"]) -> bool:
    file = json_data.get("file")
    if not file:
        return False

    file_type: str = file.get("mimeType")
    if not file_type:
        return False

    for allowed_type in allowed_types:
        if file_type.startswith(allowed_type):
            return True

    return False


def get_timestamp(json_data: dict) -> datetime:
    if photo := json_data.get("photo"):
        pass

    timestamp = json_data.get("createDateTime")

    if not timestamp:
        # This info might also be missing, but it'll just be none and we'll
        # have no idea to which file the error pertains. But it shouldn't cause
        # any further errors
        name = json_data.get("name")
        id = json_data.get("id")

        raise ValueError("No timestamp found", name, id)

    return parser.parse(timestamp)
