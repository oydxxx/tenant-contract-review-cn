import re
import shutil
import tempfile
import unittest
import importlib.util
from pathlib import Path
from urllib.parse import unquote

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SKILL_RELATIVE_PATH = Path("skills/tenant-contract-review-cn")
ALLOWED_REMOTE_REFERENCE_SCHEMES = {"http", "https", "mailto"}
PUBLICATION_SCRIPT = REPOSITORY_ROOT / "skills/tenant-contract-review-cn/scripts/validate_publication.py"
PUBLICATION_SPEC = importlib.util.spec_from_file_location("validate_publication", PUBLICATION_SCRIPT)
assert PUBLICATION_SPEC and PUBLICATION_SPEC.loader
validate_publication = importlib.util.module_from_spec(PUBLICATION_SPEC)
PUBLICATION_SPEC.loader.exec_module(validate_publication)


class DuplicateKeyError(yaml.YAMLError):
    def __init__(self, key: object) -> None:
        super().__init__(str(key))
        self.key = key


class DuplicateRejectingSafeLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects ambiguous mapping keys."""


def _construct_unique_mapping(
    loader: DuplicateRejectingSafeLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[object, object]:
    loader.flatten_mapping(node)
    mapping: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as error:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable key",
                key_node.start_mark,
            ) from error
        if duplicate:
            raise DuplicateKeyError(key)
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


DuplicateRejectingSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _load_yaml_document(document: str) -> object:
    return yaml.load(document, Loader=DuplicateRejectingSafeLoader)


def _markdown_reference_destinations(content: str) -> list[str]:
    destinations: list[str] = []
    inline_pattern = re.compile(
        r"!?\[[^\]\n]*\]\(\s*(?:<(?P<angle>[^>\n]*)>|(?P<plain>[^\s)\n]+))"
        r"(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))?\s*\)"
    )
    definition_pattern = re.compile(
        r"^[ \t]{0,3}\[[^\]\n]+\]:[ \t]*(?:<(?P<angle>[^>\n]*)>|(?P<plain>\S+))",
        re.MULTILINE,
    )
    for pattern in (inline_pattern, definition_pattern):
        for match in pattern.finditer(content):
            destinations.append(match.group("angle") if match.group("angle") is not None else match.group("plain"))
    return destinations


def validate_skill_package(skill_directory: Path) -> list[str]:
    """Return deterministic U1 package errors without trusting package content."""
    errors: list[str] = []
    package_root = skill_directory.resolve()
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
        try:
            frontmatter = _load_yaml_document(frontmatter_match.group(1))
        except DuplicateKeyError as error:
            errors.append(f"SKILL.md frontmatter contains duplicate key: {error.key}")
        except yaml.YAMLError:
            errors.append("SKILL.md frontmatter YAML is invalid")
        else:
            if not isinstance(frontmatter, dict) or set(frontmatter) != {"name", "description"}:
                errors.append("SKILL.md frontmatter must contain only name and description")
            if not isinstance(frontmatter, dict) or frontmatter.get("name") != skill_directory.name:
                errors.append("SKILL.md frontmatter name must match skill directory")
            description = frontmatter.get("description") if isinstance(frontmatter, dict) else None
            if not isinstance(description, str) or not description.strip():
                errors.append("SKILL.md frontmatter description must be a non-empty string")

    for target in _markdown_reference_destinations(content):
        if not target or target.startswith("#"):
            continue
        path_without_fragment = target.split("#", 1)[0]
        decoded_target = unquote(path_without_fragment)
        scheme_match = re.match(r"^([A-Za-z][A-Za-z0-9+.-]*):", decoded_target)
        if scheme_match:
            if scheme_match.group(1).lower() in ALLOWED_REMOTE_REFERENCE_SCHEMES:
                continue
            errors.append(f"SKILL.md reference uses disallowed scheme: {target}")
            continue
        if not decoded_target:
            continue
        reference_path = Path(decoded_target)
        resolved_target = (package_root / reference_path).resolve()
        if reference_path.is_absolute() or not resolved_target.is_relative_to(package_root):
            errors.append(f"SKILL.md reference escapes package: {target}")
        elif not resolved_target.is_file():
            errors.append(f"SKILL.md references missing file: {decoded_target}")

    metadata_file = skill_directory / "agents/openai.yaml"
    if not metadata_file.is_file():
        errors.append("agents/openai.yaml is missing")
    else:
        try:
            metadata = _load_yaml_document(metadata_file.read_text(encoding="utf-8"))
        except DuplicateKeyError as error:
            errors.append(f"agents/openai.yaml contains duplicate key: {error.key}")
        except yaml.YAMLError:
            errors.append("agents/openai.yaml YAML is invalid")
        else:
            interface = metadata.get("interface") if isinstance(metadata, dict) else None
            if not isinstance(interface, dict):
                errors.append("agents/openai.yaml interface must be a mapping")
            else:
                for field in ("display_name", "short_description", "default_prompt"):
                    value = interface.get(field)
                    if not isinstance(value, str) or not value.strip():
                        errors.append(f"agents/openai.yaml interface.{field} must be a non-empty string")
                prompt = interface.get("default_prompt")
                if isinstance(prompt, str) and prompt.strip() and "$tenant-contract-review-cn" not in prompt:
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

    def test_skill_rejects_quoted_unknown_frontmatter_field(self) -> None:
        temporary_directory, copied_skill = self.copy_skill()
        self.addCleanup(temporary_directory.cleanup)
        skill_file = copied_skill / "SKILL.md"
        content = skill_file.read_text(encoding="utf-8")
        skill_file.write_text(content.replace("---\n\n#", '"license": MIT\n---\n\n#', 1), encoding="utf-8")
        self.assertIn(
            "SKILL.md frontmatter must contain only name and description",
            validate_skill_package(copied_skill),
        )

    def test_skill_rejects_wrong_frontmatter_name(self) -> None:
        temporary_directory, copied_skill = self.copy_skill()
        self.addCleanup(temporary_directory.cleanup)
        skill_file = copied_skill / "SKILL.md"
        content = skill_file.read_text(encoding="utf-8")
        skill_file.write_text(
            content.replace("name: tenant-contract-review-cn", "name: different-skill", 1),
            encoding="utf-8",
        )
        self.assertIn(
            "SKILL.md frontmatter name must match skill directory",
            validate_skill_package(copied_skill),
        )

    def test_skill_rejects_duplicate_frontmatter_key(self) -> None:
        temporary_directory, copied_skill = self.copy_skill()
        self.addCleanup(temporary_directory.cleanup)
        skill_file = copied_skill / "SKILL.md"
        content = skill_file.read_text(encoding="utf-8")
        skill_file.write_text(
            content.replace(
                "name: tenant-contract-review-cn",
                "name: tenant-contract-review-cn\nname: different-skill",
                1,
            ),
            encoding="utf-8",
        )
        self.assertIn("SKILL.md frontmatter contains duplicate key: name", validate_skill_package(copied_skill))

    def test_skill_rejects_malformed_frontmatter_yaml(self) -> None:
        temporary_directory, copied_skill = self.copy_skill()
        self.addCleanup(temporary_directory.cleanup)
        skill_file = copied_skill / "SKILL.md"
        content = skill_file.read_text(encoding="utf-8")
        skill_file.write_text(
            content.replace("name: tenant-contract-review-cn", "name: [tenant-contract-review-cn", 1),
            encoding="utf-8",
        )
        self.assertIn("SKILL.md frontmatter YAML is invalid", validate_skill_package(copied_skill))

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

    def test_skill_rejects_reference_outside_package(self) -> None:
        temporary_directory, copied_skill = self.copy_skill()
        self.addCleanup(temporary_directory.cleanup)
        outside_file = copied_skill.parent / "outside.md"
        outside_file.write_text("outside package\n", encoding="utf-8")
        skill_file = copied_skill / "SKILL.md"
        content = skill_file.read_text(encoding="utf-8")
        skill_file.write_text(content + "\n[Outside](../outside.md)\n", encoding="utf-8")
        self.assertIn(
            "SKILL.md reference escapes package: ../outside.md",
            validate_skill_package(copied_skill),
        )

    def test_skill_rejects_missing_reference_definition_destination(self) -> None:
        temporary_directory, copied_skill = self.copy_skill()
        self.addCleanup(temporary_directory.cleanup)
        skill_file = copied_skill / "SKILL.md"
        content = skill_file.read_text(encoding="utf-8")
        skill_file.write_text(
            content + "\n[Missing][missing]\n\n[missing]: references/missing.md\n",
            encoding="utf-8",
        )
        self.assertIn(
            "SKILL.md references missing file: references/missing.md",
            validate_skill_package(copied_skill),
        )

    def test_skill_rejects_escaping_reference_definition_destination(self) -> None:
        temporary_directory, copied_skill = self.copy_skill()
        self.addCleanup(temporary_directory.cleanup)
        outside_file = copied_skill.parent / "outside.md"
        outside_file.write_text("outside package\n", encoding="utf-8")
        skill_file = copied_skill / "SKILL.md"
        content = skill_file.read_text(encoding="utf-8")
        skill_file.write_text(content + "\n[Outside][outside]\n\n[outside]: ../outside.md\n", encoding="utf-8")
        self.assertIn(
            "SKILL.md reference escapes package: ../outside.md",
            validate_skill_package(copied_skill),
        )

    def test_skill_rejects_file_uri_reference(self) -> None:
        temporary_directory, copied_skill = self.copy_skill()
        self.addCleanup(temporary_directory.cleanup)
        skill_file = copied_skill / "SKILL.md"
        content = skill_file.read_text(encoding="utf-8")
        skill_file.write_text(content + "\n[Local](file:///tmp/outside.md)\n", encoding="utf-8")
        self.assertIn(
            "SKILL.md reference uses disallowed scheme: file:///tmp/outside.md",
            validate_skill_package(copied_skill),
        )

    def test_skill_rejects_encoded_traversal_reference(self) -> None:
        temporary_directory, copied_skill = self.copy_skill()
        self.addCleanup(temporary_directory.cleanup)
        outside_file = copied_skill.parent / "outside.md"
        outside_file.write_text("outside package\n", encoding="utf-8")
        skill_file = copied_skill / "SKILL.md"
        content = skill_file.read_text(encoding="utf-8")
        skill_file.write_text(content + "\n[Outside](%2e%2e/outside.md)\n", encoding="utf-8")
        self.assertIn(
            "SKILL.md reference escapes package: %2e%2e/outside.md",
            validate_skill_package(copied_skill),
        )

    def test_skill_rejects_missing_angle_bracket_destination(self) -> None:
        temporary_directory, copied_skill = self.copy_skill()
        self.addCleanup(temporary_directory.cleanup)
        skill_file = copied_skill / "SKILL.md"
        content = skill_file.read_text(encoding="utf-8")
        skill_file.write_text(content + "\n[Missing](<references/missing file.md>)\n", encoding="utf-8")
        self.assertIn(
            "SKILL.md references missing file: references/missing file.md",
            validate_skill_package(copied_skill),
        )

    def test_skill_rejects_symlink_reference_escape(self) -> None:
        temporary_directory, copied_skill = self.copy_skill()
        self.addCleanup(temporary_directory.cleanup)
        outside_file = copied_skill.parent / "outside.md"
        outside_file.write_text("outside package\n", encoding="utf-8")
        link_path = copied_skill / "references" / "outside-link.md"
        link_path.parent.mkdir(exist_ok=True)
        link_path.symlink_to(outside_file)
        skill_file = copied_skill / "SKILL.md"
        content = skill_file.read_text(encoding="utf-8")
        skill_file.write_text(content + "\n[Outside](references/outside-link.md)\n", encoding="utf-8")
        self.assertIn(
            "SKILL.md reference escapes package: references/outside-link.md",
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

    def test_metadata_token_in_comment_does_not_satisfy_default_prompt(self) -> None:
        temporary_directory, copied_skill = self.copy_skill()
        self.addCleanup(temporary_directory.cleanup)
        metadata_file = copied_skill / "agents/openai.yaml"
        metadata = metadata_file.read_text(encoding="utf-8")
        metadata = metadata.replace("$tenant-contract-review-cn", "the skill")
        metadata_file.write_text(metadata + "# $tenant-contract-review-cn\n", encoding="utf-8")
        self.assertIn(
            "default_prompt must mention $tenant-contract-review-cn",
            validate_skill_package(copied_skill),
        )

    def test_metadata_rejects_duplicate_yaml_key(self) -> None:
        temporary_directory, copied_skill = self.copy_skill()
        self.addCleanup(temporary_directory.cleanup)
        metadata_file = copied_skill / "agents/openai.yaml"
        metadata = metadata_file.read_text(encoding="utf-8")
        metadata_file.write_text(
            metadata.replace(
                '  display_name: "中国大陆租房合同审查"',
                '  display_name: "中国大陆租房合同审查"\n  display_name: "decoy"',
                1,
            ),
            encoding="utf-8",
        )
        self.assertIn("agents/openai.yaml contains duplicate key: display_name", validate_skill_package(copied_skill))

    def test_metadata_rejects_malformed_yaml(self) -> None:
        temporary_directory, copied_skill = self.copy_skill()
        self.addCleanup(temporary_directory.cleanup)
        metadata_file = copied_skill / "agents/openai.yaml"
        metadata_file.write_text("interface: [\n", encoding="utf-8")
        self.assertIn("agents/openai.yaml YAML is invalid", validate_skill_package(copied_skill))

    def test_metadata_requires_non_empty_interface_fields(self) -> None:
        temporary_directory, copied_skill = self.copy_skill()
        self.addCleanup(temporary_directory.cleanup)
        metadata_file = copied_skill / "agents/openai.yaml"
        metadata = metadata_file.read_text(encoding="utf-8")
        metadata_file.write_text(
            metadata.replace('  display_name: "中国大陆租房合同审查"', '  display_name: ""', 1),
            encoding="utf-8",
        )
        self.assertIn(
            "agents/openai.yaml interface.display_name must be a non-empty string",
            validate_skill_package(copied_skill),
        )

    def test_metadata_rejects_default_prompt_under_decoy_mapping(self) -> None:
        temporary_directory, copied_skill = self.copy_skill()
        self.addCleanup(temporary_directory.cleanup)
        metadata_file = copied_skill / "agents/openai.yaml"
        metadata = metadata_file.read_text(encoding="utf-8")
        metadata_file.write_text(
            metadata.replace("  default_prompt:", "decoy:\n  default_prompt:", 1),
            encoding="utf-8",
        )
        self.assertIn(
            "agents/openai.yaml interface.default_prompt must be a non-empty string",
            validate_skill_package(copied_skill),
        )


class PublicationLeakageTests(unittest.TestCase):
    def scan_temporary_tree(self, relative_path: str, content: str) -> list[str]:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            target = root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return validate_publication.validate_publication(root)

    def test_current_public_manifest_passes(self) -> None:
        self.assertEqual([], validate_publication.validate_publication(REPOSITORY_ROOT))

    def test_fixture_without_explicit_synthetic_marker_fails(self) -> None:
        errors = self.scan_temporary_tree("tests/fixtures/synthetic/case.json", '{"case": "example"}\n')
        self.assertIn("tests/fixtures/synthetic/case.json: fixture lacks explicit synthetic: true marker", errors)

    def test_marked_fixture_can_pass_the_publication_scan(self) -> None:
        self.assertEqual(
            [],
            self.scan_temporary_tree("tests/fixtures/synthetic/case.json", '{"synthetic": true, "case": "example"}\n'),
        )

    def test_absolute_path_token_and_identity_number_fail(self) -> None:
        local_path = "/" + "Users/example/contract.pdf"
        token = "gh" + "p_" + "A" * 36
        identity_number = "110105" + "19491231" + "002X"
        errors = self.scan_temporary_tree(
            "examples/release-check.txt",
            f"path={local_path}\ntoken={token}\nidentity={identity_number}\n",
        )
        self.assertTrue(any("local absolute path" in error for error in errors))
        self.assertTrue(any("GitHub token" in error for error in errors))
        self.assertTrue(any("identity number" in error for error in errors))

    def test_work_temporary_and_log_artifacts_fail(self) -> None:
        for relative_path in ("work/session.json", "temp/eval.json", "host-logs/host.log"):
            with self.subTest(relative_path=relative_path):
                errors = self.scan_temporary_tree(relative_path, "synthetic test output\n")
                self.assertTrue(any("forbidden" in error for error in errors))

    def test_privacy_contract_blocks_untrusted_and_undisclosed_real_material_paths(self) -> None:
        privacy = (REPOSITORY_ROOT / "skills/tenant-contract-review-cn/references/privacy-safety.md").read_text(encoding="utf-8")
        self.assertIn("不可信数据", privacy)
        self.assertIn("不能改变安全门禁", privacy)
        self.assertIn("processor", privacy)
        self.assertIn("training_opt_out_verified", privacy)
        self.assertIn("不得读取或传输未经充分脱敏的真实材料", privacy)

    def test_log_minimization_and_deletion_never_claim_success_without_receipt(self) -> None:
        privacy = (REPOSITORY_ROOT / "skills/tenant-contract-review-cn/references/privacy-safety.md").read_text(encoding="utf-8")
        self.assertIn("案件 ID、材料摘要（不得含原文）、阶段、门禁结果、错误分类与耗时", privacy)
        self.assertIn("绝不伪造删除成功或删除凭证", privacy)
        security = (REPOSITORY_ROOT / "SECURITY.md").read_text(encoding="utf-8")
        self.assertIn("自动扫描是发布门槛，不替代人工审阅", security)


if __name__ == "__main__":
    unittest.main()
