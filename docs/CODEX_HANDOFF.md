# Codex handoff brief

This file is the single source of truth when delegating implementation to Codex (or any coding agent).

## Repo

- Remote: `git@github.com:shuaige121/polyvoice.git`
- Working copy (WSL, primary): `/mnt/wsl/PHYSICALDRIVE1p2/projects/polyvoice`
- If running on `gpu13`: clone fresh under `~/projects/polyvoice`, push feature branches, author opens PRs.

## Goal

Implement [SPEC.md](SPEC.md) Phase 1 → Phase 2 → Phase 3 **in that order**, committing each phase as its own logical sequence of commits (one commit per file group, not one giant commit). Do not skip ahead.

## Boundaries

- **Do not** alter [ARCHITECTURE.md](ARCHITECTURE.md) or [SPEC.md](SPEC.md) without flagging it in the PR description.
- **Do not** remove `venvs/` or `models/` from `.gitignore`.
- **Do not** introduce a new top-level dependency without listing it in `pyproject.toml` with justification.
- **Do not** pin the whole project to torch==2.3.1 in root `pyproject.toml`; that pin belongs only in `venvs/cosyvoice/requirements.txt`.
- When a third-party repo (CosyVoice, sherpa-onnx) exposes an unstable API, wrap it in our adapter — never let upstream types leak into `src/polyvoice/server/`.
- Secrets: no API keys in code. Vocab extractor uses `ANTHROPIC_API_KEY` env.
- Keep commits signed off by the human operator; use `git commit -s` if pre-commit enforces DCO.

## Definition of done

Per phase, run every command under that phase's "verification" section in SPEC.md. All must pass (or be documented as environment-gated with a clear reason).

## Environment assumptions

- Python 3.10+, `uv` available.
- ffmpeg in PATH.
- RTX 5090 (Blackwell, sm_120, CUDA 12.8) on primary dev machine; RTX 5060 Ti (16GB) on `gpu13`.
- PyTorch nightly cu128 on primary; Codex host may need its own torch install per backend venv.
- `~/.claude/projects/` exists and contains real jsonl files (sensitive — do not commit excerpts).

## Reporting

After each phase:
1. Push branch `phase-<n>` and open PR against `main`.
2. In PR body: list verification commands run + their outcome, any deviations from SPEC, open questions.
3. Do not self-merge. Wait for review.

## Questions → ask, don't guess

If SPEC is ambiguous, leave a `TODO(spec):` comment in code and list it in the PR description. Don't invent behavior.
