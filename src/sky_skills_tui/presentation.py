"""Display helpers that leave installed skill files untouched."""

import io
import re
import time
from collections.abc import Iterator

from rich.console import Console, ConsoleOptions, RenderResult
from rich.markdown import Heading, Markdown
from rich.measure import Measurement
from rich.segment import Segment
from rich.text import Text


def shortcut_label(label: str, key: str) -> Text:
    """Underline a key in the wording, with separate hints only for special keys."""
    text = Text(label)
    offset = label.casefold().find(key.casefold())
    if offset < 0:
        if len(key) == 1 and key.isalpha():
            raise ValueError(f"Letter shortcut {key!r} must appear in label {label!r}")
        text.append(" · ")
        text.append(key.upper(), style="underline")
    else:
        text.stylize("underline", offset, offset + len(key))
    return text


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


class RenderedMarkdown:
    """SKILL.md rendered ahead of time at a fixed width, so redraws only replay lines.

    Rich Markdown with syntax-highlighted code can take a second for long skills, and
    Textual would otherwise repeat that work for every layout. Rendering happens in
    short slices on the event loop (a thread would contend for the GIL and stall
    input just the same), so keys stay responsive while a long preview renders.
    """

    def __init__(self, markdown: SkillMarkdown, width: int) -> None:
        self.markdown = markdown
        self.width = width
        self.lines: list[list[Segment]] = []
        console = Console(
            file=io.StringIO(),
            width=width,
            force_terminal=True,
            color_system="truecolor",
            legacy_windows=False,
            emoji=False,
            highlight=False,
            safe_box=False,
            _environ={},
        )
        lines = Segment.split_and_crop_lines(
            console.render(markdown, console.options), width, include_new_lines=False, pad=False
        )
        self._pending: Iterator[list[Segment]] | None = iter(lines)

    def render_for(self, seconds: float) -> bool:
        """Render more lines for roughly `seconds`; return True once complete."""
        if self._pending is None:
            return True
        deadline = time.perf_counter() + seconds
        for line in self._pending:
            self.lines.append(line)
            if time.perf_counter() >= deadline:
                return False
        self._pending = None
        return True

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        new_line = Segment.line()
        for line in self.lines:
            yield from line
            yield new_line

    def __rich_measure__(self, console: Console, options: ConsoleOptions) -> Measurement:
        return Measurement(1, self.width)


def split_frontmatter(content: str) -> tuple[str, str]:
    """Keep YAML out of Markdown, where it would be parsed as a setext heading."""
    match = re.match(r"\A\ufeff?---[^\S\n]*\n(.*?)\n(?:---|\.\.\.)[^\S\n]*(?:\n|\Z)", content, re.S)
    if match:
        return match[1], content[match.end() :].lstrip("\n")
    return "", content
