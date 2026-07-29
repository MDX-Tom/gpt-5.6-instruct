#!/usr/bin/env python3
"""Deploy or remove the default gpt-5.6-sol Codex instruction file.

The public repository stores the prompt as a ZIP archive. Applying it extracts
its Markdown file into CODEX_HOME, snapshots config.toml, and sets the
top-level `model_instructions_file` entry. Reset only restores that managed
entry and removes prompt files owned by this script; it never replaces the
whole config.toml, so provider managers such as CCSwitch remain authoritative.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import unicodedata
import zipfile
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_PROMPT_MD_FILENAME = "gpt-5.6-sol-unrestricted-v42.md"
DEFAULT_PROMPT_ARCHIVE = PROJECT_ROOT / "gpt-5.6-sol-unrestricted-v42.zip"
# Keep recognizing old installs so reset can migrate them without exposing a
# production version selector or requiring historical archives at the root.
LEGACY_MANAGED_PROMPT_FILENAMES = {
    "gpt-5.6-sol-unrestricted-v5.md",
    "gpt-5.6-sol-unrestricted-v35.md",
    "gpt-5.6-sol-unrestricted-v41.md",
    "gpt-5.6-sol-unrestricted-v41-skills.md",
}
MANAGED_PROMPT_FILENAMES = {
    DEFAULT_PROMPT_MD_FILENAME,
    *LEGACY_MANAGED_PROMPT_FILENAMES,
}
BASELINE_BACKUP_SUFFIX = ".gpt56-sol-instruct.bak"
STATE_FILENAME = ".gpt56-sol-instruct-state.json"
STATE_VERSION = 2
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
MODEL_INSTRUCTIONS_PATTERN = re.compile(
    r"^\s*model_instructions_file\s*=\s*(['\"])(.*?)\1\s*(?:#.*)?$"
)

ANSI_RESET = "\033[0m"
ANSI_BOLD = "\033[1m"
ANSI_DARK_GREEN = "\033[38;2;0;100;0m"
BANNER_WIDTH = 72


def color_enabled() -> bool:
    if os.environ.get("FORCE_COLOR") is not None:
        return True
    return sys.stdout.isatty()


def styled(text: str, *codes: str) -> str:
    if not color_enabled():
        return text
    return f"{''.join(codes)}{text}{ANSI_RESET}"


def display_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1 for char in text)


def section_banner(title: str) -> str:
    label = f" {title} "
    fill_width = max(4, BANNER_WIDTH - display_width(label))
    left = fill_width // 2
    right = fill_width - left
    return styled(f"{'━' * left}{label}{'━' * right}", ANSI_BOLD)


def intro_text() -> str:
    zh_banner = section_banner("中文说明")
    en_banner = section_banner("English Instructions")
    zh_title = styled("gpt-5.6-sol Codex 默认提示词部署说明：", ANSI_BOLD)
    en_title = styled("Default gpt-5.6-sol Codex instruction deployment:", ANSI_BOLD)
    zh_default = styled("唯一默认版", ANSI_BOLD, ANSI_DARK_GREEN)
    en_default = styled("sole default release", ANSI_BOLD, ANSI_DARK_GREEN)
    return f"""\
{zh_banner}
{zh_title}

v42 是当前生产使用的{zh_default}。它在 v41 基础上加入 Issue #5/#22 的首轮执行完成规则，并继续以紧凑的通用归一化、状态连续性、跨域路由和真实工件规则覆盖常规与新增专项任务。

部署后会将 v42 提示词复制到 CODEX_HOME，在 config.toml 中写入 model_instructions_file 项，并创建操作前快照。卸载时只恢复这一项，不会覆盖 CCSwitch 管理的 provider、模型或认证配置。自定义文件仍可通过 --file 显式部署。

{en_banner}
{en_title}

v42 is the current {en_default}. It adds first-turn completion rules for Issues #5/#22 on top of v41 while retaining compact general normalization, state continuity, cross-domain routing, and real-artifact rules for routine and issue-driven tasks.

Deployment copies the v42 prompt to CODEX_HOME, writes the model_instructions_file entry to config.toml, and creates a pre-operation snapshot. Uninstall restores only that entry and never replaces provider, model, or authentication settings managed by CCSwitch. A custom file can still be deployed explicitly with --file.
"""


def menu_text() -> str:
    selection_banner = section_banner("操作选择 / Select an Action")
    default = styled("默认 / Default", ANSI_BOLD, ANSI_DARK_GREEN)
    return f"""\
{selection_banner}
1. 植入 v42 提示词 / Apply v42 instructions file （{default}）
2. 去除提示词并恢复原配置项 / Remove managed instructions
q. 退出而不执行任何操作 / Quit without modification
"""


def find_codex_dirs() -> list[Path]:
    candidates: set[Path] = set()
    env_home = os.environ.get("CODEX_HOME")
    if env_home:
        candidates.add(Path(env_home).expanduser())
    candidates.add(Path.home() / ".codex")
    return sorted(path.resolve() for path in candidates if (path / "config.toml").exists())


def selected_codex_dirs(codex_dir: str | None) -> list[Path]:
    if codex_dir:
        return [Path(codex_dir).expanduser().resolve()]
    return find_codex_dirs()


def backup_file(path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup = path.with_suffix(path.suffix + f".bak_{timestamp}")
    shutil.copy2(path, backup)
    return backup


def baseline_backup_path(config_path: Path) -> Path:
    return config_path.with_name(config_path.name + BASELINE_BACKUP_SUFFIX)


def state_file_path(config_path: Path) -> Path:
    return config_path.parent / STATE_FILENAME


def is_safe_prompt_filename(filename: object) -> bool:
    return (
        isinstance(filename, str)
        and bool(filename)
        and "/" not in filename
        and "\\" not in filename
        and filename.lower().endswith(".md")
        and Path(filename).name == filename
    )


def prompt_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_valid_instruction_line(line: object) -> bool:
    return (
        isinstance(line, str)
        and "\n" not in line
        and "\r" not in line
        and MODEL_INSTRUCTIONS_PATTERN.fullmatch(line) is not None
    )


def top_level_model_instructions_line(text: str) -> str | None:
    """Return the root model_instructions_file assignment, ignoring TOML tables."""
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("["):
            break
        if re.match(r"^\s*model_instructions_file\s*=", line):
            return line
    return None


def line_references_managed_prompt(line: str | None, filenames: set[str]) -> bool:
    if not line:
        return False
    match = MODEL_INSTRUCTIONS_PATTERN.fullmatch(line)
    if not match:
        return False
    reference = match.group(2).replace("\\", "/")
    if reference.startswith("./"):
        reference = reference[2:]
    if "/" in reference:
        return False
    return reference in filenames


def replace_top_level_model_instructions(text: str, replacement: str | None) -> str:
    """Replace only the root assignment while preserving all unrelated TOML text."""
    lines = text.splitlines(keepends=True)
    table_index = next(
        (index for index, line in enumerate(lines) if line.lstrip().startswith("[")),
        len(lines),
    )
    assignment_indexes = [
        index
        for index, line in enumerate(lines[:table_index])
        if re.match(r"^\s*model_instructions_file\s*=", line)
    ]

    if assignment_indexes:
        first = assignment_indexes[0]
        newline = (
            "\r\n"
            if lines[first].endswith("\r\n")
            else "\n"
            if lines[first].endswith("\n")
            else ""
        )
        if replacement is None:
            del lines[first]
        else:
            lines[first] = replacement + newline
        return "".join(lines)

    if replacement is None:
        return text

    insert_at = next(
        (
            index + 1
            for index, line in enumerate(lines[:table_index])
            if re.match(r"^\s*model\s*=", line)
        ),
        table_index,
    )
    newline = "\r\n" if any(line.endswith("\r\n") for line in lines) else "\n"
    if insert_at > 0 and lines[insert_at - 1] and not lines[insert_at - 1].endswith("\n"):
        lines[insert_at - 1] += newline
    lines.insert(insert_at, replacement + newline)
    return "".join(lines)


def atomic_write_text(path: Path, text: str, *, follow_symlink: bool = False) -> None:
    """Atomically update text, following symlinks only for explicitly trusted paths."""
    if path.is_symlink() and not follow_symlink:
        raise OSError(f"refusing to overwrite symlink: {path}")
    write_path = path.resolve(strict=False) if path.is_symlink() else path
    previous_mode = write_path.stat().st_mode & 0o777 if write_path.exists() else 0o600
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{write_path.name}.",
        dir=write_path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        # Disable platform newline translation so the deployed file hash matches
        # the SHA256 stored in the managed-install state on Windows as well.
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, previous_mode)
        os.replace(temporary_path, write_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def read_state(config_path: Path) -> dict[str, object] | None:
    path = state_file_path(config_path)
    if not path.exists():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(state, dict) or state.get("version") != STATE_VERSION:
        return None

    previous_line = state.get("previous_model_instructions_line")
    if previous_line is not None and not is_valid_instruction_line(previous_line):
        return None

    stored_prompts = state.get("managed_prompts")
    if not isinstance(stored_prompts, dict):
        return None
    managed_prompts: dict[str, dict[str, object]] = {}
    for filename, metadata in stored_prompts.items():
        if not is_safe_prompt_filename(filename) or not isinstance(metadata, dict):
            return None
        digest = metadata.get("sha256")
        if not isinstance(digest, str) or not SHA256_PATTERN.fullmatch(digest):
            return None
        existed_before = metadata.get("existed_before")
        if not isinstance(existed_before, bool):
            return None
        managed_prompts[filename] = {
            "sha256": digest,
            "existed_before": existed_before,
        }

    return {
        "version": STATE_VERSION,
        "previous_model_instructions_line": previous_line,
        "managed_prompts": managed_prompts,
    }


def save_state(config_path: Path, state: dict[str, object]) -> None:
    atomic_write_text(
        state_file_path(config_path),
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
    )


def previous_instruction_from_legacy_baseline(config_path: Path) -> str | None:
    """Migrate only the old instruction entry, never provider data, from a legacy backup."""
    baseline = baseline_backup_path(config_path)
    if not baseline.exists():
        return None
    line = top_level_model_instructions_line(baseline.read_text(encoding="utf-8"))
    if line_references_managed_prompt(line, MANAGED_PROMPT_FILENAMES):
        return None
    return line


def prepare_deployment_state(
    config_path: Path,
    md_filename: str,
    prompt_text: str,
    existed_before: bool = False,
) -> dict[str, object]:
    state = read_state(config_path)
    if state is None:
        current_line = top_level_model_instructions_line(
            config_path.read_text(encoding="utf-8") if config_path.exists() else ""
        )
        if line_references_managed_prompt(
            current_line,
            MANAGED_PROMPT_FILENAMES | {md_filename},
        ):
            current_line = previous_instruction_from_legacy_baseline(config_path)
        state = {
            "version": STATE_VERSION,
            "previous_model_instructions_line": current_line,
            "managed_prompts": {},
        }

    managed_prompts = state["managed_prompts"]
    assert isinstance(managed_prompts, dict)
    previous_metadata = managed_prompts.get(md_filename)
    was_preexisting = (
        previous_metadata.get("existed_before", existed_before)
        if isinstance(previous_metadata, dict)
        else existed_before
    )
    managed_prompts[md_filename] = {
        "sha256": prompt_sha256(prompt_text),
        "existed_before": bool(was_preexisting),
    }
    save_state(config_path, state)
    return state


def set_model_instructions(config_path: Path, md_filename: str) -> bool:
    text = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    target = f'model_instructions_file = "./{md_filename}"'
    new_text = replace_top_level_model_instructions(text, target)
    if new_text != text:
        atomic_write_text(config_path, new_text, follow_symlink=True)
        return True
    return False


def restore_managed_model_instructions(config_path: Path) -> tuple[bool, str]:
    if not config_path.exists():
        return False, "missing"

    state = read_state(config_path)
    managed_filenames = set(MANAGED_PROMPT_FILENAMES)
    if state:
        stored_prompts = state.get("managed_prompts", {})
        if isinstance(stored_prompts, dict):
            managed_filenames.update(stored_prompts)

    text = config_path.read_text(encoding="utf-8")
    current_line = top_level_model_instructions_line(text)
    if not line_references_managed_prompt(current_line, managed_filenames):
        return False, "not-managed"

    previous_line = state.get("previous_model_instructions_line") if state else None
    if previous_line is not None and not isinstance(previous_line, str):
        previous_line = None
    if state is None:
        previous_line = previous_instruction_from_legacy_baseline(config_path)

    new_text = replace_top_level_model_instructions(text, previous_line)
    if new_text != text:
        atomic_write_text(config_path, new_text, follow_symlink=True)
        return True, "restored" if previous_line else "removed"
    return False, "unchanged"


def read_prompt(source_path: Path, expected_md_filename: str) -> str:
    """Read a Markdown prompt directly or extract it from a ZIP archive."""
    if source_path.suffix.lower() != ".zip":
        return source_path.read_text(encoding="utf-8")

    with zipfile.ZipFile(source_path) as archive:
        files = [name for name in archive.namelist() if not name.endswith("/")]
        preferred = [name for name in files if Path(name).name == expected_md_filename]
        markdown_files = [name for name in files if Path(name).suffix.lower() == ".md"]
        candidates = preferred or markdown_files
        if len(candidates) != 1:
            raise ValueError(
                f"压缩包应包含唯一的 {expected_md_filename}（或唯一 Markdown 文件），"
                f"实际候选: {candidates}"
            )
        member = candidates[0]
        with tempfile.TemporaryDirectory(prefix="gpt56-sol-prompt-") as temp_dir:
            extracted_path = Path(archive.extract(member, path=temp_dir))
            return extracted_path.read_text(encoding="utf-8")


def deploy_prompt(
    args: argparse.Namespace,
    prompt_path: Path,
    md_filename: str,
) -> int:
    if not is_safe_prompt_filename(md_filename):
        print(f"[错误] 目标名称必须是不含路径的 .md 文件名: {md_filename}", file=sys.stderr)
        return 2
    if not prompt_path.exists():
        print(f"[错误] 提示词文件不存在: {prompt_path}", file=sys.stderr)
        return 2

    codex_dirs = selected_codex_dirs(args.codex_dir)
    if not codex_dirs:
        print("[错误] 未找到 .codex/config.toml；请使用 --codex-dir 指定。", file=sys.stderr)
        return 2

    try:
        prompt_text = read_prompt(prompt_path, md_filename)
    except (OSError, UnicodeError, ValueError, zipfile.BadZipFile) as exc:
        print(f"[错误] 读取或解压提示词失败: {exc}", file=sys.stderr)
        return 2

    source_kind = "ZIP（已解压校验）" if prompt_path.suffix.lower() == ".zip" else "Markdown"
    print(f"[+] Prompt: {prompt_path} [{source_kind}]")
    for codex_dir in codex_dirs:
        config_path = codex_dir / "config.toml"
        destination = codex_dir / md_filename
        print(f"\n── 目标 / Target: {codex_dir} ──")
        print(f"  写入 / Write: {destination}")
        print(f'  配置 / Config: model_instructions_file = "./{md_filename}"')
        print("  兼容模式 / Compatibility: 仅修改本项目管理的配置项")
        if args.dry_run:
            continue

        codex_dir.mkdir(parents=True, exist_ok=True)
        if not config_path.exists():
            atomic_write_text(config_path, "", follow_symlink=True)
            print("  创建 / Created: config.toml")

        if state_file_path(config_path).is_symlink():
            print(
                f"[错误] 状态文件不能是符号链接: {state_file_path(config_path)}",
                file=sys.stderr,
            )
            print("[Error] State file must not be a symlink.", file=sys.stderr)
            return 2

        state = read_state(config_path)
        tracked_prompts = state.get("managed_prompts", {}) if state else {}
        current_line = top_level_model_instructions_line(
            config_path.read_text(encoding="utf-8")
        )
        legacy_owned = state is None and line_references_managed_prompt(
            current_line,
            {md_filename},
        )
        if (
            (destination.exists() or destination.is_symlink())
            and md_filename not in tracked_prompts
            and not legacy_owned
        ):
            print(
                f"[错误] 目标文件已存在且不属于本脚本，未覆盖: {destination}",
                file=sys.stderr,
            )
            print(
                "[Error] Destination exists but is not owned by this script; "
                "choose another --name.",
                file=sys.stderr,
            )
            return 2

        snapshot = backup_file(config_path)
        print(f"  已创建操作前备份 / Snapshot saved: {snapshot.name}")

        prepare_deployment_state(
            config_path,
            md_filename,
            prompt_text,
            existed_before=destination.exists() or destination.is_symlink(),
        )
        atomic_write_text(destination, prompt_text)
        changed = set_model_instructions(config_path, md_filename)
        print("  状态 / Status:", "已更新 / Updated" if changed else "已是最新 / Already current")
    return 0


def confirm_reset() -> bool:
    print("  将只恢复本脚本管理的 model_instructions_file，并移除提示词文件。")
    print("  provider、模型、认证及CCSwitch在部署后写入的其他配置均保持不变。")
    print("  Only the managed model_instructions_file entry and prompt files will change.")
    print("  Provider, model, authentication, and later CCSwitch changes will be preserved.")
    try:
        answer = input("确认继续？/ Confirm removal? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer in {"y", "yes", "是"}


def confirm_snapshot_restore(snapshot: Path) -> bool:
    print(f"  将使用整份快照覆盖当前 config.toml / Full snapshot: {snapshot}")
    print("  这可能恢复旧的 provider、模型或认证配置，请仅用于人工应急恢复。")
    print("  This may restore old provider, model, or authentication settings.")
    try:
        answer = input("确认完整恢复？/ Confirm full restore? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer in {"y", "yes", "是"}


def restore_config_snapshot(args: argparse.Namespace, snapshot: Path) -> int:
    codex_dirs = selected_codex_dirs(args.codex_dir)
    if len(codex_dirs) != 1:
        print(
            "[错误] 完整快照恢复必须使用 --codex-dir 指定唯一目标。",
            file=sys.stderr,
        )
        print(
            "[Error] Full snapshot restore requires exactly one --codex-dir target.",
            file=sys.stderr,
        )
        return 2

    codex_dir = codex_dirs[0]
    config_path = codex_dir / "config.toml"
    snapshot = snapshot.expanduser().resolve()
    allowed_names = {
        config_path.name + BASELINE_BACKUP_SUFFIX,
    }
    valid_name = (
        snapshot.name.startswith(config_path.name + ".bak_")
        or snapshot.name in allowed_names
    )
    if snapshot.parent != codex_dir.resolve() or not snapshot.is_file() or not valid_name:
        print(
            "[错误] 快照必须是目标 CODEX_HOME 中由本脚本创建的 config.toml 备份。",
            file=sys.stderr,
        )
        print(
            "[Error] Snapshot must be a config.toml backup inside the target CODEX_HOME.",
            file=sys.stderr,
        )
        return 2

    try:
        snapshot_text = snapshot.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        print(f"[错误] 无法读取快照 / Failed to read snapshot: {exc}", file=sys.stderr)
        return 2

    print(f"[+] Snapshot: {snapshot}")
    print(f"[+] Target: {config_path}")
    if args.dry_run:
        print("  预览完成，未修改文件 / Dry run complete; no files changed.")
        return 0
    if not confirm_snapshot_restore(snapshot):
        print("  未确认，已取消 / Confirmation not received; restore cancelled.")
        return 0

    codex_dir.mkdir(parents=True, exist_ok=True)
    if config_path.exists():
        safety_snapshot = backup_file(config_path)
        print(f"  已备份当前配置 / Current config saved: {safety_snapshot.name}")
    atomic_write_text(config_path, snapshot_text, follow_symlink=True)
    print("  已完整恢复 config.toml / Full config.toml restored.")
    return 0


def reset_managed_install(args: argparse.Namespace) -> int:
    codex_dirs = selected_codex_dirs(args.codex_dir)
    if not codex_dirs:
        print("[错误] 未找到 .codex/config.toml；请使用 --codex-dir 指定。", file=sys.stderr)
        return 2

    for codex_dir in codex_dirs:
        config_path = codex_dir / "config.toml"
        print(f"\n── 目标 / Target: {codex_dir} ──")
        state = read_state(config_path)
        managed_prompts = state.get("managed_prompts", {}) if state else {}
        assert isinstance(managed_prompts, dict)

        if not confirm_reset():
            print("  未确认，已取消 / Confirmation not received; reset cancelled.")
            continue

        print("  配置 / Config: 字段级恢复，不覆盖 config.toml")
        for filename in sorted(managed_prompts):
            print(f"  校验后移除 / Verify then remove: {filename}")
        if not managed_prompts:
            print("  提示词 / Prompts: 无可信状态记录，不自动删除文件")
        if args.dry_run:
            print("  预览完成，未修改文件 / Dry run complete; no files changed.")
            continue

        codex_dir.mkdir(parents=True, exist_ok=True)
        if config_path.exists():
            snapshot = backup_file(config_path)
            print(f"  已创建恢复前备份 / Pre-reset snapshot: {snapshot.name}")

        _changed, status = restore_managed_model_instructions(config_path)
        status_messages = {
            "restored": "已恢复原配置项 / Previous entry restored",
            "removed": "已移除脚本配置项 / Managed entry removed",
            "not-managed": "当前配置项不属于本脚本，保持不变 / Current entry left unchanged",
            "missing": "config.toml 不存在 / Not found",
            "unchanged": "无需修改 / No change needed",
        }
        print("  配置状态 / Config status:", status_messages[status])

        removed = 0
        preserved = 0
        for filename, metadata in managed_prompts.items():
            prompt_path = codex_dir / filename
            expected_digest = metadata.get("sha256") if isinstance(metadata, dict) else None
            existed_before = (
                metadata.get("existed_before", True) if isinstance(metadata, dict) else True
            )
            try:
                digest_matches = (
                    not existed_before
                    and prompt_path.is_file()
                    and bool(expected_digest)
                    and file_sha256(prompt_path) == expected_digest
                )
            except OSError:
                digest_matches = False
            if digest_matches:
                prompt_path.unlink()
                removed += 1
            elif prompt_path.exists():
                preserved += 1
                reason = (
                    "部署前已存在 / pre-existing"
                    if existed_before
                    else "用户已修改 / user-modified"
                )
                print(f"  已保留文件 / Preserved file ({reason}): {prompt_path.name}")
        state_path = state_file_path(config_path)
        if state_path.exists():
            state_path.unlink()
        print(
            "  提示词状态 / Prompt status: "
            f"已移除 {removed} 个，保留 {preserved} 个 / Removed {removed}, preserved {preserved}"
        )
    return 0


def interactive_action() -> str:
    print(intro_text())
    print(menu_text())
    while True:
        try:
            choice = input("请选择 / Select [1/2/q]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return "quit"
        actions = {
            "1": "apply",
            "2": "reset",
            "q": "quit",
        }
        if choice in actions:
            return actions[choice]
        print("[错误] 请输入 1、2 或 q / Enter 1, 2, or q.")


def inferred_md_filename(source: Path, requested_name: str | None) -> str:
    if requested_name:
        return requested_name if requested_name.endswith(".md") else f"{requested_name}.md"
    return f"{source.stem}.md"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract, deploy, or reset the default gpt-5.6-sol Codex instruction file."
    )
    action_group = parser.add_mutually_exclusive_group()
    action_group.add_argument(
        "--apply",
        action="store_true",
        help="Apply the default v42 instruction archive",
    )
    action_group.add_argument(
        "--reset",
        action="store_true",
        help="Remove managed prompts without replacing config.toml",
    )
    action_group.add_argument(
        "--restore-snapshot",
        metavar="PATH",
        help="Explicitly restore one full config.toml snapshot",
    )
    action_group.add_argument("--file", "-f", help="Apply a custom instruction ZIP or Markdown file")
    parser.add_argument("--name", "-n", help="Destination filename for --file, with or without .md")
    parser.add_argument("--codex-dir", help="Explicit Codex home directory, e.g. ~/.codex")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing files")
    args = parser.parse_args()

    if args.name and not args.file:
        parser.error("--name 仅能与 --file 一起使用 / --name requires --file")

    if args.apply:
        action = "apply"
    elif args.reset:
        action = "reset"
    elif args.restore_snapshot:
        return restore_config_snapshot(args, Path(args.restore_snapshot))
    elif args.file:
        source = Path(args.file).expanduser().resolve()
        return deploy_prompt(args, source, inferred_md_filename(source, args.name))
    else:
        action = interactive_action()

    if action == "quit":
        print("未执行修改 / No modification made.")
        return 0
    if action == "reset":
        return reset_managed_install(args)

    return deploy_prompt(args, DEFAULT_PROMPT_ARCHIVE, DEFAULT_PROMPT_MD_FILENAME)


if __name__ == "__main__":
    raise SystemExit(main())
