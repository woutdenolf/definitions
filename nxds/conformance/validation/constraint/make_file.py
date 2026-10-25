"""NXcase_require with neither mu nor fluo."""

import sys

from _common import entry_file
from _common import group

root, entry = entry_file(sys.argv[1], "NXcase_require")
group(entry, "data", "NXdata")
root.close()
