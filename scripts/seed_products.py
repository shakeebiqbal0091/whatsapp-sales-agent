"""Idempotent product seed (upsert by name). Run via scripts/seed_database.py."""
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Product

PRODUCTS = [
    ("Logitech K380 Wireless Keyboard", "Compact multi-device Bluetooth keyboard", "35.00", 12, "Keyboards", True),
    ("Keychron K2 Mechanical Keyboard", "Wireless 75% mechanical keyboard, hot-swappable", "89.00", 5, "Keyboards", True),
    ("Dell KB216 Wired Keyboard", "Full-size wired USB keyboard", "15.00", 40, "Keyboards", True),
    ("Logitech MX Keys Wireless Keyboard", "Backlit wireless keyboard for productivity", "109.00", 0, "Keyboards", True),
    ("Logitech M185 Wireless Mouse", "Compact wireless mouse, 12-month battery", "14.00", 30, "Mice", True),
    ("Logitech MX Master 3S Wireless Mouse", "Ergonomic wireless mouse, silent clicks", "99.00", 7, "Mice", True),
    ("Razer DeathAdder Gaming Mouse", "Wired ergonomic gaming mouse", "49.00", 10, "Mice", True),
    ("Sony WH-CH520 Wireless Headphones", "Bluetooth on-ear headphones, 50h battery", "59.00", 15, "Audio", True),
    ("JBL Tune 510BT Headphones", "Wireless on-ear headphones", "39.00", 20, "Audio", True),
    ("Anker 65W USB-C Charger", "Fast GaN wall charger, 2 ports", "29.00", 25, "Accessories", True),
    ("Samsung 27in Full HD Monitor", "27-inch IPS monitor, 75Hz", "159.00", 6, "Monitors", True),
    ("Legacy PS/2 Keyboard", "Discontinued model", "9.00", 3, "Keyboards", False),
    ("Logitech K120 Wired Keyboard", "Full-size USB office keyboard", "12.00", 35, "Keyboards", True),
    ("Keychron K6 Mechanical Keyboard", "Compact wireless mechanical keyboard", "79.00", 9, "Keyboards", True),
    ("Logitech G502 HERO Gaming Mouse", "Wired gaming mouse with customizable buttons", "45.00", 11, "Mice", True),
    ("Microsoft Bluetooth Mouse", "Compact Bluetooth mouse", "24.00", 18, "Mice", True),
    ("Dell Inspiron 15 Laptop", "15.6-inch laptop for work and study", "649.00", 8, "Laptops", True),
    ("Lenovo IdeaPad Slim 3", "Laptop for everyday work and study", "499.00", 12, "Laptops", True),
    ("HP Pavilion 14 Laptop", "14-inch laptop with SSD storage", "579.00", 6, "Laptops", True),
    ("Dell 24-inch Full HD Monitor", "24-inch Full HD monitor", "139.00", 7, "Monitors", True),
    ("LG 27-inch QHD Monitor", "27-inch QHD productivity monitor", "279.00", 4, "Monitors", True),
    ("Logitech C920 HD Webcam", "1080p webcam for video calls", "69.00", 10, "Webcams", True),
    ("Anker USB-C Hub 7-in-1", "USB-C hub with HDMI and USB ports", "39.00", 14, "Accessories", True),
]


def seed_products(session: Session) -> int:
    created = 0
    for name, description, price, stock, category, active in PRODUCTS:
        product = session.scalar(select(Product).where(Product.name == name))
        if product is None:
            product = Product(name=name)
            session.add(product)
            created += 1
        product.description, product.price = description, Decimal(price)
        product.stock_quantity, product.category, product.active = stock, category, active
    session.commit()
    return created
