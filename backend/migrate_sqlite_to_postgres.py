"""
Migration script: var olan SQLite verisini (backend/news_summary.db) Postgres'e taşır.

Bu, bir kerelik veri göçü script'idir — `init_db()`'deki idempotent kolon-ekleme
mekanizmasından farklı olarak (bkz. app/db/database.py), şema değil VERİ taşır.

Kullanım (DATABASE_URL zaten hedef Postgres'i işaret etmeli):

    # 1) Önce SADECE Postgres'i ayağa kaldır — backend'i henüz BAŞLATMA.
    #    (backend her başlangıçta seed_database() çalıştırır; topics/feeds/
    #    system_prompts tablolarına idempotent seed verisi ekler. Migrasyon
    #    ondan ÖNCE çalışmalı, yoksa aynı satırları ikinci kez eklemeye
    #    çalışıp unique constraint hatası alırsın.)
    docker compose up -d db

    # 2) Migrasyonu, gerçek backend servisini başlatmadan, tek seferlik bir
    #    container'da çalıştır (`run`, backend'in normal CMD'sini atlar —
    #    yani FastAPI/seed_database() hiç tetiklenmez):
    docker compose run --rm backend python migrate_sqlite_to_postgres.py \\
        --sqlite-path /app/data/news_summary.db

    # 3) Migrasyon bittikten SONRA backend'i (ve geri kalanını) normal başlat.
    #    seed_database() artık migrasyonla gelen satırları bulup atlayacaktır.
    docker compose up -d

Yerelde (Docker dışında) çalıştırırken --sqlite-path ile gerçek dosya yolunu ver ve
DATABASE_URL ortam değişkenini hedef Postgres DSN'ine ayarla.

Script FK'lere göre topolojik sıralı şekilde (Base.metadata.sorted_tables) her tabloyu
kopyalar, integer id PK'lı tablolarda kopyalama sonrası Postgres sequence'ini
(gelecekteki INSERT'lerin migrasyonla gelen id'lerle çakışmaması için) resetler, ve
kaynak/hedef satır sayılarını karşılaştırıp özet basar. Hedef tablolar zaten doluysa
(yanlışlıkla ikinci kez çalıştırmayı önlemek için) --force verilmeden durur.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import create_engine, insert, select, text

from app.core.config import settings
from app.db.database import Base, engine as target_engine
# Importing the module (not just Base) is required: it's what registers every
# model's Table onto Base.metadata. Without it, Base.metadata.sorted_tables is
# empty and this script would silently "succeed" without copying anything.
from app.db import models  # noqa: F401

CHUNK_SIZE = 500


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sqlite-path",
        default="news_summary.db",
        help="Kaynak SQLite dosyasının yolu (varsayılan: news_summary.db)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Hedef tablolarda satır olsa bile devam et (veri ikilemesi riski)",
    )
    return parser.parse_args()


def reset_sequence(conn, table):
    """Postgres-only: bump the id sequence past the just-migrated explicit ids
    so future INSERTs don't collide with them. No-op on any other dialect
    (e.g. sqlite, used as the target in tests) since there is no sequence."""
    if conn.engine.dialect.name != "postgresql":
        return
    pk_columns = list(table.primary_key.columns)
    if len(pk_columns) != 1 or pk_columns[0].name != "id":
        return
    conn.execute(
        text(
            "SELECT setval(pg_get_serial_sequence(:tbl, 'id'), "
            f'COALESCE((SELECT MAX(id) FROM "{table.name}"), 1), true)'
        ),
        {"tbl": table.name},
    )


def target_has_data(engine):
    """Returns (table_name, count) for the first non-empty table, or (None, 0)."""
    with engine.connect() as conn:
        for table in Base.metadata.sorted_tables:
            count = conn.execute(text(f'SELECT COUNT(*) FROM "{table.name}"')).scalar()
            if count:
                return table.name, count
    return None, 0


def migrate_data(source_engine, target_engine, chunk_size=CHUNK_SIZE):
    """Copies every table (FK-safe order) from source_engine into target_engine.

    Returns (source_counts, target_counts) dicts keyed by table name, so the
    caller can verify row counts match.
    """
    Base.metadata.create_all(bind=target_engine)
    tables = Base.metadata.sorted_tables

    source_counts = {}
    target_counts = {}

    with source_engine.connect() as source_conn, target_engine.begin() as target_conn:
        for table in tables:
            rows = [dict(row) for row in source_conn.execute(select(table)).mappings().all()]
            source_counts[table.name] = len(rows)

            for i in range(0, len(rows), chunk_size):
                chunk = rows[i : i + chunk_size]
                if chunk:
                    target_conn.execute(insert(table), chunk)

            reset_sequence(target_conn, table)

            target_counts[table.name] = len(target_conn.execute(select(table)).mappings().all())

    return source_counts, target_counts


def main():
    args = parse_args()

    if "sqlite" in settings.database_url:
        print(
            "HATA: DATABASE_URL hala SQLite'i isaret ediyor "
            f"({settings.database_url}). Bu script'i DATABASE_URL Postgres'e "
            "isaret ederken calistir (orn. docker compose exec backend python "
            "migrate_sqlite_to_postgres.py ...)."
        )
        sys.exit(1)

    if not os.path.isfile(args.sqlite_path):
        print(f"HATA: SQLite dosyasi bulunamadi: {args.sqlite_path}")
        sys.exit(1)

    # Şema henüz yoksa (backend hiç başlamadıysa) target_has_data'nın COUNT(*)
    # sorgusu "relation does not exist" ile patlar — önce şemayı garanti et.
    Base.metadata.create_all(bind=target_engine)

    if not args.force:
        table_name, count = target_has_data(target_engine)
        if table_name:
            print(
                f"HATA: Hedef tablo '{table_name}' zaten {count} satir iceriyor. "
                "Yanlislikla veri ikilemesini onlemek icin duruluyor. "
                "Bastan baslamak icin --force kullan."
            )
            sys.exit(1)

    source_engine = create_engine(f"sqlite:///{args.sqlite_path}")
    source_counts, target_counts = migrate_data(source_engine, target_engine)

    print("Ozet:")
    mismatch = False
    for table in Base.metadata.sorted_tables:
        src, dst = source_counts[table.name], target_counts[table.name]
        status = "OK" if src == dst else "UYUSMUYOR"
        mismatch = mismatch or src != dst
        print(f"  {table.name:<35} kaynak={src:<6} hedef={dst:<6} {status}")

    if mismatch:
        print("\nHATA: Bazi tablolarda satir sayisi uyusmuyor.")
        sys.exit(1)

    print("\nMigrasyon tamamlandi.")


if __name__ == "__main__":
    main()
