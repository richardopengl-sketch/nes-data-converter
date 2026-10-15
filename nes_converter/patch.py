"""Shared v003 original-snapshot patch mechanics; no dataset interpretation."""
import difflib
import re


def lf(text: str) -> str:
    result = text.replace("\r\n", "\n")
    if "\r" in result:
        raise ValueError("Standalone CR is outside the provisional LF format")
    return result


def make_patch(before_files, after_files, *, editable_regions: dict[str, tuple[int, int]] | None = None):
    if before_files.keys() != after_files.keys():
        raise ValueError("File creation/deletion/rename outside provisional scope")
    if editable_regions is not None and not editable_regions.keys() <= before_files.keys():
        raise ValueError("Editable region refers to an unknown file")
    lines = []
    for path, before in before_files.items():
        if not isinstance(path, str) or not path or "\n" in path or "\r" in path or path.startswith(("+", "-")):
            raise ValueError("Invalid header path")
        old, new = before.split("\n"), after_files[path].split("\n")
        offset = 0
        if editable_regions is not None and path in editable_regions:
            start, end = editable_regions[path]
            if type(start) is not int or type(end) is not int or not 0 <= start <= end <= len(old):
                raise ValueError("Editable region outside original snapshot")
            target_end = len(new) - (len(old) - end)
            if target_end < start or old[:start] != new[:start] or old[end:] != new[target_end:]:
                raise ValueError("Noneditable prefix/suffix changed")
            old, new, offset = old[start:end], new[start:target_end], start
        matcher = difflib.SequenceMatcher(None, old, new, autojunk=False)
        for tag, i, end, j, target_end in matcher.get_opcodes():
            if tag != "equal":
                lines += [f"{path}:{offset + i}"] + ["-" + line for line in old[i:end]] + ["+" + line for line in new[j:target_end]]
    return "\n".join(lines)


def parse_patch(patch):
    # Response line delimiters are not prefixed source blank lines ("+" / "-").
    patch = lf(patch).rstrip("\n")
    if patch == "" or patch == "<NO_EDIT>":
        return []
    patches = []
    current = None
    for line in patch.split("\n"):
        if line.startswith(("-", "+")) and current is not None:
            if line[0] == "-" and current["added"]:
                raise ValueError("Deletion after additions is outside strict subset")
            current["removed" if line[0] == "-" else "added"].append(line[1:])
        else:
            match = re.fullmatch(r"(.+):([0-9]+)", line)
            if not match:
                raise ValueError("Invalid patch header or body")
            current = {"path": match[1], "start": int(match[2]), "removed": [], "added": []}
            patches.append(current)
    if any(not p["removed"] and not p["added"] for p in patches):
        raise ValueError("Empty patch body")
    return patches


def apply_patch(before_files, patch):
    parsed = parse_patch(patch)
    output = dict(before_files)
    for path in {p["path"] for p in parsed}:
        if path not in before_files:
            raise ValueError("Unknown target file")
        old = before_files[path].split("\n")
        selected = sorted((p for p in parsed if p["path"] == path), key=lambda p: p["start"])
        previous_end = -1
        previous_start = -1
        for p in selected:
            start, end = p["start"], p["start"] + len(p["removed"])
            if start < previous_end or start == previous_start:
                raise ValueError("Overlapping/ambiguous patches")
            if not 0 <= start <= end <= len(old):
                raise ValueError("Patch location outside original snapshot")
            if old[start:end] != p["removed"]:
                raise ValueError("Deleted content does not match original snapshot")
            previous_start, previous_end = start, end
        for p in reversed(selected):
            old[p["start"]:p["start"] + len(p["removed"])] = p["added"]
        output[path] = "\n".join(old)
    return output
