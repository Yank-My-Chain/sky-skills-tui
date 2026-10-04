import pytest

from sky_skills_tui.presentation import split_frontmatter


@pytest.mark.parametrize("closing", ["---", "..."])
def test_frontmatter_is_separate_from_markdown(closing):
    content = (
        "---\nname: skill\ndescription: |\n  First line\n  Second line\n"
        f"{closing}\n\n# Title\n\n---\n"
    )
    metadata, body = split_frontmatter(content)
    assert metadata == "name: skill\ndescription: |\n  First line\n  Second line"
    assert body == "# Title\n\n---\n"


@pytest.mark.parametrize(
    "content", ["# Heading\n\nText", "---\nUnclosed metadata", "---example\ntext\n---"]
)
def test_non_frontmatter_is_preserved(content):
    assert split_frontmatter(content) == ("", content)
