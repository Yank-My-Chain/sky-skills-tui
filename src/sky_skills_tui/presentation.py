"""Display helpers that leave installed skill files untouched."""

import re


def split_frontmatter(content: str) -> tuple[str, str]:
    """Keep YAML out of Markdown, where it would be parsed as a setext heading."""
    match = re.match(r"\A\ufeff?---[^\S\n]*\n(.*?)\n(?:---|\.\.\.)[^\S\n]*(?:\n|\Z)", content, re.S)
    if match:
        return match[1], content[match.end() :].lstrip("\n")
    return "", content
