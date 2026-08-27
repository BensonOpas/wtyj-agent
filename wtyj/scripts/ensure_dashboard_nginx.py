#!/usr/bin/env python3
"""Apply the dashboard proxy invariants required by the browser client."""

from __future__ import annotations

import argparse
import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Callable


TENANT_HEADER = "X-Unboks-Tenant"
ALI_RENTAL_LOCATION = "/api/ali-car-rental/"
ALI_RENTAL_TENANT = "ali-car-rental"
ALI_RENTAL_BEGIN_MARKER = "# BEGIN UNBOKS TENANT ali-car-rental"
ALI_RENTAL_END_MARKER = "# END UNBOKS TENANT ali-car-rental"
DASHBOARD_CACHE_MARKER = "UNBOKS DASHBOARD APP SHELL CACHE POLICY"
NO_STORE_VALUE = "no-store, no-cache, must-revalidate, max-age=0"


class _Block:
    def __init__(self, start: int, end: int) -> None:
        self.start = start
        self.end = end


class _WritePlan:
    def __init__(
        self,
        target: Path,
        content: str,
        mode: int,
        uid: int,
        gid: int,
    ) -> None:
        self.target = target
        self.content = content
        self.mode = mode
        self.uid = uid
        self.gid = gid
        self.new_path: Path | None = None
        self.rollback_path: Path | None = None


def _scan_nginx_line(line: str) -> tuple[str, int]:
    """Return uncommented code and its structural brace delta."""
    quote: str | None = None
    escaped = False
    result: list[str] = []
    brace_delta = 0
    for character in line:
        if escaped:
            result.append(character)
            escaped = False
            continue
        if character == "\\":
            result.append(character)
            escaped = True
            continue
        if quote:
            result.append(character)
            if character == quote:
                quote = None
            continue
        if character in {'"', "'"}:
            result.append(character)
            quote = character
            continue
        if character == "#":
            break
        if character == "{":
            brace_delta += 1
        elif character == "}":
            brace_delta -= 1
        result.append(character)
    return "".join(result), brace_delta


def _strip_comment(line: str) -> str:
    return _scan_nginx_line(line)[0]


def _brace_delta(line: str) -> int:
    return _scan_nginx_line(line)[1]


def _line_ending(line: str) -> str:
    if line.endswith("\r\n"):
        return "\r\n"
    if line.endswith("\n"):
        return "\n"
    if line.endswith("\r"):
        return "\r"
    return ""


def _default_line_ending(text: str) -> str:
    match = re.search(r"\r\n|\n|\r", text)
    return match.group(0) if match else "\n"


def _matching_block_end(lines: list[str], start: int) -> int:
    depth = 0
    for index in range(start, len(lines)):
        depth += _brace_delta(lines[index])
        if index == start and depth != 1:
            raise ValueError("Nginx location opening line was not recognized")
        if depth == 0:
            return index
        if depth < 0:
            break
    raise ValueError("Nginx location block was not balanced")


def _find_blocks(
    lines: list[str],
    header_matches: Callable[[str], bool],
) -> list[_Block]:
    blocks: list[_Block] = []
    for index, line in enumerate(lines):
        if header_matches(_strip_comment(line).strip()):
            blocks.append(_Block(index, _matching_block_end(lines, index)))
    return blocks


def _block_code(lines: list[str], block: _Block) -> list[tuple[int, int, str]]:
    """Return non-comment block body lines with their pre-line nesting depth."""
    depth = 1
    result: list[tuple[int, int, str]] = []
    for index in range(block.start + 1, block.end):
        uncommented, brace_delta = _scan_nginx_line(lines[index])
        code = uncommented.strip()
        if code:
            result.append((index, depth, code))
        depth += brace_delta
        if depth < 1:
            raise ValueError("Nginx location block was not balanced")
    if depth != 1:
        raise ValueError("Nginx location block was not balanced")
    return result


def _literal_location_header(code: str, path: str, modifier: str = "") -> bool:
    modifier_pattern = rf"{re.escape(modifier)}[ \t]+" if modifier else ""
    return bool(
        re.fullmatch(
            rf"location[ \t]+{modifier_pattern}{re.escape(path)}[ \t]*\{{[ \t]*",
            code,
        )
    )


def _ali_location_header(code: str) -> bool:
    return bool(
        re.fullmatch(
            rf"location[ \t]+(?:\^~[ \t]+)?{re.escape(ALI_RENTAL_LOCATION)}"
            rf"[ \t]*\{{[ \t]*",
            code,
        )
    )


def _is_directive(code: str, directive: str, first_argument: str) -> bool:
    return bool(
        re.match(
            rf"^{re.escape(directive)}[ \t]+{re.escape(first_argument)}"
            rf"(?:[ \t]+|;)",
            code,
        )
    )


def ensure_single_tenant_header(text: str) -> str:
    """Hide Ali's upstream tenant header before adding its proxy-owned value."""
    lines = text.splitlines(keepends=True)
    begin_markers = [
        index
        for index, line in enumerate(lines)
        if line.strip() == ALI_RENTAL_BEGIN_MARKER
    ]
    end_markers = [
        index
        for index, line in enumerate(lines)
        if line.strip() == ALI_RENTAL_END_MARKER
    ]
    if len(begin_markers) != 1 or len(end_markers) != 1:
        raise ValueError("expected exactly one marked Ali rental tenant section")
    blocks = _find_blocks(lines, _ali_location_header)
    if len(blocks) != 1:
        raise ValueError(
            f"expected exactly one location {ALI_RENTAL_LOCATION}, found {len(blocks)}"
        )
    if not (
        begin_markers[0] < blocks[0].start
        and blocks[0].end < end_markers[0]
    ):
        raise ValueError(
            f"location {ALI_RENTAL_LOCATION} is outside its Ali rental tenant markers"
        )

    code_lines = _block_code(lines, blocks[0])
    tenant_headers = [
        item
        for item in code_lines
        if _is_directive(item[2], "add_header", TENANT_HEADER)
    ]
    if len(tenant_headers) != 1 or tenant_headers[0][1] != 1:
        raise ValueError(
            f"location {ALI_RENTAL_LOCATION} must have exactly one direct "
            f"add_header {TENANT_HEADER} directive"
        )
    expected_header = re.fullmatch(
        rf"add_header[ \t]+{re.escape(TENANT_HEADER)}[ \t]+"
        rf"(?:\"{ALI_RENTAL_TENANT}\"|'{ALI_RENTAL_TENANT}'|{ALI_RENTAL_TENANT})"
        rf"[ \t]+always[ \t]*;",
        tenant_headers[0][2],
    )
    if not expected_header:
        raise ValueError(
            f"location {ALI_RENTAL_LOCATION} has an unexpected {TENANT_HEADER} value"
        )

    hidden_headers = [
        item
        for item in code_lines
        if _is_directive(item[2], "proxy_hide_header", TENANT_HEADER)
    ]
    if len(hidden_headers) > 1 or (
        hidden_headers
        and (
            hidden_headers[0][1] != 1
            or not re.fullmatch(
                rf"proxy_hide_header[ \t]+{re.escape(TENANT_HEADER)}[ \t]*;",
                hidden_headers[0][2],
            )
        )
    ):
        raise ValueError(
            f"location {ALI_RENTAL_LOCATION} has an ambiguous proxy_hide_header directive"
        )
    if hidden_headers:
        return text

    header_index = tenant_headers[0][0]
    header_line = lines[header_index]
    indent = header_line[: len(header_line) - len(header_line.lstrip(" \t"))]
    newline = _line_ending(header_line) or _default_line_ending(text)
    lines.insert(
        header_index,
        f"{indent}proxy_hide_header {TENANT_HEADER};{newline}",
    )
    return "".join(lines)


def _has_one_direct_no_store(lines: list[str], block: _Block) -> bool:
    directives = [
        item
        for item in _block_code(lines, block)
        if _is_directive(item[2], "add_header", "Cache-Control")
    ]
    if len(directives) != 1 or directives[0][1] != 1:
        return False
    return bool(
        re.fullmatch(
            rf"add_header[ \t]+Cache-Control[ \t]+"
            rf"(?:\"{re.escape(NO_STORE_VALUE)}\"|'{re.escape(NO_STORE_VALUE)}')"
            rf"[ \t]+always[ \t]*;",
            directives[0][2],
        )
    )


def _is_spa_fallback(code: str) -> bool:
    return bool(
        re.fullmatch(
            r"try_files[ \t]+\$uri[ \t]+\$uri/[ \t]+/index\.html[ \t]*;",
            code,
        )
    )


def _has_one_direct_spa_fallback(lines: list[str], block: _Block) -> bool:
    directives = [
        item
        for item in _block_code(lines, block)
        if re.match(r"^try_files(?:[ \t]+|;)", item[2])
    ]
    return (
        len(directives) == 1
        and directives[0][1] == 1
        and _is_spa_fallback(directives[0][2])
    )


def _legacy_root_fallback(
    lines: list[str],
    block: _Block,
) -> str | None:
    code_lines = _block_code(lines, block)
    if len(code_lines) != 1:
        return None
    index, depth, code = code_lines[0]
    if depth != 1 or not _is_spa_fallback(code):
        return None
    line = lines[index]
    return line[: len(line) - len(line.lstrip(" \t"))]


def ensure_dashboard_shell_no_store(text: str) -> str:
    """Keep SPA HTML fresh while leaving unrelated locations byte-identical."""
    lines = text.splitlines(keepends=True)
    index_blocks = _find_blocks(
        lines,
        lambda code: _literal_location_header(code, "/index.html", "="),
    )
    root_blocks = _find_blocks(
        lines,
        lambda code: _literal_location_header(code, "/"),
    )

    if len(index_blocks) == 1 and len(root_blocks) == 1:
        if (
            _has_one_direct_no_store(lines, index_blocks[0])
            and _has_one_direct_no_store(lines, root_blocks[0])
            and _has_one_direct_spa_fallback(lines, root_blocks[0])
        ):
            return text
        raise ValueError("dashboard app-shell cache policy is incomplete or ambiguous")

    if DASHBOARD_CACHE_MARKER in text:
        raise ValueError("dashboard app-shell cache policy marker is incomplete")
    if index_blocks or len(root_blocks) != 1:
        raise ValueError(
            "dashboard requires exactly one legacy root location or one complete app-shell policy"
        )

    root = root_blocks[0]
    legacy = _legacy_root_fallback(lines, root)
    if legacy is None:
        raise ValueError("dashboard SPA location block was not recognized")

    directive_indent = legacy
    header_line = lines[root.start]
    block_indent = header_line[: len(header_line) - len(header_line.lstrip(" \t"))]
    newline = _line_ending(header_line) or _default_line_ending(text)
    replacement_lines = [
        f"{block_indent}# BEGIN {DASHBOARD_CACHE_MARKER}",
        f"{block_indent}# Hashed static assets retain their long-lived policy below.",
        f"{block_indent}location = /index.html {{",
        f"{directive_indent}expires -1;",
        f'{directive_indent}add_header Cache-Control "{NO_STORE_VALUE}" always;',
        f'{directive_indent}add_header Pragma "no-cache" always;',
        f"{block_indent}}}",
        "",
        f"{block_indent}location / {{",
        f"{directive_indent}expires -1;",
        f'{directive_indent}add_header Cache-Control "{NO_STORE_VALUE}" always;',
        f'{directive_indent}add_header Pragma "no-cache" always;',
        f"{directive_indent}try_files $uri $uri/ /index.html;",
        f"{block_indent}}}",
        f"{block_indent}# END {DASHBOARD_CACHE_MARKER}",
    ]
    replacement = newline.join(replacement_lines)
    if _line_ending(lines[root.end]):
        replacement += newline
    lines[root.start : root.end + 1] = replacement.splitlines(keepends=True)
    return "".join(lines)


def _read_text(path: Path) -> str:
    with path.open("r", encoding="utf-8", newline="") as stream:
        return stream.read()


def _stage_file(
    target: Path,
    content: str,
    mode: int,
    uid: int,
    gid: int,
    purpose: str,
) -> Path:
    descriptor, name = tempfile.mkstemp(
        prefix=f".{target.name}.{purpose}.",
        dir=target.parent,
    )
    path = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(content)
            stream.flush()
            os.fchown(stream.fileno(), uid, gid)
            os.fchmod(stream.fileno(), stat.S_IMODE(mode))
            os.fsync(stream.fileno())
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        path.unlink(missing_ok=True)
        raise
    return path


def _fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(directory, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _remove_staged_files(plans: list[_WritePlan]) -> None:
    for plan in plans:
        for path in (plan.new_path, plan.rollback_path):
            if path is not None:
                path.unlink(missing_ok=True)


def atomic_write_many(files: dict[str, tuple[Path, str]]) -> dict[str, bool]:
    """Replace all changed real files, or restore every replacement on failure."""
    changed = {label: False for label in files}
    plans: list[_WritePlan] = []
    resolved_targets: dict[Path, str] = {}

    for label, (logical_path, content) in files.items():
        target = logical_path.resolve(strict=True)
        target_stat = target.stat()
        if not stat.S_ISREG(target_stat.st_mode):
            raise ValueError(f"{logical_path} does not resolve to a regular file")
        if target in resolved_targets:
            raise ValueError(
                f"{label} and {resolved_targets[target]} resolve to the same file: {target}"
            )
        resolved_targets[target] = label
        current = _read_text(target)
        if current != content:
            changed[label] = True
            plans.append(
                _WritePlan(
                    target,
                    content,
                    target_stat.st_mode,
                    target_stat.st_uid,
                    target_stat.st_gid,
                )
            )

    try:
        for plan in plans:
            original = _read_text(plan.target)
            plan.new_path = _stage_file(
                plan.target,
                plan.content,
                plan.mode,
                plan.uid,
                plan.gid,
                "new",
            )
            plan.rollback_path = _stage_file(
                plan.target,
                original,
                plan.mode,
                plan.uid,
                plan.gid,
                "rollback",
            )
    except BaseException:
        _remove_staged_files(plans)
        raise

    attempted: list[_WritePlan] = []
    try:
        for plan in plans:
            attempted.append(plan)
            assert plan.new_path is not None
            os.replace(plan.new_path, plan.target)
            plan.new_path = None
            _fsync_directory(plan.target.parent)
    except BaseException as write_error:
        rollback_errors: list[str] = []
        for plan in reversed(attempted):
            try:
                assert plan.rollback_path is not None
                os.replace(plan.rollback_path, plan.target)
                plan.rollback_path = None
                _fsync_directory(plan.target.parent)
            except BaseException as rollback_error:
                rollback_errors.append(f"{plan.target}: {rollback_error}")
        _remove_staged_files(plans)
        if rollback_errors:
            raise RuntimeError(
                "configuration write failed and rollback was incomplete: "
                + "; ".join(rollback_errors)
            ) from write_error
        raise

    _remove_staged_files(plans)
    return changed


def atomic_write(path: Path, content: str) -> bool:
    """Atomically update one file without replacing its symlink."""
    return atomic_write_many({"file": (path, content)})["file"]


def apply_config_updates(api_config: Path, dashboard_config: Path) -> dict[str, bool]:
    """Validate both transformations before replacing either config file."""
    api_updated = ensure_single_tenant_header(_read_text(api_config))
    dashboard_updated = ensure_dashboard_shell_no_store(_read_text(dashboard_config))
    return atomic_write_many(
        {
            "api": (api_config, api_updated),
            "dashboard": (dashboard_config, dashboard_updated),
        }
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-config", required=True, type=Path)
    parser.add_argument("--dashboard-config", required=True, type=Path)
    args = parser.parse_args()

    print(apply_config_updates(args.api_config, args.dashboard_config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
