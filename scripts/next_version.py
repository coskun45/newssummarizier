#!/usr/bin/env python3
"""Bir sonraki deploy sürümünü (X.Y.0) hesaplar — .github/workflows/ci-cd.yml tarafından çağrılır.

  * MAJOR = `frontend/src/data/features.json` içindeki en yüksek `vN` (Ayarlar › Features).
    Yeni major başlatmak = features.json'a yeni bir `vN` bloğu eklemek.
  * MINOR = o major içindeki mevcut git tag'lerinin (`vX.Y.Z`) en yüksek minor'ü + 1;
    bu major için hiç tag yoksa `N.0.0`. Patch hep 0.

Tag listesi stdin'den okunur (`git tag --list 'v*' | next_version.py --features ...`),
sonuç stdout'a `X.Y.Z` olarak yazılır.
"""
import argparse
import json
import re
import sys
from pathlib import Path
from typing import Iterable, List, Tuple

TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
VERSION_RE = re.compile(r"^v(\d+)$")

Version = Tuple[int, int, int]


def latest_major(features_path: Path) -> int:
    """features.json'daki en yüksek `vN` numarası."""
    data = json.loads(Path(features_path).read_text(encoding="utf-8"))
    majors = []
    for entry in data["versions"]:
        match = VERSION_RE.match(entry["version"])
        if not match:
            raise ValueError(f"Geçersiz features sürümü: {entry['version']!r} (beklenen: vN)")
        majors.append(int(match.group(1)))
    if not majors:
        raise ValueError("features.json'da hiç sürüm yok")
    return max(majors)


def parse_tags(lines: Iterable[str]) -> List[Version]:
    """Yalnızca `vX.Y.Z` biçimindeki tag'leri döndürür; diğerleri yok sayılır."""
    tags = []
    for line in lines:
        match = TAG_RE.match(line.strip())
        if match:
            tags.append((int(match.group(1)), int(match.group(2)), int(match.group(3))))
    return tags


def next_version(major: int, tags: List[Version]) -> str:
    """`major` için bir sonraki sürüm: aynı major'daki en yüksek minor + 1, yoksa `major.0.0`."""
    highest_tag_major = max((t[0] for t in tags), default=0)
    if highest_tag_major > major:
        raise ValueError(
            f"Mevcut tag major'ı (v{highest_tag_major}) features.json'daki en yüksek sürümden "
            f"(v{major}) büyük — features.json geri mi alındı? Sürüm düşürülmüyor."
        )
    minors = [t[1] for t in tags if t[0] == major]
    if not minors:
        return f"{major}.0.0"
    return f"{major}.{max(minors) + 1}.0"


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--features", required=True, type=Path, help="features.json yolu")
    args = parser.parse_args(argv)
    try:
        print(next_version(latest_major(args.features), parse_tags(sys.stdin.read().splitlines())))
    except ValueError as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
