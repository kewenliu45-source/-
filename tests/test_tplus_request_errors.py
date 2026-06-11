import unittest

import requests

from app.data_sources.tplus_openapi_source import _format_tplus_request_error


class TPlusRequestErrorTests(unittest.TestCase):
    def test_timeout_error_suggests_timeout_and_page_size(self):
        error = requests.exceptions.ReadTimeout(
            "HTTPSConnectionPool(host='openapi.chanjet.com', port=443): Read timed out. (read timeout=20)"
        )

        message = _format_tplus_request_error(error, "/tplus/api/v2/currentStock/Query")

        self.assertIn("接口在", message)
        self.assertIn("TPLUS_REQUEST_TIMEOUT", message)
        self.assertIn("TPLUS_QUERY_PAGE_SIZE", message)
        self.assertNotIn("EXSV0011", message)

    def test_exsv0011_error_suggests_endpoint_configuration(self):
        message = _format_tplus_request_error(
            RuntimeError("EXSV0011: service name not found"),
            "/tplus/api/v2/currentStock/Query",
        )

        self.assertIn("EXSV0011", message)
        self.assertIn("TPLUS_CURRENT_STOCK_QUERY_ENDPOINT", message)


if __name__ == "__main__":
    unittest.main()
