"""Fetch the pinned HIPE-OCRepair data release into the path expected by the loader."""
from __future__ import annotations
import argparse
import io
import shutil
import tarfile
import urllib.request
from pathlib import Path

REPO = "https://codeload.github.com/hipe-eval/HIPE-OCRepair-2026-data/tar.gz/refs/tags/v0.9.5"
DEFAULT_TARGET = Path(__file__).resolve().parents[1] / "related_source" / "HIPE-OCRepair-2026-data-0.9.5"

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--url", default=REPO)
    args = parser.parse_args()
    target = args.target.resolve()
    if (target / "data" / "v0.9").is_dir():
        print(f"HIPE data already present: {target}")
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading HIPE data to {target} ...")
    with urllib.request.urlopen(args.url, timeout=120) as response:
        payload = response.read()
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        roots = {member.name.split("/", 1)[0] for member in archive.getmembers() if member.name}
        if len(roots) != 1:
            raise RuntimeError(f"Unexpected archive roots: {sorted(roots)}")
        temp = target.parent / (target.name + ".download")
        if temp.exists():
            shutil.rmtree(temp)
        archive.extractall(temp.parent)
        extracted = temp.parent / next(iter(roots))
        if target.exists():
            shutil.rmtree(target)
        extracted.rename(target)
    if not (target / "data" / "v0.9").is_dir():
        raise RuntimeError(f"Archive has no data/v0.9 directory: {target}")
    print(f"Installed HIPE data: {target}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
