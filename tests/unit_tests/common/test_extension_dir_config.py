from __future__ import annotations

from pathlib import Path

import pytest
from dotenv import dotenv_values

from jiuwenswarm.common import extension_dir_config
from jiuwenswarm.common.extension_dir_config import (
    EXTENSION_DIRS_ENV,
    MANAGED_MARKER_ENV,
    migrate_extension_dirs,
)


def _packaged_extensions_dir() -> Path:
    return Path(extension_dir_config.__file__).resolve().parent.parent / "extensions"


def test_blank_template_assignment_is_filled_in_place(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "KEEP=value\n"
        "# Extension package search dirs, separated by ';'\n"
        'EXTENSION_DIRS=""\n'
        "OTHER=1\n",
        encoding="utf-8",
    )
    environ: dict[str, str] = {}

    value = migrate_extension_dirs(env_path, environ=environ)

    assert value == str(_packaged_extensions_dir())
    assert environ[EXTENSION_DIRS_ENV] == value
    # Single quotes: python-dotenv interprets backslash escapes inside double
    # quotes, which would corrupt Windows paths.
    assert env_path.read_text(encoding="utf-8") == (
        "KEEP=value\n"
        "# Extension package search dirs, separated by ';'\n"
        f"EXTENSION_DIRS='{value}'\n"
        "OTHER=1\n"
        f"{MANAGED_MARKER_ENV}='{value}'\n"
    )


def test_missing_assignment_is_appended_once(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("KEEP=value", encoding="utf-8")
    environ: dict[str, str] = {}

    first = migrate_extension_dirs(env_path, environ=environ)
    written = env_path.read_text(encoding="utf-8")
    second = migrate_extension_dirs(env_path, environ=environ)

    assert first == second == str(_packaged_extensions_dir())
    assert written == (
        f"KEEP=value\nEXTENSION_DIRS='{first}'\n{MANAGED_MARKER_ENV}='{first}'\n"
    )
    assert env_path.read_text(encoding="utf-8") == written


def test_windows_path_survives_the_dotenv_round_trip(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text('EXTENSION_DIRS=""\n', encoding="utf-8")
    windows_value = r"C:\Users\O'Brien\ext;C:\temp\tools"

    migrate_extension_dirs(env_path, environ={EXTENSION_DIRS_ENV: windows_value})

    assert dotenv_values(env_path)[EXTENSION_DIRS_ENV] == windows_value


def test_operator_value_is_kept_and_never_marked_managed(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    original = 'EXTENSION_DIRS="/opt/exts;/srv/more"\n'
    env_path.write_text(original, encoding="utf-8")
    environ: dict[str, str] = {}

    value = migrate_extension_dirs(env_path, environ=environ)

    assert value == "/opt/exts;/srv/more"
    assert environ[EXTENSION_DIRS_ENV] == value
    # No managed marker: the value is the operator's, and a marker would invite
    # the next start to recompute it.
    assert env_path.read_text(encoding="utf-8") == original


def test_operator_value_survives_repeated_startups(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    original = 'EXTENSION_DIRS="/opt/exts"\n'
    env_path.write_text(original, encoding="utf-8")

    for _ in range(3):
        assert migrate_extension_dirs(env_path, environ={}) == "/opt/exts"

    assert env_path.read_text(encoding="utf-8") == original


def test_populated_assignment_is_replaced_whole_not_prefixed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_install = tmp_path / "old" / "jiuwenswarm" / "extensions"
    new_install = tmp_path / "new" / "jiuwenswarm" / "extensions"
    old_install.mkdir(parents=True)
    new_install.mkdir(parents=True)
    env_path = tmp_path / ".env"

    monkeypatch.setattr(extension_dir_config, "packaged_extensions_dir", lambda: old_install)
    migrate_extension_dirs(env_path, environ={})

    monkeypatch.setattr(extension_dir_config, "packaged_extensions_dir", lambda: new_install)
    migrate_extension_dirs(env_path, environ={})

    text = env_path.read_text(encoding="utf-8")
    # Replacing only the value left the old text behind as a stray line, which
    # then read back as the effective setting on the next dotenv load.
    assert str(old_install) not in text
    assert dotenv_values(env_path)[EXTENSION_DIRS_ENV] == str(new_install)


def test_derived_value_is_recomputed_when_the_install_moves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_install = tmp_path / "old" / "jiuwenswarm" / "extensions"
    new_install = tmp_path / "new" / "jiuwenswarm" / "extensions"
    old_install.mkdir(parents=True)
    new_install.mkdir(parents=True)
    env_path = tmp_path / ".env"

    monkeypatch.setattr(
        extension_dir_config, "packaged_extensions_dir", lambda: old_install
    )
    assert migrate_extension_dirs(env_path, environ={}) == str(old_install)

    monkeypatch.setattr(
        extension_dir_config, "packaged_extensions_dir", lambda: new_install
    )
    assert migrate_extension_dirs(env_path, environ={}) == str(new_install)
    assert dotenv_values(env_path)[EXTENSION_DIRS_ENV] == str(new_install)


def test_operator_value_survives_an_install_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text('EXTENSION_DIRS="/opt/exts"\n', encoding="utf-8")
    monkeypatch.setattr(
        extension_dir_config, "packaged_extensions_dir", lambda: tmp_path / "absent"
    )

    assert migrate_extension_dirs(env_path, environ={}) == "/opt/exts"
    assert dotenv_values(env_path)[EXTENSION_DIRS_ENV] == "/opt/exts"


def test_managed_value_yields_to_an_operator_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    derived = tmp_path / "derived" / "extensions"
    derived.mkdir(parents=True)
    env_path = tmp_path / ".env"
    monkeypatch.setattr(extension_dir_config, "packaged_extensions_dir", lambda: derived)
    assert migrate_extension_dirs(env_path, environ={}) == str(derived)

    env_path.write_text('EXTENSION_DIRS="/opt/exts"\n', encoding="utf-8")
    assert migrate_extension_dirs(env_path, environ={}) == "/opt/exts"
    # The record of our derived value must be cleared, or the next start
    # recomputes over this value.
    persisted = dotenv_values(env_path)
    assert persisted[EXTENSION_DIRS_ENV] == "/opt/exts"
    assert not (persisted.get(MANAGED_MARKER_ENV) or "").strip()
    assert migrate_extension_dirs(env_path, environ={}) == "/opt/exts"


def test_duplicate_assignments_are_collapsed_to_one(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        'EXTENSION_DIRS=""\nKEEP=value\nEXTENSION_DIRS=""\n',
        encoding="utf-8",
    )

    migrate_extension_dirs(env_path, environ={EXTENSION_DIRS_ENV: "/new"})

    text = env_path.read_text(encoding="utf-8")
    # dotenv resolves a repeated key to the last occurrence, so a surviving
    # duplicate would beat the value written here.
    assert text.count("EXTENSION_DIRS=") == 1
    assert dotenv_values(env_path)[EXTENSION_DIRS_ENV] == "/new"


def test_process_environment_value_is_persisted_for_the_gateway(
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text('EXTENSION_DIRS=""\n', encoding="utf-8")
    environ = {EXTENSION_DIRS_ENV: "/from/shell"}

    assert migrate_extension_dirs(env_path, environ=environ) == "/from/shell"
    assert environ[EXTENSION_DIRS_ENV] == "/from/shell"
    # The Gateway reloads .env with override=True, so a shell export alone is
    # replaced by the blank template line; the value must reach the file.
    assert dotenv_values(env_path)[EXTENSION_DIRS_ENV] == "/from/shell"


def test_agentos_runtime_never_writes_deployment_owned_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JIUWENSWARM_RUNTIME_PROFILE", "agentos")
    env_path = tmp_path / ".env"
    original = 'EXTENSION_DIRS=""\n'
    env_path.write_text(original, encoding="utf-8")
    environ: dict[str, str] = {}

    assert migrate_extension_dirs(env_path, environ=environ) is None
    assert environ == {}
    assert env_path.read_text(encoding="utf-8") == original


def test_missing_packaged_extensions_dir_leaves_env_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        extension_dir_config,
        "packaged_extensions_dir",
        lambda: tmp_path / "absent",
    )
    env_path = tmp_path / ".env"
    original = 'EXTENSION_DIRS=""\n'
    env_path.write_text(original, encoding="utf-8")

    assert migrate_extension_dirs(env_path, environ={}) is None
    assert env_path.read_text(encoding="utf-8") == original


def test_unwritable_env_is_reported_without_breaking_startup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text('EXTENSION_DIRS=""\n', encoding="utf-8")

    def _boom(_path: Path, _content: str) -> None:
        raise OSError("read-only filesystem")

    monkeypatch.setattr(extension_dir_config, "_write_env_atomic", _boom)

    assert migrate_extension_dirs(env_path, environ={}) is None
    assert env_path.read_text(encoding="utf-8") == 'EXTENSION_DIRS=""\n'


def test_existing_env_file_keeps_its_mode(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text('EXTENSION_DIRS=""\n', encoding="utf-8")
    env_path.chmod(0o600)

    migrate_extension_dirs(env_path, environ={})

    assert (env_path.stat().st_mode & 0o777) == 0o600
