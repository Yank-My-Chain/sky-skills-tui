"""Export a deterministic Textual screenshot without npm or user-home mutations."""

import argparse
import asyncio
import json
import os
import tempfile
from pathlib import Path

from textual.widgets import DataTable, Static

from sky_skills_tui.app import SkillsApp
from sky_skills_tui.models import Status
from sky_skills_tui.service import SkillsService


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("assets"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    os.environ.pop("NO_COLOR", None)
    with tempfile.TemporaryDirectory(prefix="sky-preview-") as directory:
        project = Path(directory) / "my-project"
        home = Path(directory) / "home"
        project.mkdir()
        home.mkdir()
        os.environ["XDG_STATE_HOME"] = str(home / ".local/state")
        entries = {}
        for name, source in [
            ("web-design-guidelines", "vercel-labs/agent-skills"),
            ("vercel-react-best-practices", "vercel-labs/agent-skills"),
            ("vercel-composition-patterns", "vercel-labs/agent-skills"),
            ("find-skills", "vercel-labs/skills"),
            ("team-conventions", "acme/engineering-skills"),
            ("legacy-deployment", "acme/engineering-skills"),
        ]:
            entries[name] = {
                "source": source,
                "sourceType": "github",
                "skillPath": f"skills/{name}/SKILL.md",
                "computedHash": "04a2b35fc77df24b5c6f62d3b5f8e4a391304b85a671a858c20668d39e5d0d11",
            }
            folder = project / ".agents/skills" / name
            folder.mkdir(parents=True)
            (folder / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: Practical guidelines for your project.\n---\n\n"
                "# React best practices\n\n"
                "Guidelines for building readable, responsive React applications.\n\n"
                "## When to use this skill\n\n"
                "Use these instructions when writing components, reviewing a change, "
                "or improving page performance.\n\n"
                "## Keep components focused\n\n"
                "- Give each component **one clear responsibility**.\n"
                "- Keep state close to the code that uses it.\n"
                "- Prefer derived values over duplicated state.\n\n"
                "## Load independent data together\n\n"
                "Start independent requests together to avoid unnecessary waiting.\n\n"
                "```tsx\nconst [profile, posts] = await Promise.all([\n"
                "  getProfile(userId),\n  getPosts(userId),\n]);\n```\n\n"
                "## Review checklist\n\n"
                + "\n\n".join(
                    f"### Step {i}\n\nCheck loading, empty and error states." for i in range(1, 9)
                )
            )
        (project / "skills-lock.json").write_text(json.dumps({"version": 1, "skills": entries}))
        app = SkillsApp(SkillsService(project, home=home), bootstrap=False)
        async with app.run_test(size=(140, 42)) as pilot:
            await pilot.pause()
            for skill in app.skills:
                skill.agents = ["Claude Code"]
                skill.status = Status.CURRENT
                skill.reason = "Source folder matches the locked version."
                if skill.name == "vercel-react-best-practices":
                    skill.status = Status.OUTDATED
                    skill.reason = "Source folder differs from the locked version."
                elif skill.name == "legacy-deployment":
                    skill.status = Status.DEPRECATED
                    skill.reason = "Source is readable, but the recorded skill no longer exists."
            app.query_one("#project-path", Static).update("~/projects/my-project")
            app.render_rows()
            row = next(
                i
                for i, s in enumerate(app.visible_skills)
                if s.name == "vercel-react-best-practices"
            )
            app.query_one("#skills", DataTable).move_cursor(row=row)
            app.action_select_source()
            app.activity("npm skills 1.7.0 ready · checked 6 skills across 3 sources")
            app.activity("vercel-react-best-practices: outdated — source folder changed")
            await pilot.pause()
            app.save_screenshot("sky.svg", path=str(args.output))
            await pilot.press("v")
            await pilot.pause()
            app.save_screenshot("skill-preview.svg", path=str(args.output))
            await pilot.press("escape", "u")
            await pilot.pause()
            app.save_screenshot("install-options.svg", path=str(args.output))
            await pilot.press("escape")
            await pilot.resize_terminal(80, 24)
            await pilot.pause()
            app.save_screenshot("compact.svg", path=str(args.output))
            await pilot.press("v", "pagedown")
            await pilot.pause()
            app.save_screenshot("compact-preview.svg", path=str(args.output))


if __name__ == "__main__":
    asyncio.run(main())
