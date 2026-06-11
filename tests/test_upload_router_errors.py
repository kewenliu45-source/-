import unittest

from app.routers.upload_router import get_user_facing_error


class UploadRouterErrorTests(unittest.TestCase):
    def test_explains_chanjet_internal_connection_failure(self):
        message = get_user_facing_error(RuntimeError("4028: EXERROR0002 Connection refused"))

        self.assertIn("畅捷通已收到认证请求", message)
        self.assertIn("EXERROR0002", message)

    def test_explains_chanjet_read_timeout(self):
        message = get_user_facing_error(
            RuntimeError(
                "调用畅捷通 T+ OpenAPI 失败：HTTPSConnectionPool(host='openapi.chanjet.com', "
                "port=443): Read timed out. (read timeout=20)"
            )
        )

        self.assertIn("调用畅捷通 T+ OpenAPI 超时", message)
        self.assertIn("TPLUS_REQUEST_TIMEOUT", message)
        self.assertIn("TPLUS_QUERY_PAGE_SIZE", message)


if __name__ == "__main__":
    unittest.main()
