import os
from unittest import TestCase
from unittest.mock import Mock, patch

import httpx

from app.config import Settings
from app.integrations.inventory_client import InventoryAPIError, InventoryClient
from app.tools.product_tools import build_product_tools


class InventoryClientTests(TestCase):
    def setUp(self):
        self.client = InventoryClient(
            "http://localhost:5000/",
            "test-service-token",
        )

    @staticmethod
    def response(payload):
        response = Mock()
        response.json.return_value = payload
        response.raise_for_status.return_value = None
        return response

    def test_lists_products_with_authenticated_request_and_only_public_fields(self):
        product = {
            "id": "prod_001",
            "name": "Keyboard",
            "price": 25.5,
            "quantity": 8,
            "costPrice": 11.0,
            "supplier": "Private supplier",
            "sales": [{"quantity": 10}],
        }
        response = self.response({"success": True, "data": [product]})

        with patch("app.integrations.inventory_client.httpx.get", return_value=response) as get:
            products = self.client.list_products()

        self.assertEqual(
            products,
            [{"id": "prod_001", "name": "Keyboard", "price": 25.5, "quantity": 8}],
        )
        get.assert_called_once_with(
            "http://localhost:5000/api/products",
            headers={
                "X-Inventory-Service-Request": "true",
                "Authorization": "Bearer test-service-token",
            },
            timeout=15.0,
        )

    def test_lists_low_stock_products_from_supported_route(self):
        response = self.response(
            {
                "success": True,
                "data": [
                    {"id": "prod_002", "name": "Mouse", "price": 10, "quantity": 2}
                ],
            }
        )

        with patch("app.integrations.inventory_client.httpx.get", return_value=response) as get:
            products = self.client.list_low_stock_products()

        self.assertEqual(products[0]["quantity"], 2)
        self.assertEqual(
            get.call_args.args[0],
            "http://localhost:5000/api/products/low-stock",
        )
        self.assertEqual(
            get.call_args.kwargs["headers"]["X-Inventory-Service-Request"],
            "true",
        )
        self.assertEqual(
            get.call_args.kwargs["headers"]["Authorization"],
            "Bearer test-service-token",
        )

    def test_get_product_encodes_id_and_strips_detail_fields(self):
        response = self.response(
            {
                "success": True,
                "data": {
                    "id": "prod/003",
                    "name": "Cable",
                    "price": 3,
                    "quantity": 4,
                    "lowStockThreshold": 10,
                    "sales": [],
                },
            }
        )

        with patch("app.integrations.inventory_client.httpx.get", return_value=response) as get:
            product = self.client.get_product("prod/003")

        self.assertEqual(
            product,
            {"id": "prod/003", "name": "Cable", "price": 3, "quantity": 4},
        )
        self.assertEqual(
            get.call_args.args[0],
            "http://localhost:5000/api/products/prod%2F003",
        )
        self.assertEqual(
            get.call_args.kwargs["headers"],
            {
                "X-Inventory-Service-Request": "true",
                "Authorization": "Bearer test-service-token",
            },
        )

    def test_missing_product_returns_none_on_404(self):
        response = Mock()
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "not found",
            request=httpx.Request("GET", "http://localhost:5000/api/products/missing"),
            response=httpx.Response(404),
        )

        with patch("app.integrations.inventory_client.httpx.get", return_value=response):
            self.assertIsNone(self.client.get_product("missing"))

    def test_missing_configuration_fails_without_request(self):
        client = InventoryClient(None, None)

        with patch("app.integrations.inventory_client.httpx.get") as get:
            with self.assertRaisesRegex(InventoryAPIError, "not configured"):
                client.list_products()

        get.assert_not_called()

    def test_timeout_message_does_not_expose_credentials(self):
        with patch(
            "app.integrations.inventory_client.httpx.get",
            side_effect=httpx.ReadTimeout("test-service-token"),
        ):
            with self.assertRaises(InventoryAPIError) as error:
                self.client.list_products()

        self.assertEqual(str(error.exception), "Inventory API request timed out.")
        self.assertNotIn("test-service-token", str(error.exception))

    def test_http_error_message_does_not_expose_credentials(self):
        response = Mock()
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "failure",
            request=httpx.Request("GET", "http://localhost:5000/api/products"),
            response=httpx.Response(500),
        )

        with patch("app.integrations.inventory_client.httpx.get", return_value=response):
            with self.assertRaises(InventoryAPIError) as error:
                self.client.list_products()

        self.assertEqual(str(error.exception), "Inventory API request failed.")
        self.assertNotIn("test-service-token", str(error.exception))

    def test_unauthorized_response_does_not_expose_response_details(self):
        sensitive_body = "Unauthorized: internal auth detail and service token"
        response = Mock()
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            sensitive_body,
            request=httpx.Request("GET", "http://localhost:5000/api/products"),
            response=httpx.Response(
                401,
                text=sensitive_body,
                request=httpx.Request("GET", "http://localhost:5000/api/products"),
            ),
        )

        with patch("app.integrations.inventory_client.httpx.get", return_value=response):
            with self.assertRaises(InventoryAPIError) as error:
                self.client.list_products()

        self.assertEqual(str(error.exception), "Inventory API request failed.")
        self.assertNotIn(sensitive_body, str(error.exception))
        self.assertNotIn("service token", str(error.exception))

    def test_malformed_envelope_and_product_are_rejected(self):
        with patch(
            "app.integrations.inventory_client.httpx.get",
            return_value=self.response({"success": True, "data": {"unexpected": []}}),
        ):
            with self.assertRaisesRegex(InventoryAPIError, "invalid product list"):
                self.client.list_products()

        with patch(
            "app.integrations.inventory_client.httpx.get",
            return_value=self.response(
                {
                    "success": True,
                    "data": [
                        {
                            "id": "prod_001",
                            "name": "Keyboard",
                            "price": 25,
                            "quantity": "unknown",
                        }
                    ],
                }
            ),
        ):
            with self.assertRaisesRegex(InventoryAPIError, "invalid product"):
                self.client.list_products()

    def test_invalid_json_is_rejected(self):
        response = self.response(None)
        response.json.side_effect = ValueError("invalid JSON")

        with patch("app.integrations.inventory_client.httpx.get", return_value=response):
            with self.assertRaisesRegex(InventoryAPIError, "invalid JSON"):
                self.client.list_products()

    def test_listing_tools_use_supported_inventory_lookups(self):
        product = {"id": "prod_001", "name": "Keyboard", "price": 25, "quantity": 8}
        self.client.list_products = Mock(return_value=[product])
        self.client.list_low_stock_products = Mock(return_value=[product])

        tools = {
            tool.name: tool
            for tool in build_product_tools(Mock(), "USD", self.client)
        }

        self.assertEqual(
            tools["list_products"].invoke({}),
            {"count": 1, "products": [product]},
        )
        self.assertEqual(
            tools["low_stock_products"].invoke({}),
            {"count": 1, "products": [product]},
        )

    def test_search_tool_uses_only_supported_fields_and_rejects_category_filter(self):
        product = {"id": "prod_001", "name": "Keyboard", "price": 25, "quantity": 8}
        self.client.list_products = Mock(return_value=[product])
        tools = {
            tool.name: tool
            for tool in build_product_tools(Mock(), "USD", self.client)
        }

        self.assertEqual(
            tools["search_products"].invoke({"query": "keyboard"}),
            {"count": 1, "products": [product]},
        )
        self.assertEqual(
            tools["search_products"].invoke(
                {"query": "keyboard", "category": "electronics"}
            ),
            {"error": "Category filtering is not supported by the Inventory API."},
        )
        self.client.list_products.assert_called_once()


class InventorySettingsTests(TestCase):
    def test_inventory_base_url_defaults_to_api_root_without_api_path(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings(_env_file=None)

        self.assertEqual(
            settings.inventory_api_base_url,
            "http://localhost:5000",
        )

    def test_new_environment_names_are_loaded_without_dotenv(self):
        with patch.dict(
            os.environ,
            {
                "INVENTORY_API_BASE_URL": "http://localhost:5000",
                "INVENTORY_SERVICE_TOKEN": "test-service-token",
            },
            clear=True,
        ):
            settings = Settings(_env_file=None)

        self.assertEqual(
            settings.inventory_api_base_url,
            "http://localhost:5000",
        )
        self.assertEqual(
            settings.inventory_service_token.get_secret_value(),
            "test-service-token",
        )

    def test_legacy_environment_names_remain_supported(self):
        with patch.dict(
            os.environ,
            {
                "INVENTORY_API_URL": "http://localhost:5000",
                "INVENTORY_API_TOKEN": "legacy-test-token",
            },
            clear=True,
        ):
            settings = Settings(_env_file=None)

        self.assertEqual(
            settings.inventory_api_base_url,
            "http://localhost:5000",
        )
        self.assertEqual(
            settings.inventory_service_token.get_secret_value(),
            "legacy-test-token",
        )
