import re
import shutil
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SKILL_RELATIVE_PATH = Path("skills/tenant-contract-review-cn")


def validate_skill_package(skill_directory: Path) -> list[str]:
    """Return deterministic U1 package errors without trusting package content."""
    errors: list[str] = []
    skill_file = skill_directory / "SKILL.md"
    if not skill_file.is_file():
        return ["SKILL.md is missing"]

    content = skill_file.read_text(encoding="utf-8")
    if len(content.splitlines()) > 500:
        errors.append("SKILL.md exceeds 500 lines")

    frontmatter_match = re.match(r"\A---\n(.*?)\n---(?:\n|\Z)", content, re.DOTALL)
    if not frontmatter_match:
        errors.append("SKILL.md frontmatter is missing or malformed")
    else:
        keys = {
            match.group(1)
            for line in frontmatter_match.group(1).splitlines()
            if (match := re.match(r"^([A-Za-z0-9_-]+):", line))
        }
        if keys != {"name", "description"}:
            errors.append("SKILL.md frontmatter must contain only name and description")

    for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", content):
        clean_target = target.split("#", 1)[0]
        if not clean_target or re.match(r"^[a-z][a-z0-9+.-]*:", clean_target):
            continue
        if not (skill_directory / clean_target).resolve().is_file():
            errors.append(f"SKILL.md references missing file: {clean_target}")

    metadata_file = skill_directory / "agents/openai.yaml"
    if not metadata_file.is_file():
        errors.append("agents/openai.yaml is missing")
    else:
        metadata = metadata_file.read_text(encoding="utf-8")
        if "$tenant-contract-review-cn" not in metadata:
            errors.append("default_prompt must mention $tenant-contract-review-cn")

    return errors


def validate_repository(repository_root: Path) -> list[str]:
    errors = []
    for filename in ("README.md", "LICENSE", "SECURITY.md", "CONTRIBUTING.md", ".gitignore"):
        if not (repository_root / filename).is_file():
            errors.append(f"repository file is missing: {filename}")

    skill_directory = repository_root / SKILL_RELATIVE_PATH
    errors.extend(validate_skill_package(skill_directory))
    for noisy_name in ("README.md", "INSTALLATION_GUIDE.md", "CHANGELOG.md"):
        if (skill_directory / noisy_name).exists():
            errors.append(f"repository-only documentation found in Skill package: {noisy_name}")
    return errors


class PublicationSafetyTests(unittest.TestCase):
    def copy_skill(self) -> tuple[tempfile.TemporaryDirectory, Path]:
        temporary_directory = tempfile.TemporaryDirectory()
        copied_skill = Path(temporary_directory.name) / "tenant-contract-review-cn"
        shutil.copytree(REPOSITORY_ROOT / SKILL_RELATIVE_PATH, copied_skill)
        return temporary_directory, copied_skill

    def test_repository_and_installable_package_are_separated(self) -> None:
        self.assertEqual([], validate_repository(REPOSITORY_ROOT))

    def test_skill_rejects_unknown_frontmatter_field(self) -> None:
        temporary_directory, copied_skill = self.copy_skill()
        self.addCleanup(temporary_directory.cleanup)
        skill_file = copied_skill / "SKILL.md"
        content = skill_file.read_text(encoding="utf-8")
        skill_file.write_text(content.replace("---\n\n#", "license: MIT\n---\n\n#", 1), encoding="utf-8")
        self.assertIn(
            "SKILL.md frontmatter must contain only name and description",
            validate_skill_package(copied_skill),
        )

    def test_skill_rejects_more_than_500_lines(self) -> None:
        temporary_directory, copied_skill = self.copy_skill()
        self.addCleanup(temporary_directory.cleanup)
        skill_file = copied_skill / "SKILL.md"
        skill_file.write_text("---\nname: tenant-contract-review-cn\ndescription: test\n---\n" + "line\n" * 497, encoding="utf-8")
        self.assertIn("SKILL.md exceeds 500 lines", validate_skill_package(copied_skill))

    def test_skill_rejects_missing_relative_reference(self) -> None:
        temporary_directory, copied_skill = self.copy_skill()
        self.addCleanup(temporary_directory.cleanup)
        skill_file = copied_skill / "SKILL.md"
        content = skill_file.read_text(encoding="utf-8")
        skill_file.write_text(content + "\n[Missing](references/missing.md)\n", encoding="utf-8")
        self.assertIn(
            "SKILL.md references missing file: references/missing.md",
            validate_skill_package(copied_skill),
        )

    def test_metadata_default_prompt_names_the_skill(self) -> None:
        temporary_directory, copied_skill = self.copy_skill()
        self.addCleanup(temporary_directory.cleanup)
        metadata_file = copied_skill / "agents/openai.yaml"
        self.assertTrue(metadata_file.is_file(), "agents/openai.yaml must exist before mutation")
        metadata = metadata_file.read_text(encoding="utf-8")
        metadata_file.write_text(metadata.replace("$tenant-contract-review-cn", "the skill"), encoding="utf-8")
        self.assertIn(
            "default_prompt must mention $tenant-contract-review-cn",
            validate_skill_package(copied_skill),
        )


if __name__ == "__main__":
    unittest.main()
