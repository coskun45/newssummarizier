#!/usr/bin/env python3
"""Sunucuda tek yapılandırma dosyasını (repo kökü `.env`) hazırlar / günceller.

deploy.sh (interaktif ilk kurulum) ve .github/workflows/deploy.yml (otomatik deploy)
tarafından ortak kullanılır. İdempotenttir — mevcut değerlere dokunmaz:

  * `.env` yoksa `.env.example`'dan üretir; rastgele POSTGRES_PASSWORD ve JWT_SECRET_KEY atar.
  * Eski düzenden kalan `backend/.env` varsa değerlerini `.env`'ye taşır (mevcut `.env`
    değerlerini ezmez; container'a özel anahtarlar hariç) ve dosyayı, `.env` yazıldıktan
    SONRA `backend/.env.migrated`'e yeniden adlandırır.
  * `.env.example`'da olup `.env`'de olmayan anahtarları ekler.
  * Ortam değişkeni olarak verilen OPENAI_API_KEY / ADMIN_EMAIL / ADMIN_PASSWORD
    yalnızca `.env`'de boş ya da placeholder ise yazılır (elle değiştirilmiş değeri ezmez).
  * DEBUG=False yapar; --server-ip verilirse CORS_ORIGINS'i (varsayılandaysa) http://<ip> yapar.

Secret'ları asla stdout'a yazmaz.
"""
import argparse
import os
import secrets
import sys
from pathlib import Path
from typing import Dict, List, Optional

DEFAULT_JWT = "change-me-in-production-use-32-char-minimum-secret-key"
PLACEHOLDERS = {
    "OPENAI_API_KEY": {"your-openai-api-key-here"},
    "JWT_SECRET_KEY": {DEFAULT_JWT},
}
# docker-compose.yml bunları container içinde zaten kendisi belirler; eski dosyadan taşınmaz.
CONTAINER_ONLY = {"DATABASE_URL", "CHECKPOINTS_DB", "BULLETIN_STORAGE_DIR"}
# Ortam değişkeninden gelen ilk-kurulum değerleri.
INITIAL_FROM_ENV = ("OPENAI_API_KEY", "ADMIN_EMAIL", "ADMIN_PASSWORD")


def _split(line: str) -> Optional[tuple]:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    key, value = stripped.split("=", 1)
    return key.strip(), value


def _read(path: Path) -> List[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _get(lines: List[str], key: str) -> Optional[str]:
    """Değer, satır içi ` # yorum` kısmı atılarak."""
    for line in lines:
        kv = _split(line)
        if kv and kv[0] == key:
            return kv[1].split(" #")[0].strip()
    return None


def _set(lines: List[str], key: str, value: str) -> None:
    for i, line in enumerate(lines):
        kv = _split(line)
        if kv and kv[0] == key:
            lines[i] = f"{key}={value}"
            return
    lines.append(f"{key}={value}")


def _only_localhost(cors: str) -> bool:
    """Eski deploy'ların bıraktığı yalnızca-localhost listeleri de varsayılan sayılır."""
    origins = [o.strip() for o in cors.split(",") if o.strip()]
    return bool(origins) and all(o.split("://", 1)[-1].split(":")[0] in ("localhost", "127.0.0.1") for o in origins)


def _is_unset(lines: List[str], key: str) -> bool:
    current = _get(lines, key)
    return current is None or current == "" or current in PLACEHOLDERS.get(key, set())


def ensure_env(root: Path, initial: Dict[str, str], server_ip: Optional[str] = None) -> Dict[str, bool]:
    """`root/.env`'yi hazırlar. Yapılanları döndürür (secret içermez)."""
    env_path = root / ".env"
    example_path = root / ".env.example"
    legacy_path = root / "backend" / ".env"
    jwt_file = root / ".jwt_secret"

    example_lines = _read(example_path)
    fresh = not env_path.exists()
    lines = list(example_lines) if fresh else _read(env_path)
    done = {"created": fresh, "migrated_legacy": False}

    if fresh:
        password = secrets.token_urlsafe(24)
        user = _get(lines, "POSTGRES_USER") or "bulten"
        db = _get(lines, "POSTGRES_DB") or "bulten"
        _set(lines, "POSTGRES_PASSWORD", password)
        _set(lines, "DATABASE_URL", f"postgresql+psycopg2://{user}:{password}@localhost:5432/{db}")

    legacy_to_rename = None
    if legacy_path.exists():
        # Taze .env'de eski dosya şablon varsayılanlarını ezer; mevcut .env'de ise zaten
        # tanımlı (elle değiştirilmiş olabilecek) değerler korunur, sadece eksikler tamamlanır.
        existing = {kv[0] for kv in map(_split, lines) if kv}
        for line in _read(legacy_path):
            kv = _split(line)
            if kv and kv[0] not in CONTAINER_ONLY and (fresh or kv[0] not in existing):
                _set(lines, kv[0], kv[1])
        legacy_to_rename = legacy_path
        done["migrated_legacy"] = True

    if jwt_file.exists() and _is_unset(lines, "JWT_SECRET_KEY"):
        _set(lines, "JWT_SECRET_KEY", jwt_file.read_text(encoding="utf-8").strip())

    present = {kv[0] for kv in map(_split, lines) if kv}
    for line in example_lines:
        kv = _split(line)
        if kv and kv[0] not in present:
            lines.append(line.strip())

    for key in INITIAL_FROM_ENV:
        if initial.get(key) and _is_unset(lines, key):
            _set(lines, key, initial[key])

    if _is_unset(lines, "JWT_SECRET_KEY"):
        _set(lines, "JWT_SECRET_KEY", secrets.token_hex(32))

    _set(lines, "DEBUG", "False")

    if server_ip:
        example_cors = _get(example_lines, "CORS_ORIGINS")
        current_cors = _get(lines, "CORS_ORIGINS")
        if current_cors in (None, "", example_cors) or _only_localhost(current_cors):
            _set(lines, "CORS_ORIGINS", f"http://{server_ip}")

    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if legacy_to_rename is not None:
        legacy_to_rename.rename(legacy_to_rename.with_name(".env.migrated"))
    try:
        env_path.chmod(0o600)
    except OSError:
        pass
    return done


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--server-ip", help="CORS_ORIGINS için sunucu IP'si")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]), help="Repo kökü")
    args = parser.parse_args()

    root = Path(args.root)
    if not (root / ".env.example").exists():
        print(f"HATA: {root / '.env.example'} bulunamadı.", file=sys.stderr)
        return 1

    initial = {k: os.environ.get(k, "") for k in INITIAL_FROM_ENV}
    done = ensure_env(root, initial, args.server_ip)
    print(f"[✓] {root / '.env'} " + ("oluşturuldu" if done["created"] else "güncel"))
    if done["migrated_legacy"]:
        print("[✓] backend/.env değerleri .env'ye taşındı (eski dosya: backend/.env.migrated)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
