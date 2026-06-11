import unittest

from app.data_sources.tplus_openapi_source import _extract_app_ticket
from app.routers.tplus_oauth_router import decrypt_chanjet_message


class ChanjetMessageCryptoTests(unittest.TestCase):
    def test_decrypts_app_test_message(self):
        encrypted_message = (
            "QgXzRv/keY3KzDp/MD0UV7IOKFl/B2hbf9wKsQ2DkCXXEN5yc87PPy3j2AQ8e27h5hzLh/"
            "mOSd/Dj+8E3CLk53VfycbQEJ0Q7D+VdPcMUjndbGrKlL08Dwh21z3cPZCFLopF1DqHzducQ"
            "dHVMc8XeI2C2Dgl6tq2tsEGWPV628GANhBSnkVWZ5+bsa3JndlDg3LigYTF20COZH4vqrU3"
            "JBUZQ0qf4Z2bK0JjQGrNioo="
        )

        payload = decrypt_chanjet_message(encrypted_message, "1234567812345678")

        self.assertEqual(payload["msgType"], "APP_TEST")
        self.assertEqual(payload["bizContent"]["message"], "畅捷通开放平台消息测试")

    def test_extracts_nested_app_ticket(self):
        payload = {"msgType": "APP_TICKET", "bizContent": {"appTicket": "t-example"}}

        self.assertEqual(_extract_app_ticket(payload), "t-example")


if __name__ == "__main__":
    unittest.main()
