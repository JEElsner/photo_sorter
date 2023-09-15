from . import __version__
from datetime import datetime


def sort_on_disk():
    from pathlib import Path
    from . import photo_sorter

    in_path = input("Photos Location: ")
    out_path = input("Sorted Location: ")

    photo_sorter.move_photos(Path(in_path), Path(out_path))


def sort_on_onedrive():
    from . import drive_sorter
    from .ms_graph import Graph
    import json

    with open("./auth.json", mode="r") as f:
        auth_info = json.load(f)
        graph = Graph(auth_info["clientId"], auth_info["tenantId"], auth_info["scopes"])

    in_path = input(
        "Enter path to photos from root. e.g. if the photos are located at root:/Pictures/Camera Roll, enter /Pictures/Camera Roll.\n> "
    )
    out_path = input("Enter output location for sorted photos.\n> ")

    print("Beginning sorting")
    start = datetime.now()

    drive_sorter.sort_photos(graph, in_path, out_path)

    end = datetime.now()
    print("Sorting finished")
    print(f"Total requests: {graph.total_requests_made}")

    delta = end - start
    print(f"Duration: {delta}")


print(f"PhotoSorter version {__version__}")

print(f"0 - Sort Photos on local disk\n1 - Sort Photos on OneDrive")
while True:
    try:
        choice = int(input("> "))
        if choice not in [0, 1]:
            raise ValueError()
        break
    except ValueError:
        print("Invalid choice")


if choice == 0:
    sort_on_disk()
else:
    sort_on_onedrive()
