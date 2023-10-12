# Load version
from . import _version

__version__ = _version.get_versions()["version"]

# Set up logging
import logging as __logging
import sys as __sys

__logging.basicConfig(
    filename="photo-sorter.log",
    level=__logging.DEBUG,
    filemode="w",
    format="%(asctime)s\t%(levelname)s\t%(name)s\t%(message)s",
)

__stdout_logger = __logging.StreamHandler(stream=__sys.stdout)
__stdout_logger.setLevel(__logging.INFO)
__stdout_logger.setFormatter(__logging.Formatter("%(message)s"))

main_log = __logging.getLogger("")
main_log.addHandler(__stdout_logger)
