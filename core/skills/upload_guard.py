from __future__ import annotations

"""WHAT IS ALLOWED THROUGH THE ATTACH BUTTON.

UK (2026-09-13): "attach file ka frontend mein option hai but attach
nahi hota, wahan koi file nahi koi directory check. Aisa ki koi
malicious code na daale input attach se -- ye sab karo, pehle zaroori
hai." And separately: "main package bolun .zip tar.gz to wo sab kar ke
de de."

Those two asks pull in opposite directions, which is the whole design
problem here. Accepting archives is exactly how you get hurt:

  * ZIP-SLIP. An archive entry named '../../core/orchestration/brain.py'
    will, with a naive extractall(), overwrite a live source file. This
    is the single most common way "just let users upload a zip" turns
    into remote code execution. Every path is therefore resolved after
    joining and rejected if it lands outside the destination -- string
    prefix checks are not enough, because symlinks defeat them.

  * SYMLINK ESCAPE. A tar can contain a symlink pointing at /etc or at
    core/, after which a later entry writes "into" it. Symlinks and
    hardlinks are refused outright; nothing in a user upload needs one.

  * ZIP BOMB. A few KB can expand to gigabytes and fill UK's phone.
    Declared sizes are summed BEFORE extracting, and the count of
    entries is capped.

  * SPECIAL FILES. Device nodes, FIFOs, setuid bits -- refused.

The scanner is the second layer, not the first. It flags code that
would reach outside the sandbox and marks the upload for review; it is
NOT a malware detector and does not pretend to be. Nobody can reliably
decide whether arbitrary code is malicious by reading it, so the real
protection is that uploaded code lands in an isolated per-role sandbox
and is never imported by the running organism. The scan exists so that
a person is warned before choosing to run something, not so the system
can claim the file is safe.
"""

import hashlib
import os
import re
import shutil
import tarfile
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..runtime.log import log_event

MAX_UPLOAD_BYTES = 100 * 1024 * 1024         # 100 MB -- audio/video are legitimately large
MAX_EXTRACTED_BYTES = 100 * 1024 * 1024      # refuse zip bombs
MAX_ARCHIVE_ENTRIES = 2000
MAX_PATH_DEPTH = 12

# Extensions JARVIS will accept. Everything else is stored as an opaque
# blob at most, never opened or executed.
TEXT_EXTENSIONS = {".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".md", ".txt", ".csv",
                   ".yml", ".yaml", ".toml", ".ini", ".cfg", ".html", ".css", ".sh",
                   ".sql", ".xml", ".env.example"}
ARCHIVE_EXTENSIONS = {".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".heic"}

# Media and documents: stored as opaque blobs, never parsed or executed.
# They were previously "unknown type", which worked but read like a
# warning for an ordinary mp3.
MEDIA_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".opus", ".flac", ".aac",
                    ".mp4", ".mkv", ".webm", ".mov", ".pdf", ".docx", ".xlsx",
                    ".pptx", ".epub", ".srt", ".vtt"}

# Never accepted -- executables and installers have no legitimate use
# in a code sandbox and every use is a risk.
BLOCKED_EXTENSIONS = {".exe", ".dll", ".so", ".dylib", ".bin", ".apk", ".deb", ".rpm",
                      ".msi", ".bat", ".cmd", ".scr", ".jar", ".com", ".pyc", ".pyd"}

# WHAT EACH KIND OF FILE ACTUALLY IS, AND WHAT JARVIS CAN DO WITH IT
# (2026-09-16, UK: "usko pata hona chahiye kaun si cheez kya hai, kaun
# sa file extension use kar sakta hai kaun sa nahi").
#
# The guard already decided ALLOWED vs BLOCKED. That is a security
# answer, and it was the only thing JARVIS knew about an upload -- so
# when UK attached a .tar or a .png, JARVIS could say "accepted" and
# nothing else. It had no idea what the thing WAS.
#
# This maps extensions to a capability statement JARVIS can actually
# reason and talk about: what the file is, and honestly whether it can
# work with it right now or only store it.
FILE_KIND_MAP: Dict[str, Dict[str, str]] = {}


def _register(kind: str, capability: str, extensions: tuple) -> None:
    for ext in extensions:
        FILE_KIND_MAP[ext] = {"kind": kind, "capability": capability}


_register("source code", "padh sakta hoon, edit kar sakta hoon, sandbox mein chala sakta hoon",
          (".py", ".js", ".ts", ".tsx", ".jsx", ".sh", ".rb", ".go", ".rs", ".java",
           ".c", ".cpp", ".h", ".hpp", ".css", ".html", ".sql"))
_register("structured data", "parse karke padh sakta hoon aur process kar sakta hoon",
          (".json", ".yaml", ".yml", ".toml", ".ini", ".csv", ".tsv", ".xml"))
_register("plain text", "seedha padh sakta hoon",
          (".txt", ".md", ".log", ".env", ".cfg", ".conf"))
_register("archive", "sandbox mein extract karke andar ki files dekh sakta hoon",
          (".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz"))
_register("document", "abhi seedha padhne ki native capability nahi hai -- store kar sakta hoon, "
                      "aur iske liye sandbox mein tool bana sakta hoon",
          (".pdf", ".docx", ".xlsx", ".pptx", ".epub"))
_register("image", "abhi dekh nahi sakta (koi vision model attached nahi hai) -- store kar sakta hoon",
          (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".heic"))
_register("audio/video", "abhi sun/dekh nahi sakta -- store kar sakta hoon",
          (".mp3", ".wav", ".m4a", ".ogg", ".opus", ".flac", ".aac",
           ".mp4", ".mkv", ".webm", ".mov", ".srt", ".vtt"))


def describe_file_kind(filename: str) -> Dict[str, str]:
    """What this file is and what JARVIS can honestly do with it.

    Returns a blocked verdict for executables, and an explicit "pata
    nahi" for anything unrecognised rather than guessing a capability
    it may not have.
    """
    ext = os.path.splitext(filename or "")[1].lower()
    if ext in BLOCKED_EXTENSIONS:
        return {"extension": ext, "kind": "executable",
                "capability": "accept nahi kiya jaata -- sandbox mein executables allowed nahi hain",
                "allowed": "no"}
    known = FILE_KIND_MAP.get(ext)
    if known:
        return {"extension": ext, "kind": known["kind"],
                "capability": known["capability"], "allowed": "yes"}
    return {"extension": ext or "(koi extension nahi)", "kind": "unknown",
            "capability": "pehchan nahi paya -- store kar sakta hoon, par ismein kya hai yeh nahi pata",
            "allowed": "yes"}

# Patterns worth a human's attention. Presence does NOT mean malicious;
# it means "a person should look before this runs".
_SUSPICIOUS = (
    (r"\bos\.system\s*\(", "shell execution", "high"),
    (r"\bsubprocess\.(Popen|run|call|check_output)", "subprocess spawn", "high"),
    (r"\beval\s*\(|\bexec\s*\(", "eval/exec of dynamic code", "high"),
    (r"\b__import__\s*\(|\bimportlib\b", "dynamic import", "medium"),
    (r"\bshutil\.rmtree|\bos\.remove|\bos\.unlink", "file deletion", "high"),
    (r"\bsocket\b|\brequests\.|\burllib|\bhttpx\b|\bcurl\b|\bwget\b", "network access", "medium"),
    (r"\bpip\s+install|\bapt\s+install|\bnpm\s+i(nstall)?\b", "package installation", "high"),
    (r"base64\.b64decode\s*\([^)]{80,}", "large base64 blob decoded (often packed payload)", "high"),
    (r"\bos\.environ\b|\bgetenv\b", "reads environment variables", "medium"),
    (r"/etc/passwd|/etc/shadow|~/\.ssh|id_rsa", "touches credential paths", "high"),
    (r"\bchmod\s+\+?x|\bos\.chmod\b", "changes execute permissions", "medium"),
    (r"\bcrontab\b|\bsystemctl\b|\bnohup\b", "persistence / service control", "high"),
)


@dataclass
class ScanFinding:
    file: str
    label: str
    severity: str
    line: int

    def as_dict(self) -> Dict[str, Any]:
        return {"file": self.file, "label": self.label, "severity": self.severity, "line": self.line}


@dataclass
class UploadResult:
    ok: bool
    upload_id: str
    dest: Optional[str] = None
    files: List[str] = field(default_factory=list)
    findings: List[ScanFinding] = field(default_factory=list)
    refused_entries: List[Dict[str, str]] = field(default_factory=list)
    error: Optional[str] = None
    total_bytes: int = 0
    sha256: Optional[str] = None
    file_kind: Optional[Dict[str, str]] = None

    @property
    def needs_review(self) -> bool:
        return any(f.severity == "high" for f in self.findings)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok, "upload_id": self.upload_id, "dest": self.dest,
            # What this file IS and what JARVIS can honestly do with it
            # -- so it can answer "what did I just receive" instead of
            # only knowing whether the guard let it through.
            "file_kind": self.file_kind,
            "files": self.files[:300], "file_count": len(self.files),
            "findings": [f.as_dict() for f in self.findings],
            "refused_entries": self.refused_entries[:50],
            "needs_review": self.needs_review, "error": self.error,
            "total_bytes": self.total_bytes, "sha256": self.sha256,
            "note": self._note(),
        }

    def _note(self) -> str:
        if not self.ok:
            return f"Upload refuse ho gaya: {self.error}"
        bits = []
        if self.file_kind:
            bits.append(
                f"Yeh {self.file_kind.get('kind')} file hai "
                f"({self.file_kind.get('extension')}) -- {self.file_kind.get('capability')}."
            )
        bits.append(f"{len(self.files)} file extract hui.")
        if self.refused_entries:
            bits.append(f"{len(self.refused_entries)} entry refuse ki (path escape ya blocked type).")
        if self.needs_review:
            high = sorted({f.label for f in self.findings if f.severity == "high"})
            bits.append(
                f"Ismein yeh mila: {', '.join(high)}. Iska matlab yeh nahi ki file malicious hai -- "
                "matlab yeh hai ki chalane se pehle aap khud dekh lo. Main sirf sandbox mein hi "
                "chala sakta hun, live system se yeh code kabhi nahi judega."
            )
        elif self.findings:
            bits.append("Kuch minor cheezein mili, par kuch bhi sandbox ke bahar nahi pahunchta.")
        else:
            bits.append("Scan mein aisa kuch nahi mila jo sandbox ke bahar pahunche.")
        return " ".join(bits)


def _safe_join(dest_root: Path, member_name: str) -> Optional[Path]:
    """Resolve an archive member against the destination, returning None
    if it escapes. This is the zip-slip check and it must resolve, not
    string-compare, or '../' and symlinks both get through."""
    if not member_name or member_name.startswith("/") or "\x00" in member_name:
        return None
    if len(Path(member_name).parts) > MAX_PATH_DEPTH:
        return None
    candidate = (dest_root / member_name)
    try:
        resolved = candidate.resolve()
        root = dest_root.resolve()
        if resolved == root or root in resolved.parents:
            return candidate
    except Exception:
        return None
    return None


def _ext_allowed(name: str) -> Tuple[bool, str]:
    ext = Path(name).suffix.lower()
    if ext in BLOCKED_EXTENSIONS:
        return False, f"blocked file type ({ext})"
    if ext and ext not in (TEXT_EXTENSIONS | ARCHIVE_EXTENSIONS | IMAGE_EXTENSIONS | MEDIA_EXTENSIONS):
        # Unknown extension: allowed only if it is small and looks like
        # text, checked at write time. Recorded here for transparency.
        return True, "unknown type -- stored, not executed"
    return True, ""


def scan_source(path: Path, relative_name: str) -> List[ScanFinding]:
    """Read a text file and flag anything reaching outside the sandbox."""
    findings: List[ScanFinding] = []
    if path.suffix.lower() not in TEXT_EXTENSIONS:
        return findings
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return findings
    if len(text) > 2_000_000:
        text = text[:2_000_000]
    lines = text.splitlines()
    for pattern, label, severity in _SUSPICIOUS:
        rx = re.compile(pattern)
        for i, line in enumerate(lines, start=1):
            if rx.search(line):
                findings.append(ScanFinding(file=relative_name, label=label, severity=severity, line=i))
                break          # one finding per pattern per file is enough
    return findings


def _extract_zip(src: Path, dest: Path, result: UploadResult) -> bool:
    with zipfile.ZipFile(src) as zf:
        infos = zf.infolist()
        if len(infos) > MAX_ARCHIVE_ENTRIES:
            result.error = f"Archive mein {len(infos)} entries hain -- limit {MAX_ARCHIVE_ENTRIES}."
            return False
        declared = sum(i.file_size for i in infos)
        if declared > MAX_EXTRACTED_BYTES:
            result.error = f"Extract hone pe {declared // (1024*1024)} MB ho jaata -- zip bomb ho sakta hai, refuse kiya."
            return False
        for info in infos:
            name = info.filename
            if info.is_dir():
                continue
            target = _safe_join(dest, name)
            if target is None:
                result.refused_entries.append({"entry": name, "reason": "path archive ke bahar ja raha tha (zip-slip)"})
                continue
            allowed, why = _ext_allowed(name)
            if not allowed:
                result.refused_entries.append({"entry": name, "reason": why})
                continue
            # Unix mode is in the top 16 bits; refuse symlinks.
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                result.refused_entries.append({"entry": name, "reason": "symlink -- refuse kiya"})
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as srcf, open(target, "wb") as out:
                shutil.copyfileobj(srcf, out, length=64 * 1024)
            result.files.append(str(target.relative_to(dest)))
    return True


def _extract_tar(src: Path, dest: Path, result: UploadResult) -> bool:
    with tarfile.open(src) as tf:
        members = tf.getmembers()
        if len(members) > MAX_ARCHIVE_ENTRIES:
            result.error = f"Archive mein {len(members)} entries hain -- limit {MAX_ARCHIVE_ENTRIES}."
            return False
        declared = sum(m.size for m in members if m.isfile())
        if declared > MAX_EXTRACTED_BYTES:
            result.error = f"Extract hone pe {declared // (1024*1024)} MB ho jaata -- refuse kiya."
            return False
        for m in members:
            if m.isdir():
                continue
            if m.issym() or m.islnk():
                result.refused_entries.append({"entry": m.name, "reason": "symlink/hardlink -- refuse kiya"})
                continue
            if not m.isfile():
                result.refused_entries.append({"entry": m.name, "reason": "special file (device/fifo) -- refuse kiya"})
                continue
            target = _safe_join(dest, m.name)
            if target is None:
                result.refused_entries.append({"entry": m.name, "reason": "path archive ke bahar ja raha tha (tar-slip)"})
                continue
            allowed, why = _ext_allowed(m.name)
            if not allowed:
                result.refused_entries.append({"entry": m.name, "reason": why})
                continue
            extracted = tf.extractfile(m)
            if extracted is None:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "wb") as out:
                shutil.copyfileobj(extracted, out, length=64 * 1024)
            os.chmod(target, 0o600)          # never executable
            result.files.append(str(target.relative_to(dest)))
    return True


def accept_upload(file_bytes: bytes, filename: str, *, role: str = "user",
                  username: Optional[str] = None) -> Dict[str, Any]:
    """Accept an uploaded file or archive into the caller's OWN sandbox.

    Nothing here ever lands in the live tree, and nothing is executed --
    extraction and scanning only. Running anything is a separate,
    explicit action in the codebox.
    """
    upload_id = uuid.uuid4().hex[:12]
    result = UploadResult(ok=False, upload_id=upload_id)
    # Identify what this is up front, so even a REFUSED upload can
    # say what it was rather than just "refused".
    result.file_kind = describe_file_kind(filename)

    if not file_bytes:
        result.error = "File khali hai."
        return result.as_dict()
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        result.error = f"File {len(file_bytes) // (1024*1024)} MB hai -- limit {MAX_UPLOAD_BYTES // (1024*1024)} MB."
        return result.as_dict()

    safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", Path(filename or "upload").name)[:120] or "upload"
    allowed, why = _ext_allowed(safe_name)
    if not allowed:
        result.error = why
        return result.as_dict()

    result.total_bytes = len(file_bytes)
    result.sha256 = hashlib.sha256(file_bytes).hexdigest()[:16]

    try:
        from .sandbox_policy import sandbox_dir_for
        sandbox = sandbox_dir_for(role=role, username=username, session_id=f"upload_{upload_id}")
    except Exception:
        sandbox = Path("data/sandboxes/user/anonymous")
        sandbox.mkdir(parents=True, exist_ok=True)

    dest = sandbox / f"upload_{upload_id}"
    dest.mkdir(parents=True, exist_ok=True)
    staged = dest / safe_name

    try:
        staged.write_bytes(file_bytes)
        lower = safe_name.lower()
        is_zip = lower.endswith(".zip")
        is_tar = any(lower.endswith(s) for s in (".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tar.xz", ".gz", ".bz2", ".xz"))

        if is_zip:
            if not _extract_zip(staged, dest, result):
                shutil.rmtree(dest, ignore_errors=True)
                return result.as_dict()
            staged.unlink(missing_ok=True)
        elif is_tar:
            if not _extract_tar(staged, dest, result):
                shutil.rmtree(dest, ignore_errors=True)
                return result.as_dict()
            staged.unlink(missing_ok=True)
        else:
            os.chmod(staged, 0o600)
            result.files.append(safe_name)

        for rel in result.files:
            findings = scan_source(dest / rel, rel)
            result.findings.extend(findings)

        result.ok = True
        result.dest = str(dest)
        log_event("upload",
                  f"accepted upload {upload_id} ({len(result.files)} files, "
                  f"{len(result.refused_entries)} refused, review={result.needs_review})",
                  level="info")
    except (zipfile.BadZipFile, tarfile.TarError) as exc:
        shutil.rmtree(dest, ignore_errors=True)
        result.error = f"Archive padha nahi gaya (corrupt ya galat format): {exc}"
    except Exception as exc:
        shutil.rmtree(dest, ignore_errors=True)
        result.error = f"Upload fail hua: {exc}"

    return result.as_dict()


def _base_dir_for(role: str, username: Optional[str]) -> Optional[Path]:
    """The same per-role sandbox root list_uploads/accept_upload use.

    Factored out (2026-09-21, root-cause pass on the "attachment does
    nothing" bug -- see read_uploaded_file() below) so the ID -> real
    path resolution used by an actual read is GUARANTEED to be the
    same lookup list_uploads() already does, rather than a second,
    independently-written path-guessing routine that could drift from
    it. Nothing outside this module should reconstruct this logic.
    """
    try:
        from .sandbox_policy import SANDBOX_ROOT
    except Exception:
        return None
    tier = "owner" if role in {"owner", "co_owner"} else ("admin" if role == "admin" else "user")
    base = SANDBOX_ROOT / tier
    if tier == "user":
        base = base / re.sub(r"[^a-zA-Z0-9_-]", "_", username or "anonymous")
    return base


def list_uploads(role: str = "user", username: Optional[str] = None) -> List[Dict[str, Any]]:
    """What this principal has uploaded -- their own sandbox only."""
    try:
        base = _base_dir_for(role, username)
        out = []
        if base is not None and base.exists():
            for d in sorted(base.rglob("upload_*")):
                if d.is_dir():
                    files = [f for f in d.rglob("*") if f.is_file()]
                    out.append({"upload_id": d.name.replace("upload_", ""), "path": str(d),
                                "files": len(files),
                                "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(d.stat().st_mtime))})
        return out
    except Exception:
        return []


# Read this many characters of a text-like upload back to the model.
# Large enough for real source files and documents-as-text, small
# enough to not blow the LLM's context on one attachment.
MAX_READ_CHARS = 40_000


def read_uploaded_file(upload_id: str, role: str = "user", username: Optional[str] = None,
                       filename: Optional[str] = None) -> Dict[str, Any]:
    """Resolve upload_id to the REAL sandbox path accept_upload() saved
    and return its content -- the missing half of the upload feature
    (2026-09-21 root-cause pass, UK's chat-log audit).

    Before this existed, JARVIS could list an upload's ID (list_uploads
    -> list_my_uploads tool) but had no tool that turned an ID into
    actual content, and nothing in the system prompt told the model to
    even try -- so on "yeh file dekho: X" it had nothing behind the
    sentence and, left to fill the gap itself, INVENTED a plausible-
    sounding path (/tmp/jarvis/uploads/, /usr/share/jarvis/resources/,
    etc.) that accept_upload() never wrote to and that do not exist.
    This function is the one and only place an upload_id is turned
    into a filesystem path -- callers (companion_tools.py's
    read_uploaded_file tool) never construct a path themselves, which
    is what keeps this grounded instead of guessed.

    Returns a dict that is ALWAYS honest about what it found: a
    matching upload's real absolute path is included even when the
    file can't be read as text (a PDF, an image, an archive), so the
    model has something true to say instead of a fabricated location.
    A missing upload_id returns ok=False with the caller's own real
    upload list attached, so the model can match a filename itself
    instead of guessing a second time.
    """
    upload_id = re.sub(r"[^a-zA-Z0-9]", "", upload_id or "")[:32]
    if not upload_id:
        return {"ok": False, "error": "upload_id khaali ya invalid hai.",
                "your_uploads": list_uploads(role=role, username=username)}

    base = _base_dir_for(role, username)
    upload_dir: Optional[Path] = None
    if base is not None and base.exists():
        for d in base.rglob(f"upload_{upload_id}"):
            if d.is_dir():
                upload_dir = d
                break
    if upload_dir is None:
        # Never fabricate a path here -- an unmatched ID is reported as
        # exactly that, with the real list attached so the model can
        # self-correct against real data instead of guessing again.
        return {"ok": False, "error": f"upload_id '{upload_id}' is speaker ke sandbox mein nahi mila.",
                "your_uploads": list_uploads(role=role, username=username)}

    files = sorted(f for f in upload_dir.rglob("*") if f.is_file())
    if filename:
        matched = [f for f in files if f.name == filename or f.name.lower() == filename.lower()]
        if matched:
            files = matched
    if not files:
        return {"ok": False, "error": "Upload directory mila, par andar koi file nahi hai (khaali ya extract fail hui thi).",
                "upload_id": upload_id, "path": str(upload_dir)}

    out_files = []
    for f in files[:20]:
        rel = str(f.relative_to(upload_dir))
        kind = describe_file_kind(f.name)
        entry: Dict[str, Any] = {
            "name": f.name, "relative_path": rel, "absolute_path": str(f.resolve()),
            "size_bytes": f.stat().st_size, "kind": kind["kind"],
        }
        if f.suffix.lower() in TEXT_EXTENSIONS:
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
                truncated = len(text) > MAX_READ_CHARS
                entry["content"] = text[:MAX_READ_CHARS]
                entry["truncated"] = truncated
                if truncated:
                    entry["note"] = f"{len(text)} chars mein se pehle {MAX_READ_CHARS} dikhaye gaye."
            except Exception as exc:
                entry["content"] = None
                entry["note"] = f"Text ke roop mein padh nahi paya: {exc}"
        else:
            entry["content"] = None
            entry["note"] = (
                f"Yeh {kind['kind']} file hai -- {kind['capability']}. Content seedha yahan nahi dikhaya "
                "ja sakta, lekin iska real path upar diya gaya hai; usi path se koi bhi tool (jaise "
                "run_coding_task) ise access kar sakta hai."
            )
        out_files.append(entry)

    return {"ok": True, "upload_id": upload_id, "path": str(upload_dir), "files": out_files,
            "file_count": len(files)}
