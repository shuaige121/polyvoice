#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
skills_dir="${HOME}/.claude/skills"

mkdir -p "${skills_dir}"

for skill in "${repo_root}"/skills/*; do
  [ -d "${skill}" ] || continue
  name="$(basename "${skill}")"
  ln -sfn "${skill}" "${skills_dir}/${name}"
  echo "${skills_dir}/${name} -> ${skill}"
done
