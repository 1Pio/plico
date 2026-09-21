#!/usr/bin/env python3
"""Sequential native syntax check with a streaming GN compilation database read."""
import json
import argparse
from pathlib import Path
import shlex
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--overlay', type=Path)
parser.add_argument('files', nargs='*')
args = parser.parse_args()
database = root / "build/src/out/Default/compile_commands.json"
entry = None
block = []
with database.open() as source:
    for line in source:
        if line.strip() == "{":
            block = [line]
        elif block:
            block.append(line)
            if line.strip() in ("}", "},"):
                if any('"file": "../../chrome/browser/ui/views/frame/browser_view.cc"' in part
                       for part in block):
                    entry = json.loads("".join(block).rstrip().rstrip(","))
                    break
                block = []
if entry is None:
    raise SystemExit("No baseline BrowserView compilation command was found.")

base = []
tokens = iter(shlex.split(entry["command"]))
for token in tokens:
    if token in ("-o", "-MF", "-MT", "-MQ"):
        next(tokens)
    elif token not in ("-MD", "-MMD", "-c", entry["file"]):
        base.append(token)
# Read edited Plico headers before the last synchronized copy in build/src.
# Chromium's command already contains -I../.., so appending this path silently
# checks a mixture of current sources and stale generated headers.
base[1:1] = ["-I" + str(root)]
base += ["-fsyntax-only", "-ferror-limit=10"]
if args.overlay:
    base[1:1] = ['-I' + str(args.overlay.resolve())]
paths = args.files or [str(path.relative_to(root)) for path in sorted((root / "plico/native").glob("*"))
                         if path.suffix in (".cc", ".mm")]
for name in paths:
    path = root / name
    command = base.copy()
    if path.suffix == ".mm":
        command += ["-x", "objective-c++", "-fobjc-arc"]
    command.append(str(path))
    print("Checking " + str(path.relative_to(root)), flush=True)
    result = subprocess.run(command, cwd=entry["directory"])
    if result.returncode:
        raise SystemExit(result.returncode)
