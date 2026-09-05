from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.8-3.10
    import tomli as tomllib


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "codex_instruct",
    PROJECT_ROOT / "codex-instruct.py",
)
assert SPEC and SPEC.loader
codex_instruct = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(codex_instruct)


class ManagedConfigTests(unittest.TestCase):
    def make_config(self, text: str) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary_directory = tempfile.TemporaryDirectory()
        config_path = Path(temporary_directory.name) / "config.toml"
        config_path.write_text(text, encoding="utf-8")
        return temporary_directory, config_path

    def test_gpt56_v45_is_the_stable_default_release(self) -> None:
        self.assertEqual(codex_instruct.DEFAULT_PROMPT_VERSION, "gpt-5.6-v45")
        self.assertEqual(
            codex_instruct.DEFAULT_PROMPT_MD_FILENAME,
            "gpt-5.6-sol-v45.md",
        )
        self.assertEqual(
            codex_instruct.DEFAULT_PROMPT_ARCHIVE.name,
            "gpt-5.6-sol-v45.zip",
        )
        self.assertEqual(
            {
                version: (archive.name, md_filename)
                for version, (archive, md_filename) in codex_instruct.PROMPT_VERSIONS.items()
            },
            {
                "gpt-5.6-v45": ("gpt-5.6-sol-v45.zip", "gpt-5.6-sol-v45.md"),
                "gpt-6-v1-rc1": ("gpt-6-astra-v1-rc1.zip", "gpt-6-astra-v1-rc1.md"),
            },
        )
        self.assertIn("gpt-6-astra-v1-rc1.md", codex_instruct.MANAGED_PROMPT_FILENAMES)
        self.assertEqual(
            codex_instruct.LEGACY_MANAGED_PROMPT_FILENAMES,
            {
                "gpt-5.6-sol-unrestricted-v45.md",
                "gpt-5.6-sol-unrestricted-v5.md",
                "gpt-5.6-sol-unrestricted-v35.md",
                "gpt-5.6-sol-unrestricted-v41.md",
                "gpt-5.6-sol-unrestricted-v41-skills.md",
                "gpt-5.6-sol-unrestricted-v42.md",
            },
        )

    def test_cli_deploys_selected_rc1_archive(self) -> None:
        temporary_directory, config_path = self.make_config('model = "gpt-6-astra"\n')
        self.addCleanup(temporary_directory.cleanup)
        codex_home = config_path.parent

        with patch.object(
            sys,
            "argv",
            [
                "codex-instruct.py",
                "--apply",
                "--version",
                "gpt-6-v1-rc1",
                "--codex-dir",
                str(codex_home),
            ],
        ):
            result = codex_instruct.main()

        self.assertEqual(result, 0)
        deployed = codex_home / "gpt-6-astra-v1-rc1.md"
        self.assertEqual(
            deployed.read_bytes(),
            (PROJECT_ROOT / "gpt-6-astra-v1-rc1.md").read_bytes(),
        )
        self.assertIn(
            'model_instructions_file = "./gpt-6-astra-v1-rc1.md"',
            config_path.read_text(encoding="utf-8"),
        )

    def test_interactive_menu_selects_each_packaged_version(self) -> None:
        with patch("builtins.input", return_value="1"):
            self.assertEqual(
                codex_instruct.interactive_action(),
                "apply:gpt-5.6-v45",
            )
        with patch("builtins.input", return_value="2"):
            self.assertEqual(
                codex_instruct.interactive_action(),
                "apply:gpt-6-v1-rc1",
            )

    # A pre-existing top-level instruction line, including its comment, survives deploy/reset.
    def test_round_trip_restores_previous_instruction_entry(self) -> None:
        original_line = 'model_instructions_file = "./personal-instructions.md" # keep me'
        temporary_directory, config_path = self.make_config(
            f'model = "gpt-5.5"\n{original_line}\n'
        )
        self.addCleanup(temporary_directory.cleanup)

        codex_instruct.prepare_deployment_state(
            config_path,
            "gpt-5.6-sol-unrestricted-v45.md",
            "test instructions\n",
        )
        codex_instruct.set_model_instructions(
            config_path,
            "gpt-5.6-sol-unrestricted-v45.md",
        )
        changed, status = codex_instruct.restore_managed_model_instructions(config_path)

        self.assertTrue(changed)
        self.assertEqual(status, "restored")
        self.assertIn(original_line, config_path.read_text(encoding="utf-8"))

    # Assignments inside TOML tables are not mistaken for the managed top-level field.
    def test_nested_assignment_is_not_rewritten(self) -> None:
        nested_line = 'model_instructions_file = "nested-value.md"'
        temporary_directory, config_path = self.make_config(
            f'[profile.test]\n{nested_line}\n'
        )
        self.addCleanup(temporary_directory.cleanup)

        codex_instruct.prepare_deployment_state(
            config_path,
            "gpt-5.6-sol-unrestricted-v45.md",
            "test instructions\n",
        )
        codex_instruct.set_model_instructions(
            config_path,
            "gpt-5.6-sol-unrestricted-v45.md",
        )
        codex_instruct.restore_managed_model_instructions(config_path)

        text = config_path.read_text(encoding="utf-8")
        self.assertEqual(text.count(nested_line), 1)
        self.assertNotIn("gpt-5.6-sol-unrestricted-v45.md", text)

    # Legacy backups contribute only the prior instruction entry, never stale provider data.
    def test_legacy_baseline_migrates_only_previous_instruction(self) -> None:
        temporary_directory, config_path = self.make_config(
            'model_provider = "openai"\n'
            'model_instructions_file = "./gpt-5.6-sol-unrestricted-v42.md"\n'
        )
        self.addCleanup(temporary_directory.cleanup)
        baseline = codex_instruct.baseline_backup_path(config_path)
        baseline.write_text(
            'model_provider = "custom"\n'
            'model_instructions_file = "./personal.md"\n\n'
            '[model_providers.custom]\nbase_url = "https://example.invalid/v1"\n',
            encoding="utf-8",
        )

        changed, status = codex_instruct.restore_managed_model_instructions(config_path)

        self.assertTrue(changed)
        self.assertEqual(status, "restored")
        restored = tomllib.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(restored["model_provider"], "openai")
        self.assertEqual(restored["model_instructions_file"], "./personal.md")
        self.assertNotIn("model_providers", restored)

    # One end-to-end reset covers custom-name ownership, owned-artifact cleanup,
    # and preservation of provider/feature settings changed after deployment.
    def test_full_reset_removes_state_and_prompt_without_reverting_provider(self) -> None:
        temporary_directory, config_path = self.make_config(
            'model_provider = "custom"\nmodel = "gpt-5.5"\n'
        )
        self.addCleanup(temporary_directory.cleanup)
        codex_home = config_path.parent
        source = codex_home / "source.md"
        source.write_text("test instructions\n", encoding="utf-8")
        args = SimpleNamespace(codex_dir=str(codex_home), dry_run=False)

        result = codex_instruct.deploy_prompt(args, source, "custom-prompt.md")
        self.assertEqual(result, 0)

        # CCSwitch changes provider state while retaining the common instruction entry.
        config_path.write_text(
            'model_provider = "openai"\n'
            'model = "gpt-5.5"\n'
            'model_instructions_file = "./custom-prompt.md"\n\n'
            '[features]\n'
            'web_search = true\n',
            encoding="utf-8",
        )
        with patch("builtins.input", return_value="y"):
            result = codex_instruct.reset_managed_install(args)

        self.assertEqual(result, 0)
        restored = tomllib.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(restored["model_provider"], "openai")
        self.assertEqual(restored["model"], "gpt-5.5")
        self.assertTrue(restored["features"]["web_search"])
        self.assertNotIn("model_instructions_file", restored)
        self.assertFalse((codex_home / "custom-prompt.md").exists())
        self.assertFalse(codex_instruct.state_file_path(config_path).exists())

    # Editing a CRLF config must not introduce mixed line endings.
    def test_crlf_line_endings_are_preserved(self) -> None:
        text = 'model = "gpt-5.5"\r\n[features]\r\nweb_search = true\r\n'
        updated = codex_instruct.replace_top_level_model_instructions(
            text,
            'model_instructions_file = "./prompt.md"',
        )

        self.assertNotIn("\n", updated.replace("\r\n", ""))

    # An invalid state file cannot nominate config.toml or another non-Markdown file for deletion.
    def test_tampered_state_cannot_nominate_config_for_deletion(self) -> None:
        temporary_directory, config_path = self.make_config(
            'model_instructions_file = "./gpt-5.6-sol-unrestricted-v41.md"\n'
        )
        self.addCleanup(temporary_directory.cleanup)
        state_path = codex_instruct.state_file_path(config_path)
        state_path.write_text(
            json.dumps(
                {
                    "version": codex_instruct.STATE_VERSION,
                    "previous_model_instructions_line": None,
                    "managed_prompts": {
                        "config.toml": {
                            "sha256": "0" * 64,
                            "existed_before": False,
                        },
                    },
                }
            ),
            encoding="utf-8",
        )
        args = SimpleNamespace(codex_dir=str(config_path.parent), dry_run=False)

        with patch("builtins.input", return_value="y"):
            result = codex_instruct.reset_managed_install(args)

        self.assertEqual(result, 0)
        self.assertTrue(config_path.exists())

    # A user-replaced prompt fails the recorded SHA256 check and must be preserved.
    def test_modified_custom_prompt_is_preserved_on_reset(self) -> None:
        temporary_directory, config_path = self.make_config('model = "gpt-5.5"\n')
        self.addCleanup(temporary_directory.cleanup)
        codex_home = config_path.parent
        source = codex_home / "source.md"
        source.write_text("deployed content\n", encoding="utf-8")
        args = SimpleNamespace(codex_dir=str(codex_home), dry_run=False)
        self.assertEqual(
            codex_instruct.deploy_prompt(args, source, "custom-prompt.md"),
            0,
        )
        custom_prompt = codex_home / "custom-prompt.md"
        custom_prompt.write_text("user replacement\n", encoding="utf-8")
        config_path.write_text(
            'model_instructions_file = "./personal.md"\n',
            encoding="utf-8",
        )

        with patch("builtins.input", return_value="y"):
            result = codex_instruct.reset_managed_install(args)

        self.assertEqual(result, 0)
        self.assertEqual(custom_prompt.read_text(encoding="utf-8"), "user replacement\n")
        self.assertIn("./personal.md", config_path.read_text(encoding="utf-8"))

    # Atomic config writes follow a trusted config symlink instead of replacing the link itself.
    def test_atomic_config_update_preserves_symlink(self) -> None:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        codex_home = Path(temporary_directory.name)
        target = codex_home / "shared-config.toml"
        config_path = codex_home / "config.toml"
        target.write_text('model = "gpt-5.5"\n', encoding="utf-8")
        config_path.symlink_to(target.name)

        codex_instruct.set_model_instructions(
            config_path,
            "gpt-5.6-sol-unrestricted-v45.md",
        )

        self.assertTrue(config_path.is_symlink())
        self.assertIn("model_instructions_file", target.read_text(encoding="utf-8"))

    # A matching basename outside CODEX_HOME is not treated as a script-owned prompt.
    def test_external_path_with_managed_basename_is_not_owned(self) -> None:
        line = 'model_instructions_file = "/tmp/gpt-5.6-sol-unrestricted-v42.md"'
        self.assertFalse(
            codex_instruct.line_references_managed_prompt(
                line,
                codex_instruct.MANAGED_PROMPT_FILENAMES,
            )
        )

    # Deployment refuses to overwrite a destination that is not already tracked as owned.
    def test_preexisting_unowned_prompt_is_not_overwritten(self) -> None:
        temporary_directory, config_path = self.make_config('model = "gpt-5.5"\n')
        self.addCleanup(temporary_directory.cleanup)
        codex_home = config_path.parent
        source = codex_home / "source.md"
        source.write_text("new content\n", encoding="utf-8")
        destination = codex_home / "custom-prompt.md"
        destination.write_text("personal content\n", encoding="utf-8")
        args = SimpleNamespace(codex_dir=str(codex_home), dry_run=False)

        result = codex_instruct.deploy_prompt(args, source, destination.name)

        self.assertEqual(result, 2)
        self.assertEqual(destination.read_text(encoding="utf-8"), "personal content\n")
        self.assertFalse(codex_instruct.state_file_path(config_path).exists())

    # Full-file recovery remains available only through the explicit snapshot command.
    def test_explicit_snapshot_restore_keeps_manual_recovery(self) -> None:
        temporary_directory, config_path = self.make_config(
            'model_provider = "openai"\n'
        )
        self.addCleanup(temporary_directory.cleanup)
        codex_home = config_path.parent
        snapshot = codex_home / "config.toml.bak_20260723_010203_000001"
        snapshot.write_text('model_provider = "custom"\n', encoding="utf-8")
        args = SimpleNamespace(codex_dir=str(codex_home), dry_run=False)

        with patch("builtins.input", return_value="y"):
            result = codex_instruct.restore_config_snapshot(args, snapshot)

        self.assertEqual(result, 0)
        self.assertIn('model_provider = "custom"', config_path.read_text(encoding="utf-8"))

    # Legacy deployments preserve prompt files that existed before ownership tracking.
    def test_legacy_preexisting_prompt_is_preserved(self) -> None:
        filename = "gpt-5.6-sol-unrestricted-v41.md"
        temporary_directory, config_path = self.make_config(
            f'model_instructions_file = "./{filename}"\n'
        )
        self.addCleanup(temporary_directory.cleanup)
        codex_home = config_path.parent
        codex_instruct.baseline_backup_path(config_path).write_text(
            'model = "gpt-5.5"\n',
            encoding="utf-8",
        )
        destination = codex_home / filename
        destination.write_text("legacy deployment\n", encoding="utf-8")
        source = codex_home / "source.md"
        source.write_text("updated deployment\n", encoding="utf-8")
        args = SimpleNamespace(codex_dir=str(codex_home), dry_run=False)

        self.assertEqual(codex_instruct.deploy_prompt(args, source, filename), 0)
        with patch("builtins.input", return_value="y"):
            self.assertEqual(codex_instruct.reset_managed_install(args), 0)

        self.assertTrue(destination.exists())
        self.assertEqual(destination.read_text(encoding="utf-8"), "updated deployment\n")


if __name__ == "__main__":
    unittest.main()
