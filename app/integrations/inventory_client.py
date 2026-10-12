"""HTTP client for the Inventory Management System API."""

from typing import Any

import httpx


class InventoryAPIError(Exception):
    """Raised when the inventory API request fails."""


class InventoryClient:
    """Read product catalogue and stock from the inventory API."""

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        timeout: float = 15.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.headers: dict[str, str] = {}

        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    def _get(
        self,
        path: str,
        *,
        allow_not_found: bool = False,
    ) -> Any:
        """Send a GET request and return its JSON response."""
        url = f"{self.base_url}/{path.lstrip('/')}"

        try:
            response = httpx.get(
                url,
                headers=self.headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()

        except httpx.HTTPStatusError as exc:
            if allow_not_found and exc.response.status_code == 404:
                return None

            raise InventoryAPIError(
                f"Inventory API request failed: {exc}"
            ) from exc

        except httpx.HTTPError as exc:
            raise InventoryAPIError(
                f"Inventory API request failed: {exc}"
            ) from exc

        except ValueError as exc:
            raise InventoryAPIError(
                "Inventory API returned invalid JSON."
            ) from exc

    def list_products(self) -> list[dict[str, Any]]:
        """Return products from the inventory catalogue."""
        payload = self._get("products")

        if isinstance(payload, dict):
            payload = payload.get("data", payload)

        if not isinstance(payload, list):
            raise InventoryAPIError(
                "Unexpected product catalogue response format."
            )

        return [
            product
            for product in payload
            if isinstance(product, dict)
        ]

    def get_product(self, product_id: str) -> dict[str, Any] | None:
        """Return one product, or None if it does not exist."""
        payload = self._get(
            f"products/{product_id}",
            allow_not_found=True,
        )

        if payload is None:
            return None

        if isinstance(payload, dict):
            product = payload.get("data", payload)
            if isinstance(product, dict):
                return product

        return None
