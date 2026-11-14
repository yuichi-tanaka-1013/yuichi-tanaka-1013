"""Shared helpers for the SVG tests.

external_references() is the check behind the project's main rule: an SVG must
not make the viewer's browser ask anything outside GitHub.
"""

import re

# Split in two parts on purpose: a repo-wide grep for the URL scheme then lists
# only real URLs and xmlns declarations, not the words these checks look for.
HTTP = "ht" + "tp"
XMLNS = f'xmlns="{HTTP}://www.w3.org/2000/svg"'


def local(tag: str) -> str:
    """'{namespace}name' -> 'name'."""
    return tag.rsplit("}", 1)[-1]


def find_all(root, name: str) -> list:
    """Every element called `name`, whatever its namespace."""
    return [element for element in root.iter() if local(element.tag) == name]


def external_references(svg: str) -> list[str]:
    """Return a description of every external reference found in the SVG text.

    The SVG namespace declaration is the only allowed URL. Links, imports,
    fonts, scripts and url() other than url(#id) are all refused.
    """
    found = []
    text = svg.replace(XMLNS, "")
    if HTTP in text.lower():
        found.append(HTTP)
    checks = {
        "href": r"href",
        "xlink": r"xlink",
        "@import": r"@import",
        "@font-face": r"@font-face",
        "script": r"<script",
        "url() that is not #id": r"url\(\s*['\"]?(?!#)",
    }
    for label, pattern in checks.items():
        if re.search(pattern, text, flags=re.IGNORECASE):
            found.append(label)
    return found
