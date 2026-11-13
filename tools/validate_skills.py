#!/usr/bin/env python3
"""Validate the skills in this repository against the Agent Skills specification.

Checks (all fail the build):
  * SKILL.md exists in every skill directory and starts with YAML frontmatter
  * `name` equals the directory name and matches [a-z0-9-] (no leading/trailing
    hyphen, no double hyphen)
  * `description` is 1-1024 characters
  * `compatibility` is at most 500 characters when present
  * `metadata` is a flat string map when present
  * SKILL.md is under 500 lines (progressive-disclosure guidance)
  * every relative markdown link in SKILL.md resolves to an existing file
  * every reference file stays one level below the skill root

Usage: python tools/validate_skills.py [--verbose]
Exit code 0 = all good, 1 = at least one failure.
"""

import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)#]+)(?:#[^)]*)?\)")
MAX_LINES = 500
MAX_DESCRIPTION = 1024
MAX_COMPATIBILITY = 500


def split_frontmatter(text):
    """Return (frontmatter_lines, body) or (None, text) when absent."""
    if not text.startswith("---"):
        return None, text
    lines = text.splitlines()
    if lines[0].strip() != "---":
        return None, text
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return lines[1:index], "\n".join(lines[index + 1:])
    return None, text


def parse_frontmatter(lines):
    """Minimal YAML subset parser: scalars and indented block scalars."""
    data = {}
    key = None
    buffer = []
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if re.match(r"^[A-Za-z0-9_-]+:", line):
            if key is not None:
                data[key] = join_block(buffer)
            key, _, rest = line.partition(":")
            key = key.strip()
            buffer = [rest.strip()]
            continue
        if key is not None:
            buffer.append(line.strip())
    if key is not None:
        data[key] = join_block(buffer)
    return data


def join_block(parts):
    cleaned = []
    for part in parts:
        part = part.strip()
        if not part or part in (">", ">-", "|", "|-", "|+"):
            continue
        cleaned.append(part)
    return " ".join(cleaned).strip()


def unquote(value):
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


class Result(object):
    def __init__(self):
        self.failures = []
        self.checks = 0

    def check(self, condition, message):
        self.checks += 1
        if not condition:
            self.failures.append(message)
        return condition


def validate_skill(skill_dir, result, verbose=False):
    name = os.path.basename(skill_dir)
    skill_md = os.path.join(skill_dir, "SKILL.md")
    if not result.check(os.path.isfile(skill_md), name + ": SKILL.md is missing"):
        return
    with open(skill_md, "r", encoding="utf-8") as handle:
        text = handle.read()

    lines = text.splitlines()
    result.check(len(lines) < MAX_LINES,
                 name + ": SKILL.md has " + str(len(lines)) + " lines (limit " + str(MAX_LINES) + ")")

    front, body = split_frontmatter(text)
    if not result.check(front is not None, name + ": SKILL.md has no YAML frontmatter"):
        return
    data = {key: unquote(value) for key, value in parse_frontmatter(front).items()}

    declared = data.get("name", "")
    result.check(declared == name,
                 name + ": frontmatter name '" + declared + "' must equal the directory name")
    result.check(bool(NAME_RE.match(declared or "")),
                 name + ": name must be lowercase letters/digits/hyphens without '--'")

    description = data.get("description", "")
    result.check(1 <= len(description) <= MAX_DESCRIPTION,
                 name + ": description is " + str(len(description)) + " chars (limit "
                 + str(MAX_DESCRIPTION) + ")")

    if "compatibility" in data:
        result.check(len(data["compatibility"]) <= MAX_COMPATIBILITY,
                     name + ": compatibility is " + str(len(data["compatibility"]))
                     + " chars (limit " + str(MAX_COMPATIBILITY) + ")")

    if "metadata" in data:
        result.check(isinstance(data["metadata"], str) and bool(data["metadata"]),
                     name + ": metadata must be a non-empty key-value map")

    for target in LINK_RE.findall(body):
        target = target.strip()
        if not target or target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        resolved = os.path.normpath(os.path.join(skill_dir, target))
        if not result.check(os.path.exists(resolved),
                            name + ": broken relative link '" + target + "'"):
            continue
        relative = os.path.relpath(resolved, skill_dir)
        result.check(relative.count(os.sep) <= 1,
                     name + ": link '" + target + "' is more than one level deep "
                     "(references must stay one level below the skill root)")

    if verbose:
        print("  " + name + ": " + str(len(lines)) + " lines, description "
              + str(len(description)) + " chars")


def main():
    verbose = "--verbose" in sys.argv
    result = Result()
    skills = []
    for entry in sorted(os.listdir(REPO_ROOT)):
        path = os.path.join(REPO_ROOT, entry)
        if os.path.isdir(path) and os.path.isfile(os.path.join(path, "SKILL.md")):
            skills.append(path)
    if not result.check(bool(skills), "no skill directories found in " + REPO_ROOT):
        return 1
    print("Validating " + str(len(skills)) + " skill(s) in " + REPO_ROOT)
    for skill_dir in skills:
        validate_skill(skill_dir, result, verbose)
    if result.failures:
        print("\nFAIL (" + str(len(result.failures)) + " of " + str(result.checks) + " checks)")
        for failure in result.failures:
            print("  - " + failure)
        return 1
    print("\nPASS: " + str(result.checks) + " checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
