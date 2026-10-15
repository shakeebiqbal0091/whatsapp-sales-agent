"""Read-only HTTP client for the Inventory Management System API."""

import math
from typing import Any
from urllib.parse import quote

import httpx


class InventoryAPIError(Exception):
    """Raised when the inventory API request or response is invalid."""


class InventoryClient:
    """Read product catalogue and stock from the inventory API."""

    def __init__(
        self,
        base_url: str | None,
        token: str | None = None,
        timeout: float = 15.0,
    ) -> None:
        self.base_url = (base_url or "").strip().rstrip("/")
        self.token = token.strip() if token else None
        self.timeout = timeout

    @staticmethod
    def _parse_product(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise InventoryAPIError("Inventory API returned an invalid product.")

        product_id = value.get("id")
        name = value.get("name")
        price = value.get("price")
        quantity = value.get("quantity")

        if (
            not isinstance(product_id, str)
            or not product_id
            or not isinstance(name, str)
            or not name
            or isinstance(price, bool)
            or not isinstance(price, (int, float))
            or (isinstance(price, float) and not math.isfinite(price))
            or isinstance(quantity, bool)
            or not isinstance(quantity, int)
            or quantity < 0
        ):
            raise InventoryAPIError("Inventory API returned an invalid product.")

        return {
            "id": product_id,
            "name": name,
            "price": price,
            "quantity": quantity,
        }

    @staticmethod
    def _data(payload: Any) -> Any:
        if (
            not isinstance(payload, dict)
            or payload.get("success") is not True
            or "data" not in payload
        ):
            raise InventoryAPIError("Inventory API returned an invalid response.")
        return payload["data"]

    def _get(
        self,
        path: str,
        *,
        allow_not_found: bool = False,
    ) -> Any:
        """Send an authenticated GET request and return its JSON response."""
        if not self.base_url or not self.token:
            raise InventoryAPIError("Inventory API is not configured.")

        url = f"{self.base_url}/{path.lstrip('/')}"
        headers = {
            "X-Inventory-Service-Request": "true",
            "Authorization": f"Bearer {self.token}",
        }

        try:
            response = httpx.get(
                url,
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            if allow_not_found and exc.response.status_code == 404:
                return None
            raise InventoryAPIError("Inventory API request failed.") from None
        except httpx.TimeoutException:
            raise InventoryAPIError("Inventory API request timed out.") from None
        except httpx.InvalidURL:
            raise InventoryAPIError("Inventory API configuration is invalid.") from None
        except httpx.HTTPError:
            raise InventoryAPIError("Inventory API request failed.") from None
        except ValueError:
            raise InventoryAPIError("Inventory API returned invalid JSON.") from None

    def list_products(self) -> list[dict[str, Any]]:
        """List products from GET /api/products."""
        payload = self._data(self._get("api/products"))
        if not isinstance(payload, list):
            raise InventoryAPIError("Inventory API returned an invalid product list.")
        return [self._parse_product(product) for product in payload]

    def list_low_stock_products(self) -> list[dict[str, Any]]:
        """List low-stock products from GET /api/products/low-stock."""
        payload = self._data(self._get("api/products/low-stock"))
        if not isinstance(payload, list):
            raise InventoryAPIError("Inventory API returned an invalid product list.")
        return [self._parse_product(product) for product in payload]

    def get_product(self, product_id: str) -> dict[str, Any] | None:
        """Return one product from GET /api/products/:id, or None if absent."""
        if not product_id:
            raise InventoryAPIError("A product ID is required.")

        payload = self._get(
            f"api/products/{quote(product_id, safe='')}",
            allow_not_found=True,
        )
        if payload is None:
            return None

        return self._parse_product(self._data(payload))
