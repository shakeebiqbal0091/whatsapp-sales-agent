from decimal import Decimal

from app.services.sales_service import SalesService


def svc(session) -> SalesService:
    return SalesService(session, "USD")


def test_search_finds_relevant_products_ranked(session):
    results = svc(session).search_products("wireless keyboard")
    names = [p.name for p in results]
    assert "Logitech K380 Wireless Keyboard" in names
    assert all("Keyboard" in n or "Wireless" in n for n in names)
    assert names[0].endswith("Keyboard")  # keyboard-and-wireless beats wireless-only matches


def test_plural_and_case_insensitive(session):
    assert svc(session).search_products("KEYBOARDS")


def test_unknown_product_returns_nothing(session):
    assert svc(session).search_products("spaceship") == []


def test_inactive_products_are_hidden(session):
    names = [p.name for p in svc(session).search_products("legacy PS/2 keyboard", limit=50)]
    assert "Legacy PS/2 Keyboard" not in names
    assert "Dell KB216 Wired Keyboard" in names  # active keyboards still returned


def test_stopword_only_query_lists_catalogue(session):
    assert len(svc(session).search_products("what products do you have?")) == 5


def test_price_is_exact_from_db(session):
    k380 = svc(session).search_products("K380")[0]
    assert k380.price == Decimal("35.00") and k380.currency == "USD"


def test_stock_insufficient(session):
    k380 = svc(session).search_products("K380")[0]
    check = svc(session).check_stock(k380.id, 20)
    assert check.stock == 12 and check.requested == 20 and check.available is False


def test_stock_sufficient_and_out_of_stock(session):
    k380 = svc(session).search_products("K380")[0]
    assert svc(session).check_stock(k380.id, 5).available is True
    mx_keys = svc(session).search_products("MX Keys")[0]
    assert svc(session).check_stock(mx_keys.id).available is False


def test_missing_product_stock(session):
    assert svc(session).check_stock(99999, 1) is None


def test_search_is_injection_safe(session):
    assert svc(session).search_products("'; DROP TABLE products; --") == []
    assert svc(session).search_products("keyboard")  # table still there
