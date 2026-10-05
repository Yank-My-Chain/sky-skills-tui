"""Display helpers that leave installed skill files untouched."""

import re

from rich.console import Console, ConsoleOptions, RenderResult
from rich.markdown import Heading, Markdown


class SkillHeading(Heading):
    """Keep preview headings aligned with the text and the app's foreground color."""

    def __init__(self, tag: str) -> None:
        super().__init__(tag)
        self.style_name = "bold"

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        text = self.text.copy()
        text.justify = "left"
        yield text


class SkillMarkdown(Markdown):
    elements = {**Markdown.elements, "heading_open": SkillHeading}


def split_frontmatter(content: str) -> tuple[str, str]:
    """Keep YAML out of Markdown, where it would be parsed as a setext heading."""
    match = re.match(r"\A\ufeff?---[^\S\n]*\n(.*?)\n(?:---|\.\.\.)[^\S\n]*(?:\n|\Z)", content, re.S)
    if match:
        return match[1], content[match.end() :].lstrip("\n")
    return "", content
