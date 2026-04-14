"""WSL Claude Code vocabulary scanner for the Windows app."""

from __future__ import annotations

import getpass
import json
import logging
import math
import os
import re
import subprocess
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

try:  # PySide6 is present in the app, but keeping import lazy helps headless tests.
    from PySide6.QtCore import QObject, Signal, Slot
except Exception:  # pragma: no cover - fallback only used when GUI deps are absent
    QObject = object  # type: ignore[assignment,misc]

    class Signal:  # type: ignore[no-redef]
        def __init__(self, *_args: object) -> None:
            self._callbacks: list[Callable[..., None]] = []

        def connect(self, callback: Callable[..., None]) -> None:
            self._callbacks.append(callback)

        def emit(self, *args: object) -> None:
            for callback in list(self._callbacks):
                callback(*args)

    def Slot(*_args: object, **_kwargs: object) -> Callable[[Callable[..., Any]], Callable[..., Any]]:  # type: ignore[misc]
        return lambda func: func

import jieba
from wordfreq import zipf_frequency

from polyvoice_app import paths

logger = logging.getLogger("polyvoice.vocab")

SCHEMA_VERSION = 1
SOURCE_NAME = "wsl-claude"
POLYVOICE_SOURCE = "polyvoice-windows-wsl"

SYSTEM_TAG_NAMES = (
    "task-notification",
    "local-command-caveat",
    "command-name",
    "command-message",
    "command-args",
    "local-command-stdout",
    "local-command-stderr",
    "command-stdout",
    "command-stderr",
    "bash-input",
    "bash-stdout",
    "bash-stderr",
    "function_calls",
    "function_result",
    "user-prompt-submit-hook",
    "ide_opened_file",
    "files-attached",
    "policy-spec",
    "system-reminder",
)

SYSTEM_TAG = re.compile(
    rf"<({'|'.join(re.escape(name) for name in SYSTEM_TAG_NAMES)})(?:\s[^>]*)?>.*?</\1>",
    re.DOTALL | re.IGNORECASE,
)
CODE_BLOCK = re.compile(r"```.*?```", re.DOTALL)
INLINE_CODE = re.compile(r"`[^`]+`")
URL = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
PATH_RE = re.compile(r"(?<!\w)(?:~|\.{1,2})?/[\w./@%+=:,;~#-]+|[A-Za-z]:\\[^\s]+")
JSON_FIELD = re.compile(r'"[A-Za-z_][\w_]*"\s*:')
WHITESPACE = re.compile(r"\s+")
SKIP_MARKERS = (
    "[Request interrupted",
    "<function_calls>",
    "<function_result>",
    "<ide_opened_file>",
    "<files-attached>",
)

STOP_EN = {
    "the",
    "a",
    "an",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "will",
    "would",
    "should",
    "could",
    "can",
    "may",
    "might",
    "must",
    "i",
    "you",
    "he",
    "she",
    "it",
    "we",
    "they",
    "this",
    "that",
    "these",
    "those",
    "and",
    "or",
    "but",
    "if",
    "then",
    "else",
    "when",
    "where",
    "why",
    "how",
    "what",
    "in",
    "on",
    "at",
    "to",
    "for",
    "of",
    "with",
    "from",
    "by",
    "as",
    "about",
    "not",
    "no",
    "yes",
    "ok",
    "okay",
    "http",
    "https",
    "www",
    "com",
    "org",
}

SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bcfat_[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{16,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\b[0-9a-fA-F]{32,64}\b"),
    re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"),
    re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    URL,
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*(?:TOKEN|SECRET|PASSWORD|API_KEY|ACCESS_KEY)\b"),
    re.compile(r"\b[A-Za-z0-9+/]{32,}={0,2}\b"),
)

CAMEL_OR_ACRONYM = re.compile(r"\b[A-Z][a-zA-Z0-9]*[A-Z][a-zA-Z0-9]*\b|\b[A-Z]{2,}\b")
ASCII_TERM = re.compile(r"\b[A-Za-z][A-Za-z0-9_.-]{1,}[A-Za-z0-9]\b")
TOKEN_SPLIT = re.compile(r"\s+")
CAMEL = re.compile(r"^[A-Z][a-zA-Z0-9]*[A-Z][a-zA-Z0-9]*$")
ALL_CAPS = re.compile(r"^[A-Z0-9_]{2,12}$")
ID_LIKE = re.compile(r"^(?=.*\d)(?=.*_)[A-Za-z0-9_]+$")
SHORT_HEX = re.compile(r"^(?:0x)?[0-9a-fA-F]{4,31}$")


@dataclass(frozen=True)
class WslProjectRoot:
    distro: str
    user: str
    path: Path
    unc_prefix: str


@dataclass(frozen=True)
class VocabScanResult:
    distros: list[str]
    roots: list[WslProjectRoot]
    messages: int
    candidates: int
    curated: int
    master_entries: int
    hotwords_path: Path
    master_path: Path


class VocabScanWorker(QObject):
    progress = Signal(str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, distro: str | None = None) -> None:
        super().__init__()
        self.distro = distro

    @Slot()
    def run(self) -> None:
        try:
            result = refresh_from_wsl(self.distro, progress=self.progress.emit)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
        else:
            self.finished.emit(result)


def refresh_from_wsl(
    distro: str | None = None,
    *,
    progress: Callable[[str], None] | None = None,
    limit: int = 400,
) -> VocabScanResult:
    """Scan detected WSL Claude transcripts and write hotwords/master vocab."""
    paths.ensure_app_dirs()
    emit = progress or (lambda _message: None)
    distros = [distro] if distro else enumerate_wsl_distros()
    emit(f"found {len(distros)} WSL distro(s)")
    roots: list[WslProjectRoot] = []
    for name in distros:
        emit(f"probing {name}")
        roots.extend(find_claude_project_roots(name))

    records: list[dict[str, Any]] = []
    for root in roots:
        emit(f"scanning {root.distro}:{root.user}")
        records.extend(iter_messages(root.path, root))

    emit(f"extracting {len(records)} message(s)")
    candidates = build_candidates(records, limit=limit)
    curated = curate_rows(candidates)
    master_entries = merge_vocab(paths.master_vocab_path(), curated)
    write_hotwords(paths.hotwords_path(), paths.master_vocab_path())
    emit(f"wrote {paths.hotwords_path()}")

    result = VocabScanResult(
        distros=distros,
        roots=roots,
        messages=len(records),
        candidates=len(candidates),
        curated=len(curated),
        master_entries=master_entries,
        hotwords_path=paths.hotwords_path(),
        master_path=paths.master_vocab_path(),
    )
    logger.info(
        "vocab refresh completed",
        extra={
            "event": "vocab_refresh_completed",
            "distros": len(distros),
            "roots": len(roots),
            "messages": result.messages,
            "candidates": result.candidates,
            "curated": result.curated,
            "master_entries": result.master_entries,
        },
    )
    return result


def enumerate_wsl_distros(timeout_s: float = 5.0) -> list[str]:
    result = subprocess.run(  # noqa: S603
        ["wsl.exe", "-l", "-q"],
        check=False,
        capture_output=True,
        timeout=timeout_s,
    )
    output = result.stdout
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-16-le", errors="ignore") or result.stderr.decode(errors="ignore")
        raise RuntimeError(f"wsl.exe -l -q failed: {stderr.strip()}")
    text = _decode_wsl_output(output)
    return [line.strip().replace("\x00", "") for line in text.splitlines() if line.strip().replace("\x00", "")]


def find_claude_project_roots(distro: str) -> list[WslProjectRoot]:
    start_wsl_distro(distro)
    out: list[WslProjectRoot] = []
    seen: set[tuple[str, str]] = set()
    for prefix in (r"\\wsl.localhost", r"\\wsl$"):
        home_root = Path(f"{prefix}\\{distro}\\home")
        for user in _candidate_users(home_root):
            key = (prefix, user)
            if key in seen:
                continue
            seen.add(key)
            project_root = home_root / user / ".claude" / "projects"
            if _is_dir(project_root):
                out.append(WslProjectRoot(distro=distro, user=user, path=project_root, unc_prefix=prefix))
    return out


def start_wsl_distro(distro: str, timeout_s: float = 8.0) -> None:
    try:
        subprocess.run(  # noqa: S603
            ["wsl.exe", "-d", distro, "true"],
            check=False,
            capture_output=True,
            timeout=timeout_s,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        logger.warning("wsl distro start failed", extra={"event": "wsl_start_failed", "distro": distro})


def iter_messages(root: Path, source: WslProjectRoot | None = None) -> Iterable[dict[str, Any]]:
    """Yield cleaned user text messages from Claude Code JSONL transcripts."""
    for path in sorted(root.glob("*/*.jsonl")):
        session_id = path.stem
        try:
            handle = path.open(encoding="utf-8")
        except OSError:
            continue
        with handle:
            for line in handle:
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                message = payload.get("message", payload)
                if not isinstance(message, dict) or message.get("role") != "user":
                    continue
                for text in _content_to_texts(message.get("content")):
                    if any(marker in text for marker in SKIP_MARKERS):
                        continue
                    cleaned = clean_text(text)
                    if not cleaned or _looks_like_pasted_data(cleaned):
                        continue
                    item = {
                        "session_id": session_id,
                        "role": "user",
                        "type": "text",
                        "text": cleaned,
                        "ts": payload.get("timestamp") or payload.get("ts"),
                    }
                    if source:
                        item["source"] = f"{source.distro}:{source.user}:{path.name}"
                    yield item


def clean_text(text: str) -> str:
    text = SYSTEM_TAG.sub(" ", text)
    text = CODE_BLOCK.sub(" ", text)
    text = INLINE_CODE.sub(" ", text)
    text = URL.sub(" ", text)
    text = PATH_RE.sub(" ", text)
    text = redact(text)
    return WHITESPACE.sub(" ", text).strip()


def build_candidates(records: list[dict[str, Any]], *, limit: int = 400) -> list[dict[str, Any]]:
    tf: Counter[str] = Counter()
    snippets: dict[str, list[dict[str, str]]] = defaultdict(list)
    sources: dict[str, set[str]] = defaultdict(set)
    camel_bonus: Counter[str] = Counter()

    for record in records:
        text = str(record.get("text", ""))
        session_id = str(record.get("session_id", ""))
        for token in jieba.lcut(text):
            _add_token(token, record, tf, snippets, sources)
        for match in CAMEL_OR_ACRONYM.findall(text):
            camel_bonus[match] += 1
            _add_token(match, record, tf, snippets, sources)
        for match in ASCII_TERM.findall(text):
            if match in tf:
                sources[match].add(session_id)

    ranked: list[dict[str, Any]] = []
    for term, count in tf.items():
        if count < 2 or is_secret(term) or not _valid_term(term):
            continue
        zipf = term_zipf(term)
        if zipf >= 4.5:
            continue
        score = count * max(0.5, 8.0 - zipf)
        camel = term in camel_bonus
        if camel:
            score *= 1.5
        lang = detect_lang(term)
        ranked.append(
            {
                "schema_version": SCHEMA_VERSION,
                "term": term,
                "phrase": term,
                "lang": lang,
                "score": round(score, 3),
                "count": count,
                "zipf": round(zipf, 3),
                "camel": camel,
                "sources": sorted(source for source in sources[term] if source),
                "snippets": snippets[term][:3],
            }
        )
    ranked.sort(key=lambda item: (-float(item["score"]), str(item["term"]).lower()))
    return ranked[:limit]


def curate_rows(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for item in candidates:
        term = str(item.get("phrase") or item.get("term") or "").strip()
        if not _keep(term):
            continue
        lang = str(item.get("lang") or detect_lang(term))
        out.append(
            {
                "schema_version": SCHEMA_VERSION,
                "phrase": term,
                "lang": lang,
                "category": _category(term, lang),
                "aliases": _aliases(term),
                "count": int(item.get("count", 1) or 1),
                "score": float(item.get("score", 1.0) or 1.0),
                "sources": sorted(set(item.get("sources", []) or [SOURCE_NAME])),
                "snippets": item.get("snippets", [])[:3],
                "decision": "keep",
                "curation_mode": "heuristic",
            }
        )
    return out


def merge_vocab(master_path: Path, curated: list[dict[str, Any]]) -> int:
    entries = _read_master(master_path)
    now = datetime.now().isoformat(timespec="seconds")
    for item in curated:
        _merge_item(entries, item, source=POLYVOICE_SOURCE, now=now)
    master_path.parent.mkdir(parents=True, exist_ok=True)
    with master_path.open("w", encoding="utf-8") as handle:
        for item in sorted(entries.values(), key=lambda value: _sort_key(value)):
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    return len(entries)


def write_hotwords(hotwords_path: Path, master_path: Path) -> int:
    entries = list(_read_jsonl(master_path))
    phrases = sorted({str(item.get("phrase", "")).strip() for item in entries if str(item.get("phrase", "")).strip()})
    hotwords_path.parent.mkdir(parents=True, exist_ok=True)
    hotwords_path.write_text("\n".join(phrases) + ("\n" if phrases else ""), encoding="utf-8")
    return len(phrases)


def detect_lang(term: str) -> str:
    has_cjk = any("\u4e00" <= char <= "\u9fff" for char in term)
    has_ascii = any("A" <= char <= "z" for char in term)
    if has_cjk and has_ascii:
        return "mixed"
    if has_cjk:
        return "zh"
    return "en"


def term_zipf(term: str) -> float:
    if detect_lang(term) == "zh":
        return zipf_frequency(term, "zh")
    return max(zipf_frequency(term, "en"), zipf_frequency(term.lower(), "en"))


def is_secret(term: str) -> bool:
    value = term.strip()
    if not value:
        return False
    return any(pattern.search(value) for pattern in SECRET_PATTERNS)


def redact(text: str) -> str:
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def has_wsl_claude_projects() -> bool:
    for distro in enumerate_wsl_distros():
        if find_claude_project_roots(distro):
            return True
    return False


def _decode_wsl_output(output: bytes) -> str:
    if output.startswith(b"\xff\xfe") or b"\x00" in output[:12]:
        return output.decode("utf-16-le", errors="ignore").replace("\ufeff", "")
    return output.decode("utf-8", errors="ignore")


def _candidate_users(home_root: Path) -> list[str]:
    users = []
    current = os.environ.get("USERNAME") or getpass.getuser()
    for user in (current, "root"):
        if user and user not in users:
            users.append(user)
    try:
        for child in sorted(home_root.iterdir(), key=lambda item: item.name.lower()):
            if child.is_dir() and child.name not in users:
                users.append(child.name)
    except OSError:
        pass
    return users


def _is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def _content_to_texts(content: Any) -> list[str]:
    if isinstance(content, str):
        return [content]
    if isinstance(content, list):
        out = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                out.append(str(item.get("text", "")))
        return out
    return []


def _looks_like_pasted_data(text: str) -> bool:
    if len(text) > 600:
        return True
    if len(JSON_FIELD.findall(text)) >= 3:
        return True
    return text.count("{") + text.count("}") > 4


def _add_token(
    token: str,
    record: dict[str, Any],
    tf: Counter[str],
    snippets: dict[str, list[dict[str, str]]],
    sources: dict[str, set[str]],
) -> None:
    term = token.strip()
    if not term or term.isdigit() or is_secret(term) or not _valid_term(term):
        return
    tf[term] += 1
    session_id = str(record.get("session_id", ""))
    sources[term].add(session_id)
    if len(snippets[term]) < 3:
        text = _snippet(str(record.get("text", "")), term)
        if text:
            snippets[term].append({"session_id": session_id, "text": text})


def _valid_term(term: str) -> bool:
    if all(not char.isalnum() and not ("\u4e00" <= char <= "\u9fff") for char in term):
        return False
    if detect_lang(term) == "zh":
        return len(term) >= 2
    return len(term) >= 2 and term.lower() not in STOP_EN and any(char.isalpha() for char in term)


def _snippet(text: str, term: str) -> str:
    text = redact(text)
    idx = text.lower().find(term.lower())
    if idx < 0:
        return text[:80]
    start = max(0, idx - 30)
    end = min(len(text), idx + len(term) + 30)
    return TOKEN_SPLIT.sub(" ", text[start:end]).strip()[:80]


def _keep(term: str) -> bool:
    if is_secret(term):
        return False
    if SHORT_HEX.match(term):
        return False
    if len(term) < 2 or len(term) > 80:
        return False
    if term.count("/") or term.count("\\"):
        return False
    if term.startswith(("-", ".")) or term.endswith(("-", ".")):
        return False
    if not any(char.isalpha() or "\u4e00" <= char <= "\u9fff" for char in term):
        return False
    return True


def _category(term: str, lang: str) -> str:
    if CAMEL.match(term) or ALL_CAPS.match(term):
        return "acronym" if ALL_CAPS.match(term) else "library"
    if lang in {"zh", "mixed"} and any("\u4e00" <= char <= "\u9fff" for char in term):
        return "domain"
    if ID_LIKE.match(term):
        return "id"
    return "domain"


def _aliases(term: str) -> list[str]:
    aliases = []
    lower = term.lower()
    if lower != term and (CAMEL.match(term) or ALL_CAPS.match(term)):
        aliases.append(lower)
    return aliases


def _read_master(path: Path) -> dict[str, dict[str, Any]]:
    out = {}
    for item in _read_jsonl(path):
        phrase = str(item.get("phrase", "")).strip()
        if not phrase:
            continue
        lang = str(item.get("lang", "mixed"))
        item["schema_version"] = SCHEMA_VERSION
        out[_norm(phrase, lang)] = item
    return out


def _merge_item(entries: dict[str, dict[str, Any]], item: dict[str, Any], *, source: str, now: str) -> None:
    phrase = str(item.get("phrase") or item.get("term") or "").strip()
    if not phrase:
        return
    lang = str(item.get("lang", "mixed"))
    key = _norm(phrase, lang)
    count = max(1, int(item.get("count", 1) or 1))
    existing = entries.get(key)
    if existing is None:
        existing = {
            "schema_version": SCHEMA_VERSION,
            "phrase": phrase,
            "lang": lang,
            "category": item.get("category", "domain"),
            "aliases": [],
            "first_seen": item.get("first_seen") or now,
            "last_seen": now,
            "count": 0,
            "sources": [],
            "weight": 1.0,
        }
        entries[key] = existing

    if not existing.get("manual"):
        existing["category"] = existing.get("category") or item.get("category", "domain")
    existing["schema_version"] = SCHEMA_VERSION
    existing["count"] = int(existing.get("count", 0)) + count
    existing["first_seen"] = existing.get("first_seen") or now
    existing["last_seen"] = now
    existing["sources"] = sorted({*existing.get("sources", []), source, *item.get("sources", [])})
    existing["aliases"] = sorted({*existing.get("aliases", []), *item.get("aliases", [])})
    existing["weight"] = round(min(1.0 + math.log10(int(existing["count"])), 3.0), 3)


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    if not path.exists():
        return
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _norm(phrase: str, lang: str) -> str:
    return phrase if lang == "zh" else phrase.lower()


def _sort_key(item: dict[str, Any]) -> tuple[str, str]:
    return str(item.get("lang", "mixed")), str(item.get("phrase", "")).lower()
