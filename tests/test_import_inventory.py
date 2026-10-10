"""Tests for scripts/import_inventory.py (CSV/XLSX product import). Hermetic: SQLite, no network."""
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select

openpyxl = pytest.importorskip("openpyxl")  # the script imports it at module level

from app.database.models import Product  # noqa: E402
from scripts import import_inventory as imp  # noqa: E402

HEADER = "name,description,price,stock_quantity,category,active"
REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def use_test_db(monkeypatch, session_factory):
    monkeypatch.setattr(imp, "get_session_factory", lambda: session_factory)


def write_csv(tmp_path: Path, *rows: str, header: str = HEADER) -> Path:
    path = tmp_path / "inventory.csv"
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")
    return path


def product(session_factory, name: str) -> Product | None:
    with session_factory() as s:
        return s.scalar(select(Product).where(Product.name == name))


def count(session_factory) -> int:
    with session_factory() as s:
        return s.scalar(select(func.count(Product.id)))


# ---- preview vs apply
def test_dry_run_is_the_default_and_saves_nothing(tmp_path, session_factory, capsys):
    before = count(session_factory)
    path = write_csv(tmp_path, "Brand New Gadget,Shiny,10.50,5,Gadgets,true")
    assert imp.import_inventory(path, apply_changes=False) == 0
    assert count(session_factory) == before and product(session_factory, "Brand New Gadget") is None
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "New products: 1" in out


def test_apply_creates_and_updates(tmp_path, session_factory):
    path = write_csv(
        tmp_path,
        "Brand New Gadget,Shiny,10.50,5,Gadgets,true",
        "Logitech K380 Wireless Keyboard,Updated text,36.00,3,Keyboards,false",
    )
    assert imp.import_inventory(path, apply_changes=True) == 0
    new = product(session_factory, "Brand New Gadget")
    assert (new.price, new.stock_quantity, new.category, new.active) == (Decimal("10.50"), 5, "Gadgets", True)
    k380 = product(session_factory, "Logitech K380 Wireless Keyboard")
    assert (k380.description, k380.price, k380.stock_quantity, k380.active) == ("Updated text", Decimal("36.00"), 3, False)


def test_products_missing_from_the_file_are_left_untouched(tmp_path, session_factory):
    before = product(session_factory, "Dell KB216 Wired Keyboard")
    snapshot = (before.price, before.stock_quantity, before.active)
    imp.import_inventory(write_csv(tmp_path, "Brand New Gadget,x,1.00,1,Gadgets,true"), apply_changes=True)
    after = product(session_factory, "Dell KB216 Wired Keyboard")
    assert (after.price, after.stock_quantity, after.active) == snapshot


def test_reimport_is_idempotent(tmp_path, session_factory):
    path = write_csv(tmp_path, "Brand New Gadget,x,1.00,1,Gadgets,true")
    imp.import_inventory(path, apply_changes=True)
    n = count(session_factory)
    assert imp.import_inventory(path, apply_changes=True) == 0 and count(session_factory) == n


# ---- validation: one bad row blocks the WHOLE file
BAD_ROWS = {
    "negative price": "Bad,x,-1.00,1,Cat,true",
    "three decimals": "Bad,x,1.001,1,Cat,true",
    "nan price": "Bad,x,NaN,1,Cat,true",
    "text price": "Bad,x,cheap,1,Cat,true",
    "fractional stock": "Bad,x,1.00,1.5,Cat,true",
    "negative stock": "Bad,x,1.00,-1,Cat,true",
    "bad active": "Bad,x,1.00,1,Cat,maybe",
    "empty name": ",x,1.00,1,Cat,true",
    "empty category": "Bad,x,1.00,1,,true",
    "name too long": f"{'N' * 201},x,1.00,1,Cat,true",
}


@pytest.mark.parametrize("bad_row", BAD_ROWS.values(), ids=BAD_ROWS.keys())
def test_invalid_row_blocks_entire_import(tmp_path, session_factory, capsys, bad_row):
    before = count(session_factory)
    path = write_csv(tmp_path, "Good Product,x,1.00,1,Cat,true", bad_row)
    assert imp.import_inventory(path, apply_changes=True) == 1
    assert count(session_factory) == before and product(session_factory, "Good Product") is None
    assert "Nothing imported" in capsys.readouterr().out


def test_duplicate_names_in_file_are_rejected_case_insensitively(tmp_path, session_factory):
    path = write_csv(tmp_path, "Widget,x,1.00,1,Cat,true", "WIDGET,y,2.00,2,Cat,true")
    assert imp.import_inventory(path, apply_changes=True) == 1 and product(session_factory, "Widget") is None


@pytest.mark.parametrize("raw,expected", [("yes", True), ("Y", True), ("1", True), ("FALSE", False), ("no", False), ("0", False)])
def test_active_spellings(raw, expected):
    assert imp.parse_active(raw) is expected


# ---- file-level problems
def test_missing_columns_wrong_extension_missing_file(tmp_path, capsys):
    assert imp.import_inventory(write_csv(tmp_path, "A,B", header="name,price"), True) == 1
    assert "Missing required columns" in capsys.readouterr().out
    other = tmp_path / "inventory.txt"
    other.write_text("x")
    assert imp.import_inventory(other, True) == 1 and imp.import_inventory(tmp_path / "nope.csv", True) == 1


def test_row_with_extra_fields_is_rejected(tmp_path):
    assert imp.import_inventory(write_csv(tmp_path, "W,x,1.00,1,Cat,true,EXTRA"), True) == 1


def test_row_limit_enforced(tmp_path, monkeypatch):
    monkeypatch.setattr(imp, "MAX_ROWS", 2)
    rows = [f"P{i},x,1.00,1,Cat,true" for i in range(3)]
    assert imp.import_inventory(write_csv(tmp_path, *rows), True) == 1


def test_utf8_bom_and_header_case_tolerated(tmp_path, session_factory):
    path = tmp_path / "inventory.csv"
    path.write_text("\ufeffName,Description,Price,Stock_Quantity,Category,Active\nBomProduct,x,2.00,2,Cat,yes\n", encoding="utf-8")
    assert imp.import_inventory(path, True) == 0 and product(session_factory, "BomProduct").stock_quantity == 2


def test_empty_file_with_only_header(tmp_path):
    assert imp.import_inventory(write_csv(tmp_path), True) == 1


# ---- xlsx
def test_xlsx_import_with_blank_rows_and_boolean_cells(tmp_path, session_factory):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(imp_headers := ["name", "description", "price", "stock_quantity", "category", "active"])
    ws.append(["Excel Widget", "from xlsx", 12.5, 7, "Gadgets", True])
    ws.append([None] * len(imp_headers))
    ws.append(["Excel Widget 2", "x", "3.00", 1, "Gadgets", "no"])
    path = tmp_path / "inventory.xlsx"
    wb.save(path)
    assert imp.import_inventory(path, True) == 0
    assert product(session_factory, "Excel Widget").price == Decimal("12.50")
    assert product(session_factory, "Excel Widget 2").active is False


# ---- the file shipped in the repo
def test_repo_inventory_csv_passes_validation():
    path = REPO_ROOT / "inventory.csv"
    if not path.exists():
        pytest.skip("no inventory.csv in repo")
    rows, errors = imp.validate_rows(imp.read_rows(path))
    assert not errors and rows


# ---- known gaps (strict xfail: the test flips to a failure the moment you fix the issue, so remove the marker then)
@pytest.mark.xfail(strict=True, reason="name match is case-sensitive: 'logitech k380...' creates a duplicate product; products.name uniqueness is case-sensitive too")
def test_name_match_should_be_case_insensitive(tmp_path, session_factory):
    before = count(session_factory)
    imp.import_inventory(write_csv(tmp_path, "logitech k380 wireless keyboard,x,36.00,3,Keyboards,true"), True)
    assert count(session_factory) == before


@pytest.mark.xfail(strict=True, reason="openpyxl is imported by scripts/import_inventory.py but missing from requirements.txt (CLAUDE.md §43)")
def test_openpyxl_is_declared_in_requirements():
    assert "openpyxl" in (REPO_ROOT / "requirements.txt").read_text().lower()
