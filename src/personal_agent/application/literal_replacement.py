"""Literal UTF-8 replacement shared by Artifact and workspace execution."""


def replace_literal(content: bytes, old: bytes, new: bytes, replace_all: bool, max_bytes: int) -> tuple[bytes, int]:
    sample = content.decode("utf-8")[:4096]
    crlf = sample.count("\r\n") * 2 > sample.count("\n")
    text = content.replace(b"\r\n", b"\n")
    old = old.replace(b"\r\n", b"\n")
    new = new.replace(b"\r\n", b"\n")
    count = text.count(old)
    if count == 0:
        raise ValueError("FS_EDIT_NOT_FOUND: old_string was not found; read the file and copy the exact text")
    if count > 1 and not replace_all:
        raise ValueError(
            f"FS_AMBIGUOUS_EDIT: old_string matched {count} times; "
            "include more surrounding text or set replace_all to true"
        )
    size = len(text) + count * (len(new) - len(old))
    if crlf:
        size += text.count(b"\n") + count * (new.count(b"\n") - old.count(b"\n"))
    if size > max_bytes:
        raise ValueError(f"edited file exceeds the {max_bytes}-byte UTF-8 limit")
    edited = text.replace(old, new)
    return (edited.replace(b"\n", b"\r\n") if crlf else edited), count
