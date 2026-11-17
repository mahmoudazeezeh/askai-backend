"""Strict code-only mode: post-processing safety net.

The prompt already tells the model to return only bare TASM code. This
module enforces it: removes Markdown fences and surrounding prose, strips
';' comments (but never a ';' inside a string literal), and recognises the
"CLARIFY:" reply used when essential information is missing.
"""
from __future__ import annotations

import re

CLARIFY = "CLARIFY:"
_FENCE = re.compile(r"```[ \t]*([A-Za-z0-9_+-]*)[ \t]*\n(.*?)```", re.S)
_START = re.compile(
    r"^\s*(DOSSEG|\.MODEL|\.8086|\.8087|TITLE|INCLUDE|ASSUME|JUMPS|LOCALS|IDEAL|MASM|"
    r"\.STACK|\.DATA|\.CODE|ORG|PAGE|NAME|[A-Z_@?$][\w@?$]*\s+SEGMENT|[A-Z_@?$][\w@?$]*\s+(EQU|MACRO|STRUC)\b)",
    re.I)
_END = re.compile(r"^\s*END(\s+[\w@?$]+)?\s*$", re.I | re.M)


def strip_comment(line: str) -> str:
    """Remove a ';' comment, respecting '...' and "..." string literals."""
    quote = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif ch == ";":
            return line[:i].rstrip()
    return line.rstrip()


def _strip_comment_blocks(lines: list[str]) -> list[str]:
    """Remove COMMENT <delim> ... <delim> blocks (MASM/TASM)."""
    out, delim = [], None
    for ln in lines:
        if delim:
            if delim in ln:
                delim = None
            continue
        m = re.match(r"^\s*COMMENT\s+(\S)", ln, re.I)
        if m:
            d = m.group(1)
            if ln.count(d) < 2:
                delim = d
            continue
        out.append(ln)
    return out


def looks_like_program(text: str) -> bool:
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.strip().startswith(";")]
    return bool(lines) and bool(_START.match(lines[0])) and bool(_END.search(text))


def clean_code(text: str) -> str:
    lines = _strip_comment_blocks(text.replace("\r\n", "\n").split("\n"))
    out: list[str] = []
    for ln in lines:
        s = strip_comment(ln.expandtabs(4))
        if s.strip() or (out and out[-1].strip()):
            out.append(s)
    while out and not out[-1].strip():
        out.pop()
    # drop anything after the final END directive (stray prose)
    for i in range(len(out) - 1, -1, -1):
        if _END.match(out[i]):
            out = out[: i + 1]
            break
    return "\n".join(out) + "\n"


def extract_code(answer: str) -> str | None:
    """Return the program contained in a model answer (fenced or bare), or None."""
    fences = [code for lang, code in _FENCE.findall(answer)
              if lang.lower() in ("", "asm", "assembly", "masm", "tasm", "x86asm", "x86", "nasm")]
    for cand in sorted(fences, key=len, reverse=True):
        if _END.search(cand):
            return cand
    if looks_like_program(answer):
        return answer
    # bare code preceded by a line of prose ("Here is the code:")
    lines = answer.splitlines()
    for i, ln in enumerate(lines[:4]):
        if _START.match(ln):
            rest = "\n".join(lines[i:])
            if looks_like_program(rest):
                return rest
    return None


def _whole_answer_is_code(a: str) -> str | None:
    """For mixed modes (ASK/SOLVE): code only if the ENTIRE answer is a program
    (bare, or one fence with at most one short line of prose around it)."""
    if looks_like_program(a):
        return a
    fences = _FENCE.findall(a)
    if len(fences) == 1:
        outside = _FENCE.sub("", a).strip()
        code = fences[0][1]
        if len(outside) <= 80 and "\n" not in outside and _END.search(code) and looks_like_program(code):
            return code
    return None


def postprocess(answer: str, strict: bool = True) -> dict:
    """strict=True for GENERATE (always code); False for ASK/SOLVE (code only
    when the whole answer is a program, so explanations are never cut).
    -> {"kind": "clarify"|"code"|"text", "text": ...}"""
    a = answer.strip()
    head = a.lstrip("`* \n")
    if head.upper().startswith(CLARIFY):
        q = head[len(CLARIFY):].strip().strip("`*").strip()
        return {"kind": "clarify", "text": q.splitlines()[0] if q else "Please give more details."}
    code = extract_code(a) if strict else _whole_answer_is_code(a)
    if code is not None:
        return {"kind": "code", "text": clean_code(code)}
    return {"kind": "text", "text": answer}
