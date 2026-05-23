"""
Database inspection & maintenance helper.

Usage from the project root:

    # Create DB & seed default roles + admin (no model training)
    python scripts/db_inspect.py init

    # Show all tables and row counts
    python scripts/db_inspect.py summary

    # Show rows of one table (default 10)
    python scripts/db_inspect.py show users
    python scripts/db_inspect.py show transaction_records --limit 25

    # Export a table to CSV (so you can share with a teammate)
    python scripts/db_inspect.py export users --out users.csv

    # Change a field (safe, single row)
    python scripts/db_inspect.py update users 1 full_name "Alice Admin"

    # Delete a row
    python scripts/db_inspect.py delete audit_logs 42

The DB lives at <project_root>/fraud_detection.db. To share the whole DB
with another person, just send that one .db file.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

# Make the src package importable when this script is run directly.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from flask import Flask  # noqa: E402

from src.database import db, init_db  # noqa: E402
from src.database.models import (  # noqa: E402
    AuditLog, BankAccount, Card, Role, TransactionRecord, User,
)


TABLE_MODELS = {
    "users": User,
    "roles": Role,
    "audit_logs": AuditLog,
    "transaction_records": TransactionRecord,
    "bank_accounts": BankAccount,
    "cards": Card,
}


def make_app() -> Flask:
    """A minimal Flask app just for DB access (no model training)."""
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{ROOT / 'fraud_detection.db'}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    init_db(app)
    return app


def cmd_init(app: Flask) -> None:
    """Create the schema and seed default roles + admin user."""
    with app.app_context():
        db.create_all()
        from src.auth.init_roles import (
            create_default_admin, ensure_user_columns, init_default_roles,
        )
        ensure_user_columns()
        init_default_roles()
        create_default_admin()
        db.session.commit()
        print(f"Database ready -> {ROOT / 'fraud_detection.db'}")
        print("Default admin login: admin / admin123  (CHANGE IN PRODUCTION)")


def cmd_summary(app: Flask) -> None:
    """Print a row count for every table."""
    with app.app_context():
        print(f"{'TABLE':<25} {'ROWS':>10}")
        print("-" * 36)
        for name, model in TABLE_MODELS.items():
            print(f"{name:<25} {model.query.count():>10}")


def cmd_show(app: Flask, table: str, limit: int) -> None:
    """Pretty-print rows of one table."""
    model = TABLE_MODELS.get(table)
    if not model:
        sys.exit(f"Unknown table '{table}'. Choose from: {', '.join(TABLE_MODELS)}")
    with app.app_context():
        rows = model.query.limit(limit).all()
        if not rows:
            print(f"(table '{table}' is empty)")
            return
        for row in rows:
            data = row.to_dict() if hasattr(row, "to_dict") else {
                c.name: getattr(row, c.name) for c in row.__table__.columns
            }
            print("-" * 60)
            for k, v in data.items():
                print(f"  {k:<22} {v}")


def cmd_export(app: Flask, table: str, out: Path) -> None:
    """Export a table to CSV for sharing."""
    model = TABLE_MODELS.get(table)
    if not model:
        sys.exit(f"Unknown table '{table}'")
    with app.app_context():
        rows = model.query.all()
        if not rows:
            print(f"(table '{table}' is empty)")
            return
        cols = [c.name for c in model.__table__.columns]
        with out.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(cols)
            for row in rows:
                writer.writerow([getattr(row, c) for c in cols])
        print(f"Wrote {len(rows)} rows -> {out}")


def cmd_update(app: Flask, table: str, row_id: int, field: str, value: str) -> None:
    """Change one field on one row."""
    model = TABLE_MODELS.get(table)
    if not model:
        sys.exit(f"Unknown table '{table}'")
    if field not in {c.name for c in model.__table__.columns}:
        sys.exit(f"Column '{field}' not in table '{table}'")
    with app.app_context():
        row = model.query.get(row_id)
        if not row:
            sys.exit(f"No row with id={row_id} in '{table}'")
        old = getattr(row, field)
        setattr(row, field, value)
        db.session.commit()
        print(f"OK  {table}#{row_id}.{field}: {old!r} -> {value!r}")


def cmd_delete(app: Flask, table: str, row_id: int) -> None:
    """Delete a row by id."""
    model = TABLE_MODELS.get(table)
    if not model:
        sys.exit(f"Unknown table '{table}'")
    with app.app_context():
        row = model.query.get(row_id)
        if not row:
            sys.exit(f"No row with id={row_id} in '{table}'")
        db.session.delete(row)
        db.session.commit()
        print(f"OK  deleted {table}#{row_id}")


def main() -> None:
    p = argparse.ArgumentParser(description="Inspect/edit fraud_detection.db")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="Create schema + seed roles/admin")
    sub.add_parser("summary", help="Row counts per table")

    sp = sub.add_parser("show", help="Show rows of a table")
    sp.add_argument("table")
    sp.add_argument("--limit", type=int, default=10)

    sp = sub.add_parser("export", help="Export a table to CSV")
    sp.add_argument("table")
    sp.add_argument("--out", type=Path, required=True)

    sp = sub.add_parser("update", help="Change one field on one row")
    sp.add_argument("table"); sp.add_argument("row_id", type=int)
    sp.add_argument("field"); sp.add_argument("value")

    sp = sub.add_parser("delete", help="Delete one row by id")
    sp.add_argument("table"); sp.add_argument("row_id", type=int)

    args = p.parse_args()
    app = make_app()

    if args.cmd == "init":     cmd_init(app)
    elif args.cmd == "summary": cmd_summary(app)
    elif args.cmd == "show":    cmd_show(app, args.table, args.limit)
    elif args.cmd == "export":  cmd_export(app, args.table, args.out)
    elif args.cmd == "update":  cmd_update(app, args.table, args.row_id, args.field, args.value)
    elif args.cmd == "delete":  cmd_delete(app, args.table, args.row_id)


if __name__ == "__main__":
    main()
