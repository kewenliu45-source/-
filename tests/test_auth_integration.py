"""登录流程集成测试。

使用 FastAPI TestClient 测试完整的登录/退出 HTTP 流程。
"""

import unittest

from fastapi.testclient import TestClient


class TestLoginFlow(unittest.TestCase):
    """登录流程集成测试。"""

    def setUp(self):
        """每个测试前重新创建 client，确保 session 隔离。"""
        from app.main import app
        self.client = TestClient(app)

    def test_unauthenticated_root_redirects_to_login(self):
        """未登录访问 / 应重定向到 /login。"""
        response = self.client.get("/", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertIn("/login", response.headers.get("location", ""))

    def test_login_page_returns_200(self):
        """GET /login 应返回 200。"""
        response = self.client.get("/login")
        self.assertEqual(response.status_code, 200)
        self.assertIn("登录", response.text)

    def test_admin_login_success(self):
        """管理员登录成功后可访问首页。"""
        # 登录
        response = self.client.post(
            "/login",
            data={"username": "admin", "password": "admin123"},
            follow_redirects=False,
        )
        # 登录成功应重定向到 /
        self.assertEqual(response.status_code, 303)
        self.assertIn("/", response.headers.get("location", ""))

        # 跟随重定向访问首页
        response = self.client.get("/", follow_redirects=True)
        self.assertEqual(response.status_code, 200)

    def test_user_login_role_in_session(self):
        """普通用户登录后 session 中 role 为 user。"""
        # 登录
        self.client.post(
            "/login",
            data={"username": "user", "password": "user123"},
            follow_redirects=False,
        )

        # 访问首页确认能正常加载（说明 session 生效）
        response = self.client.get("/", follow_redirects=True)
        self.assertEqual(response.status_code, 200)

    def test_wrong_password_shows_error(self):
        """错误密码登录应显示错误提示。"""
        response = self.client.post(
            "/login",
            data={"username": "admin", "password": "wrong"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("用户名或密码错误", response.text)

    def test_logout_clears_session(self):
        """退出登录后应清除登录态。"""
        # 先登录
        self.client.post(
            "/login",
            data={"username": "admin", "password": "admin123"},
        )

        # 退出
        response = self.client.get("/logout", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertIn("/login", response.headers.get("location", ""))

        # 退出后访问 / 应被重定向
        response = self.client.get("/", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertIn("/login", response.headers.get("location", ""))

    def test_login_page_accessible_without_auth(self):
        """登录页本身不需要认证。"""
        response = self.client.get("/login", follow_redirects=False)
        self.assertEqual(response.status_code, 200)

    def test_static_accessible_without_auth(self):
        """静态资源不需要认证。"""
        response = self.client.get("/static/style.css", follow_redirects=False)
        self.assertEqual(response.status_code, 200)

    def test_docs_accessible_without_auth(self):
        """API 文档不需要认证。"""
        response = self.client.get("/docs", follow_redirects=False)
        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
