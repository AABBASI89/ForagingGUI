# config_writer.py
#
# Overwrites simple `NAME = value` assignments in config.py in place.
# Comments, other lines and the file's line endings are preserved.

import json
import os
import re


def format_value(value):

    if isinstance(value, bool):
        return repr(value)

    if isinstance(value, str):
        return json.dumps(value)

    if isinstance(value, float):
        return repr(round(value, 6))

    return repr(value)


def update_config_file(path, values):
    """
    values: dict NAME -> new value.

    Raises KeyError (and writes nothing) if any NAME has no
    top-level assignment in the file.
    """

    with open(path, "r", newline="", encoding="utf-8") as f:
        text = f.read()

    for name, value in values.items():

        #
        # NAME = <old value>   [# optional inline comment]
        #
        pattern = re.compile(
            rf"^(?P<head>{re.escape(name)}[ \t]*=[ \t]*)"
            rf"(?P<old>[^#\r\n]*?)"
            rf"(?P<tail>[ \t]*#[^\r\n]*)?$",
            re.MULTILINE
        )

        new_text, count = pattern.subn(
            lambda m: (
                m.group("head")
                + format_value(value)
                + (m.group("tail") or "")
            ),
            text,
            count=1
        )

        if count == 0:

            raise KeyError(
                f"{name} not found in {os.path.basename(path)}"
            )

        text = new_text

    #
    # Write to a temp file, then replace, so a failure
    # cannot leave a half-written config.py
    #
    tmp = path + ".tmp"

    with open(tmp, "w", newline="", encoding="utf-8") as f:
        f.write(text)

    os.replace(tmp, path)
