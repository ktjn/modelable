from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class DescriptorGenerationError(ValueError):
    """Raised when protoc cannot generate a descriptor artifact."""


def compile_descriptor_set(
    *,
    proto_root: Path,
    proto_files: list[Path],
    out_path: Path,
    include_imports: bool = True,
    target_ref: str | None = None,
) -> bytes:
    protoc = shutil.which("protoc")
    if protoc is None:
        raise DescriptorGenerationError("descriptor generation requires protoc on PATH")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    relative_inputs = [_relative_proto_path(proto_root, proto_file) for proto_file in proto_files]
    command = [
        protoc,
        "-I",
        str(proto_root),
        f"--descriptor_set_out={tmp_path}",
    ]
    if include_imports:
        command.append("--include_imports")
    command.extend(relative_inputs)

    result = subprocess.run(
        command,
        cwd=proto_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
        prefix = f"{target_ref}: " if target_ref else ""
        raise DescriptorGenerationError(f"{prefix}protoc failed: {message}")
    try:
        content = tmp_path.read_bytes()
    except OSError as exc:
        prefix = f"{target_ref}: " if target_ref else ""
        raise DescriptorGenerationError(f"{prefix}protoc did not write descriptor output: {tmp_path}") from exc
    tmp_path.replace(out_path)
    return content


def _relative_proto_path(proto_root: Path, proto_file: Path) -> str:
    try:
        return proto_file.relative_to(proto_root).as_posix()
    except ValueError as exc:
        raise DescriptorGenerationError(f"proto file {proto_file} is not under proto root {proto_root}") from exc
