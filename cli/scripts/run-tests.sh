#!/usr/bin/env bash
set -euo pipefail

script_dir="${BASH_SOURCE[0]%/*}"
script_dir="$(cd -- "${script_dir}" && pwd)"
cd -- "${script_dir}/.."

if command -v powershell.exe >/dev/null 2>&1; then
  if command -v wslpath >/dev/null 2>&1; then
    windows_root="$(wslpath -w "$(pwd)")"
  else
    windows_root="$(pwd -W)"
  fi
  pytest_args=()
  for arg in "$@"; do
    escaped_arg="${arg//\'/\'\'}"
    pytest_args+=("'$escaped_arg'")
  done
  args_literal=$(IFS=,; echo "${pytest_args[*]}")
  exec powershell.exe -NoProfile -Command "Set-Location -LiteralPath '${windows_root}'; \$python = Join-Path (Get-Location) '.venv\\Scripts\\python.exe'; \$base = Join-Path (Get-Location) '.pytest-tmp'; \$pytestArgs = @(${args_literal}); & \$python -m pytest --tb=short -n 0 --basetemp \$base @pytestArgs; exit \$LASTEXITCODE"
fi

exec uv run pytest --tb=short -n 0 --basetemp "$(pwd)/.pytest-tmp" "$@"
