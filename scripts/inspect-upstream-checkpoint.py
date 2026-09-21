#!/usr/bin/env python3
"""Inspect a pinned public Helium checkpoint without extracting or executing it."""
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import threading
import zipfile

REPOSITORY = "imputnet/helium-macos"
RUN = 35283975532
ARTIFACT = 10534986217
SHA256 = "d777ec2fafb4be162babbdf7c7b1b01210fb559940e763cca00fca7fba999ce2"
OUT = Path("build/reuse-qualification")
ZIP = OUT / "upstream-arm64-checkpoint.zip"
SELECTED = {
    "src/out/Default/args.gn",
    "src/out/Default/build.ninja",
    "src/out/Default/toolchain.ninja",
    "src/out/Default/obj/base/base.ninja",
    "src/out/Default/obj/chrome/browser/browser.ninja",
    "src/third_party/llvm-build/Release+Asserts/cr_build_revision",
    "src/chrome/VERSION",
}


def inspect(path):
    totals = {"files": 0, "bytes": 0, "output_files": 0,
              "output_bytes": 0, "object_files": 0, "object_bytes": 0}
    samples, state, selected, truncated = [], [], [], []
    errors = []
    with zipfile.ZipFile(path) as archive:
        inner = archive.open("build_src.tar.zst")
        decoder = subprocess.Popen(["zstd", "-dq", "-c", "-M128MB"],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        def feed():
            try:
                with inner, decoder.stdin:
                    while chunk := inner.read(256 * 1024):
                        decoder.stdin.write(chunk)
            except Exception as error:
                errors.append(str(error))
        producer = threading.Thread(target=feed)
        producer.start()
        try:
            with tarfile.open(fileobj=decoder.stdout, mode="r|") as tree:
                for item in tree:
                    # Do not retain every TarInfo for this very large source tree.
                    tree.members.clear()
                    if not item.isfile():
                        continue
                    name = item.name.removeprefix("./")
                    totals["files"] += 1
                    totals["bytes"] += item.size
                    if totals["bytes"] > 200 * 1024**3:
                        raise RuntimeError("Archive exceeds the bounded inspection size")
                    if name.startswith("src/out/Default/"):
                        totals["output_files"] += 1
                        totals["output_bytes"] += item.size
                        if name.endswith(".o"):
                            totals["object_files"] += 1
                            totals["object_bytes"] += item.size
                            if len(samples) < 12:
                                samples.append({"path": name, "bytes": item.size})
                        if "siso" in name or name.endswith(".ninja_log"):
                            if len(state) < 30:
                                state.append({"path": name, "bytes": item.size})
                    if name in SELECTED:
                        # Large generated Ninja manifests need only a bounded
                        # prefix for configuration inspection; continue inventory.
                        target = OUT / name.replace("/", "__")
                        retained = min(item.size, 128 * 1024)
                        with tree.extractfile(item) as contents:
                            target.write_bytes(contents.read(retained))
                        selected.append(name)
                        if retained < item.size:
                            truncated.append({"path": name, "bytes": item.size,
                                              "retained_bytes": retained})
            # Consume tar padding so the bounded producer can finish.
            while decoder.stdout.read(256 * 1024):
                pass
            producer.join(timeout=60)
            if producer.is_alive():
                raise RuntimeError("Archive producer did not finish")
            if decoder.wait(timeout=30) or errors:
                raise RuntimeError("Checkpoint decompression failed: " + repr(errors))
        finally:
            decoder.stdout.close()
            if decoder.poll() is None:
                decoder.terminate()
                try:
                    decoder.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    decoder.kill()
                    decoder.wait(timeout=10)
            producer.join(timeout=10)
    return {"upstream_repository": REPOSITORY, "run": RUN,
            "artifact": ARTIFACT, "zip_sha256": SHA256, "totals": totals,
            "object_samples": samples, "build_state_samples": state,
            "selected_metadata": selected, "truncated_metadata": truncated,
            "scope": "Archive inventory only; no compilation or object reuse demonstrated."}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    if not ZIP.exists():
        part = ZIP.with_suffix(".zip.part")
        with part.open("xb") as stream:
            subprocess.run(["gh", "api", f"repos/{REPOSITORY}/actions/artifacts/{ARTIFACT}/zip"],
                           stdout=stream, check=True)
        part.rename(ZIP)
    digest = hashlib.sha256()
    with ZIP.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    if digest.hexdigest() != SHA256:
        raise RuntimeError("GitHub artifact digest mismatch; refusing inspection")
    report = inspect(ZIP)
    (OUT / "checkpoint-inventory.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
