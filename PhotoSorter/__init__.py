from . import _version

__version__ = _version.get_versions()["version"]


import logging as __logging


__logging.basicConfig(
    filename="photo-sorter.log",
    level=__logging.DEBUG,
    filemode="w",
    format="%(asctime)s\t%(levelname)s\t%(name)s\t%(message)s",
)

from . import ms_graph
from . import photo_sorter, drive_sorter
