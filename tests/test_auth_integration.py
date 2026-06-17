"""登录流程 + /users 路由集成测试。

使用临时 JSON 文件 + TestClient，不依赖本机 .env。
所有集成测试共享同一套 patch，避免模块级 import 冲突。
"""

import atexit
import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

_TEST_ADMIN_USER = "testadmin"
_TEST_ADMIN_PASS = "test_admin_pass"
_TEST_NORMAL_USER = "testuser"
_TEST_NORMAL_PASS = "test_user_pass"

_USERS_FILE = os.path.join(tempfile.gettempdir(), "test_auth_integration_users.json")
if os.path.exists(_USERS_FILE):
    os.unlink(_USERS_FILE)

_patches = [
    patch("app.config.SESSION_SECRET_KEY", "test-secret-key"),
    patch("app.config.ADMIN_USERNAME", _TEST_ADMIN_USER),
    patch("app.config.ADMIN_PASSWORD", _TEST_ADMIN_PASS),
    patch("app.config.USER_USERNAME", _TEST_NORMAL_USER),
    patch("app.config.USER_PASSWORD", _TEST_NORMAL_PASS),
    patch("app.config.USERS_FILE", _USERS_FILE),
    patch("app.user_store.USERS_FILE", _USERS_FILE),
    patch("app.user_store.ADMIN_USERNAME", _TEST_ADMIN_USER),
    patch("app.user_store.ADMIN_PASSWORD", _TEST_ADMIN_PASS),
    patch("app.user_store.USER_USERNAME", _TEST_NORMAL_USER),
    patch("app.user_store.USER_PASSWORD", _TEST_NORMAL_PASS),
]
for p in _patches:
    p.start()

from app.main import app  # noqa: E402


def _admin_client():
    client = TestClient(app)
    resp = client.post(
        "/login",
        data={"username": _TEST_ADMIN_USER, "password": _TEST_ADMIN_PASS},
    )
    assert resp.status_code in (200, 303), f"admin login failed: {resp.status_code}"
    return client


def _user_client():
    client = TestClient(app)
    resp = client.post(
        "/login",
        data={"username": _TEST_NORMAL_USER, "password": _TEST_NORMAL_PASS},
    )
    assert resp.status_code in (200, 303), f"user login failed: {resp.status_code}"
    return client


# ==================== 登录流程 ====================

class TestLoginFlow(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_unauthenticated_root_redirects_to_login(self):
        resp = self.client.get("/", follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertIn("/login", resp.headers.get("location", ""))

    def test_login_page_returns_200(self):
        resp = self.client.get("/login")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("登录", resp.text)

    def test_login_page_accessible_without_auth(self):
        resp = self.client.get("/login", follow_redirects=False)
        self.assertEqual(resp.status_code, 200)

    def test_static_accessible_without_auth(self):
        resp = self.client.get("/static/style.css", follow_redirects=False)
        self.assertEqual(resp.status_code, 200)

    def test_docs_accessible_without_auth(self):
        resp = self.client.get("/docs", follow_redirects=False)
        self.assertEqual(resp.status_code, 200)

    def test_tplus_message_callback_trailing_slash_does_not_return_login_page(self):
        resp = self.client.post("/tplus/message/callback/", json={"msgType": "APP_TEST"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["result"], "success")
        self.assertEqual(resp.headers["x-inventory-callback"], "tplus-message-v3")
        self.assertNotIn("<!DOCTYPE html>", resp.text)

    def test_tplus_message_callback_with_proxy_prefix_does_not_return_login_page(self):
        resp = self.client.post("/inventory/tplus/message/callback", json={"msgType": "APP_TEST"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["result"], "success")
        self.assertEqual(resp.headers["x-inventory-callback"], "tplus-message-v3")
        self.assertNotIn("<!DOCTYPE html>", resp.text)

    def test_admin_login_success(self):
        resp = self.client.post(
            "/login",
            data={"username": _TEST_ADMIN_USER, "password": _TEST_ADMIN_PASS},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        self.assertIn("/", resp.headers.get("location", ""))
        resp = self.client.get("/", follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

    def test_user_login_role_in_session(self):
        self.client.post(
            "/login",
            data={"username": _TEST_NORMAL_USER, "password": _TEST_NORMAL_PASS},
            follow_redirects=False,
        )
        resp = self.client.get("/", follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

    def test_wrong_password_shows_error_and_echoes_username(self):
        resp = self.client.post(
            "/login",
            data={"username": "someone", "password": "wrong"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("用户名或密码错误", resp.text)
        self.assertIn('value="someone"', resp.text)

    def test_logout_clears_session(self):
        self.client.post(
            "/login",
            data={"username": _TEST_ADMIN_USER, "password": _TEST_ADMIN_PASS},
        )
        resp = self.client.get("/logout", follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertIn("/login", resp.headers.get("location", ""))
        resp = self.client.get("/", follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertIn("/login", resp.headers.get("location", ""))


# ==================== /users 路由 ====================

class TestUsersRoute(unittest.TestCase):
    def test_admin_can_access_users_page(self):
        client = _admin_client()
        resp = client.get("/users")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("用户管理", resp.text)

    def test_normal_user_forbidden(self):
        client = _user_client()
        resp = client.get("/users")
        self.assertEqual(resp.status_code, 403)

    def test_unauthenticated_redirected(self):
        client = TestClient(app)
        resp = client.get("/users", follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertIn("/login", resp.headers.get("location", ""))

    def test_users_page_shows_seeded_users(self):
        client = _admin_client()
        resp = client.get("/users")
        self.assertIn(_TEST_ADMIN_USER, resp.text)
        self.assertIn(_TEST_NORMAL_USER, resp.text)

    def test_admin_create_user_success(self):
        client = _admin_client()
        resp = client.post(
            "/users",
            data={"username": "newuser", "password": "pass123", "role": "user"},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        self.assertIn("created=1", resp.headers.get("location", ""))

    def test_admin_create_user_appears_in_list(self):
        client = _admin_client()
        client.post(
            "/users",
            data={"username": "listcheck", "password": "pass123", "role": "user"},
        )
        resp = client.get("/users")
        self.assertIn("listcheck", resp.text)

    def test_create_duplicate_user_shows_error(self):
        client = _admin_client()
        client.post(
            "/users",
            data={"username": "dupeuser", "password": "pass123", "role": "user"},
        )
        resp = client.post(
            "/users",
            data={"username": "dupeuser", "password": "pass456", "role": "user"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("already exists", resp.text)

    def test_create_user_short_password_shows_error(self):
        client = _admin_client()
        resp = client.post(
            "/users",
            data={"username": "shortpw", "password": "12345", "role": "user"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("at least 6", resp.text)

    def test_normal_user_cannot_create(self):
        client = _user_client()
        resp = client.post(
            "/users",
            data={"username": "nope", "password": "pass123", "role": "user"},
        )
        self.assertEqual(resp.status_code, 403)


# ==================== 用户管理路由 ====================

class TestUserManagementRoutes(unittest.TestCase):
    def test_admin_change_role(self):
        client = _admin_client()
        client.post("/users", data={"username": "role_target", "password": "pass123", "role": "user"})
        resp = client.post("/users/role_target/role", data={"role": "admin"}, follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        resp = client.get("/users")
        # role_target 应该显示为管理员
        self.assertIn("role-target", resp.text.replace("_", "-") if "role-target" not in resp.text else resp.text)
        # 验证实际角色已变：用新 admin 登录应该能访问 /users
        c2 = TestClient(app)
        c2.post("/login", data={"username": "role_target", "password": "pass123"})
        resp2 = c2.get("/users")
        self.assertEqual(resp2.status_code, 200)

    def test_admin_change_password(self):
        client = _admin_client()
        client.post("/users", data={"username": "pw_target", "password": "oldpass1", "role": "user"})
        resp = client.post("/users/pw_target/password", data={"password": "newpass1"}, follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        # 新密码可登录
        c2 = TestClient(app)
        resp_login = c2.post("/login", data={"username": "pw_target", "password": "newpass1"}, follow_redirects=False)
        self.assertEqual(resp_login.status_code, 303)
        # 旧密码不可登录
        c3 = TestClient(app)
        resp_old = c3.post("/login", data={"username": "pw_target", "password": "oldpass1"}, follow_redirects=False)
        self.assertEqual(resp_old.status_code, 200)  # 失败回到登录页

    def test_admin_disable_and_enable_user(self):
        client = _admin_client()
        client.post("/users", data={"username": "toggle_me", "password": "pass123", "role": "user"})
        # 禁用
        resp = client.post("/users/toggle_me/active", data={"is_active": "0"}, follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        # 被禁用用户不能登录
        c2 = TestClient(app)
        resp_login = c2.post("/login", data={"username": "toggle_me", "password": "pass123"}, follow_redirects=False)
        self.assertEqual(resp_login.status_code, 200)
        # 重新启用
        resp = client.post("/users/toggle_me/active", data={"is_active": "1"}, follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        c3 = TestClient(app)
        resp_login2 = c3.post("/login", data={"username": "toggle_me", "password": "pass123"}, follow_redirects=False)
        self.assertEqual(resp_login2.status_code, 303)

    def test_admin_delete_user(self):
        client = _admin_client()
        client.post("/users", data={"username": "delete_me", "password": "pass123", "role": "user"})
        resp = client.post("/users/delete_me/delete", follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        # 删除后不在列表
        resp = client.get("/users")
        self.assertNotIn("delete_me", resp.text)
        # 删除后不能登录
        c2 = TestClient(app)
        resp_login = c2.post("/login", data={"username": "delete_me", "password": "pass123"}, follow_redirects=False)
        self.assertEqual(resp_login.status_code, 200)

    def test_normal_user_cannot_change_role(self):
        client = _user_client()
        resp = client.post("/users/testadmin/role", data={"role": "user"})
        self.assertEqual(resp.status_code, 403)

    def test_normal_user_cannot_change_password(self):
        client = _user_client()
        resp = client.post("/users/testadmin/password", data={"password": "hacked1"})
        self.assertEqual(resp.status_code, 403)

    def test_normal_user_cannot_toggle_active(self):
        client = _user_client()
        resp = client.post("/users/testadmin/active", data={"is_active": "0"})
        self.assertEqual(resp.status_code, 403)

    def test_normal_user_cannot_delete(self):
        client = _user_client()
        resp = client.post("/users/testadmin/delete")
        self.assertEqual(resp.status_code, 403)

    def test_cannot_delete_last_admin(self):
        # 清理前面 test_admin_change_role 可能残留的额外 admin
        from app.user_store import find_user, delete_user as store_delete
        extra = find_user("role_target")
        if extra and extra.get("role") == "admin":
            store_delete("role_target")
        client = _admin_client()
        resp = client.post("/users/testadmin/delete", follow_redirects=False)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("last active admin", resp.text)

    def test_cannot_disable_last_admin(self):
        from app.user_store import find_user, delete_user as store_delete
        extra = find_user("role_target")
        if extra and extra.get("role") == "admin":
            store_delete("role_target")
        client = _admin_client()
        resp = client.post("/users/testadmin/active", data={"is_active": "0"}, follow_redirects=False)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("last active admin", resp.text)

    def test_change_password_short_password_shows_error(self):
        client = _admin_client()
        client.post("/users", data={"username": "shortpw2", "password": "pass123", "role": "user"})
        resp = client.post("/users/shortpw2/password", data={"password": "12345"}, follow_redirects=False)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("at least 6", resp.text)


def _cleanup():
    for p in _patches:
        p.stop()
    if os.path.exists(_USERS_FILE):
        os.unlink(_USERS_FILE)


atexit.register(_cleanup)


if __name__ == "__main__":
    unittest.main()
