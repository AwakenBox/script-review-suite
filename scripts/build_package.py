"""Synchronize the declared shared core and package both conversation skills."""

from pathlib import Path, PurePosixPath, PureWindowsPath
import argparse
import json
import shutil
import zipfile


VERSION = "0.2.0"
NAMES = ("script-review", "script-review-studio")
SHARED = [
    "references/protocol.md",
    "references/v1-craft.md",
    "references/v2-story.md",
    "references/v3-art.md",
    "references/v4-reach.md",
    "references/conversation.md",
    "references/knowledge-use.md",
    "scripts/score_review.py",
    "scripts/search_knowledge.py",
    "knowledge/index.json",
]


def package_files(source):
    knowledge = source / "knowledge"
    index = json.loads((knowledge / "index.json").read_text(encoding="utf-8-sig"))
    shared = list(SHARED)
    for card in index["cards"]:
        relative = card["path"].replace("\\", "/")
        path = PurePosixPath(relative)
        if path.is_absolute() or PureWindowsPath(relative).drive or ".." in path.parts:
            raise ValueError(f"Invalid knowledge path: {relative}")
        target = (knowledge / relative).resolve()
        if not target.is_relative_to(knowledge.resolve()) or not target.is_file():
            raise ValueError(f"Knowledge card must exist inside knowledge: {relative}")
        shared.append(f"knowledge/{relative}")
    shared = list(dict.fromkeys(shared))
    for relative in ["SKILL.md", "agents/openai.yaml", *shared]:
        path = source / relative
        if not path.is_file():
            raise ValueError(f"Missing resource: {path}")
        path.read_text(encoding="utf-8")
    return shared


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skills-dir", type=Path, default=Path(__file__).resolve().parents[1] / "skills")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parents[1] / "packages")
    args = parser.parse_args()
    skills = args.skills_dir.resolve()
    source, studio = [skills / name for name in NAMES]
    shared = package_files(source)
    for relative in ("SKILL.md", "agents/openai.yaml"):
        (studio / relative).read_text(encoding="utf-8")
    for relative in shared:
        target = studio / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / relative, target)
    runtime_files = ["SKILL.md", "agents/openai.yaml", *shared]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for names, label in [((NAMES[0],), NAMES[0]), ((NAMES[1],), NAMES[1]), (NAMES, "script-review-suite")]:
        output = args.output_dir / f"{label}-{VERSION}.zip"
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in names:
                for relative in runtime_files:
                    archive.write(skills / name / relative, f"{name}/{relative}")
        print(f"{output.resolve()} ({len(names) * len(runtime_files)} files)")


if __name__ == "__main__":
    main()
