"""Load markdown docs, redact secrets, and split them into heading-aware chunks."""

import re
import hashlib
from fnmatch import fnmatch
from pathlib import Path
from typing import Dict, Iterator, List

from .config import ALWAYS_EXCLUDE, Source

SECRET_PATTERNS = [
    re.compile(r"(?i)\b(api[_-]?key|secret|token|password|passwd|app[_-]?password|private[_-]?key)\b(\s*[:=]\s*)\S+"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                       # AWS access key id
    re.compile(r"\b(sk|ghp|gho|xox[bap])[-_][A-Za-z0-9_-]{16,}\b"),  # common API token prefixes
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b[0-9a-f]{40,}\b"),                          # long hex secrets / digests
]
HEADING = re.compile(r"^(#{1,4})\s+(.+?)\s*#*\s*$", re.M)


def redact(text: str) -> str:
    for pattern in SECRET_PATTERNS:
        if pattern.groups >= 2:
            text = pattern.sub(lambda m: f"{m.group(1)}{m.group(2)}[redacted]", text)
        else:
            text = pattern.sub("[redacted]", text)
    return text


def _matches(rel: str, patterns: List[str]) -> bool:
    # The leading "/" lets "**/name" patterns match files at the root too
    rel = rel.replace("\\", "/")
    return any(fnmatch(rel, p) or fnmatch("/" + rel, p) for p in patterns)


def iter_documents(source: Source) -> Iterator[Dict[str, str]]:
    root = Path(source.root)
    if not root.exists():
        return
    files = [root] if root.is_file() else sorted({f for pattern in source.include for f in root.glob(pattern) if f.is_file()})
    excludes = ALWAYS_EXCLUDE + source.exclude
    for path in files:
        rel = path.name if root.is_file() else str(path.relative_to(root))
        if _matches(rel, excludes) or path.suffix.lower() != ".md":
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if text.strip():
            yield {"source": source.label, "path": rel.replace("\\", "/"), "text": redact(text)}


def _split_long(text: str, size: int, overlap: int) -> List[str]:
    """Splits on paragraph boundaries, falling back to hard cuts for very long paragraphs."""
    parts, current = [], ""
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        while len(para) > size:
            if current:
                parts.append(current)
                current = ""
            parts.append(para[:size])
            para = para[size - overlap:]
        if len(current) + len(para) + 2 > size and current:
            parts.append(current)
            current = current[-overlap:] + "\n\n" + para if overlap else para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current:
        parts.append(current)
    return parts


def chunk_document(doc: Dict[str, str], size: int = 1200, overlap: int = 150) -> List[Dict[str, str]]:
    """Chunks a document by markdown sections; each chunk keeps its heading path for context."""
    text = doc["text"]
    marks = [(m.start(), len(m.group(1)), m.group(2).strip()) for m in HEADING.finditer(text)]
    sections, stack = [], []
    bounds = [0] + [m[0] for m in marks] + [len(text)]
    titles = [None] + marks
    for i in range(len(bounds) - 1):
        if titles[i]:
            _, level, title = titles[i]
            stack = [t for t in stack if t[0] < level] + [(level, title)]
        body = text[bounds[i]:bounds[i + 1]].strip()
        if body:
            sections.append((" > ".join(t for _, t in stack), body))

    chunks = []
    for heading, body in sections:
        for piece in _split_long(body, size, overlap):
            if len(piece.strip()) < 40:
                continue
            uid = hashlib.sha1(f"{doc['source']}|{doc['path']}|{heading}|{piece}".encode()).hexdigest()[:16]
            chunks.append({
                "id": uid,
                "source": doc["source"],
                "path": doc["path"],
                "heading": heading,
                "text": piece,
            })
    return chunks
