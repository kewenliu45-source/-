"""认证模块单元测试。"""

import unittest
from unittest.mock import patch, MagicMock

from app.auth import (
    is_public_path,
    verify_login,
    get_current_user,
    is_admin,
    ROLE_ADMIN,
    ROLE_USER,
)


class TestRoles(unittest.TestCase):
    def test_role_admin_value(self):
        self.assertEqual(ROLE_ADMIN, "admin")

    def test_role_user_value(self):
        self.assertEqual(ROLE_USER, "user")


class TestIsPublicPath(unittest.TestCase):
    def test_login_path(self):
        self.assertTrue(is_public_path("/login"))

    def test_logout_path(self):
        self.assertTrue(is_public_path("/logout"))

    def test_static_prefix(self):
        self.assertTrue(is_public_path("/static/style.css"))

    def test_chanjet_check(self):
        self.assertTrue(is_public_path("/CHANJET_CHECK.txt"))

    def test_tplus_message_callback(self):
        self.assertTrue(is_public_path("/tplus/message/callback"))

    def test_tplus_message_callback_trailing_slash(self):
        self.assertTrue(is_public_path("/tplus/message/callback/"))

    def test_tplus_message_callback_with_proxy_prefix(self):
        self.assertTrue(is_public_path("/inventory/tplus/message/callback"))

    def test_tplus_message_callback_with_extra_suffix_for_diagnostics(self):
        self.assertTrue(is_public_path("/inventory/tplus/message/callback/check"))

    def test_tplus_oauth_callback(self):
        self.assertTrue(is_public_path("/tplus/oauth/callback"))

    def test_docs(self):
        self.assertTrue(is_public_path("/docs"))

    def test_openapi_json(self):
        self.assertTrue(is_public_path("/openapi.json"))

    def test_redoc(self):
        self.assertTrue(is_public_path("/redoc"))

    def test_root_not_public(self):
        self.assertFalse(is_public_path("/"))

    def test_upload_not_public(self):
        self.assertFalse(is_public_path("/upload"))


class TestVerifyLogin(unittest.TestCase):
    """verify_login 现在委托给 user_store.authenticate_user。"""

    @patch("app.auth.authenticate_user")
    def test_success_returns_user(self, mock_auth):
        mock_auth.return_value = {"username": "admin", "role": "admin"}
        result = verify_login("admin", "admin123")
        self.assertIsNotNone(result)
        self.assertEqual(result["role"], "admin")
        mock_auth.assert_called_once_with("admin", "admin123")

    @patch("app.auth.authenticate_user")
    def test_failure_returns_none(self, mock_auth):
        mock_auth.return_value = None
        result = verify_login("admin", "wrong")
        self.assertIsNone(result)


class TestGetCurrentUser(unittest.TestCase):
    def test_user_in_session(self):
        mock_request = MagicMock()
        mock_request.session = {"user": {"username": "admin", "role": "admin"}}
        user = get_current_user(mock_request)
        self.assertEqual(user["username"], "admin")

    def test_no_user_in_session(self):
        mock_request = MagicMock()
        mock_request.session = {}
        self.assertIsNone(get_current_user(mock_request))


class TestIsAdmin(unittest.TestCase):
    def test_admin_user(self):
        mock_request = MagicMock()
        mock_request.session = {"user": {"username": "admin", "role": "admin"}}
        self.assertTrue(is_admin(mock_request))

    def test_normal_user(self):
        mock_request = MagicMock()
        mock_request.session = {"user": {"username": "user", "role": "user"}}
        self.assertFalse(is_admin(mock_request))

    def test_no_user(self):
        mock_request = MagicMock()
        mock_request.session = {}
        self.assertFalse(is_admin(mock_request))


if __name__ == "__main__":
    unittest.main()
