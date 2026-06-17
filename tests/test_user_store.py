"""user_store 单元测试。

使用临时文件，不依赖本机 outputs/users.json。
"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch


class TestUserStore(unittest.TestCase):
    """user_store 核心功能测试。"""

    def setUp(self):
        """每个测试使用独立的临时 JSON 文件路径。"""
        self._tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        )
        self._tmp.close()
        self.users_file = self._tmp.name
        # 删除空文件，让 ensure_user_store() 认为文件不存在并执行初始化
        os.unlink(self.users_file)

        # patch config so user_store uses our temp file
        self._patches = [
            patch("app.user_store.USERS_FILE", self.users_file),
            patch("app.user_store.ADMIN_USERNAME", "admin"),
            patch("app.user_store.ADMIN_PASSWORD", "admin123"),
            patch("app.user_store.USER_USERNAME", "user"),
            patch("app.user_store.USER_PASSWORD", "user123"),
        ]
        for p in self._patches:
            p.start()

        # re-import to pick up patched values
        from app import user_store
        self.user_store = user_store

    def tearDown(self):
        for p in self._patches:
            p.stop()
        if os.path.exists(self.users_file):
            os.unlink(self.users_file)

    # ---------- hash / verify ----------

    def test_hash_and_verify(self):
        h = self.user_store.hash_password("secret123")
        self.assertTrue(self.user_store.verify_password("secret123", h))
        self.assertFalse(self.user_store.verify_password("wrong", h))

    def test_hash_format(self):
        h = self.user_store.hash_password("test")
        parts = h.split("$")
        self.assertEqual(len(parts), 4)
        self.assertEqual(parts[0], "pbkdf2_sha256")
        self.assertTrue(parts[1].isdigit())

    def test_different_passwords_different_hashes(self):
        h1 = self.user_store.hash_password("abc")
        h2 = self.user_store.hash_password("def")
        self.assertNotEqual(h1, h2)

    def test_verify_invalid_hash_returns_false(self):
        self.assertFalse(self.user_store.verify_password("x", "not-a-valid-hash"))

    # ---------- ensure_user_store / seed ----------

    def test_seed_creates_file(self):
        self.assertFalse(os.path.exists(self.users_file))
        self.user_store.ensure_user_store()
        self.assertTrue(os.path.exists(self.users_file))

    def test_seed_creates_admin_and_user(self):
        self.user_store.ensure_user_store()
        users = self.user_store.list_users()
        usernames = {u["username"] for u in users}
        self.assertIn("admin", usernames)
        self.assertIn("user", usernames)

    def test_seed_does_not_overwrite_existing(self):
        self.user_store.ensure_user_store()
        # add a custom user
        self.user_store.create_user("custom", "pass123", "user")
        # ensure_user_store again should not overwrite
        self.user_store.ensure_user_store()
        users = self.user_store.list_users()
        usernames = {u["username"] for u in users}
        self.assertIn("custom", usernames)

    # ---------- authenticate_user ----------

    def test_authenticate_admin(self):
        self.user_store.ensure_user_store()
        result = self.user_store.authenticate_user("admin", "admin123")
        self.assertIsNotNone(result)
        self.assertEqual(result["username"], "admin")
        self.assertEqual(result["role"], "admin")

    def test_authenticate_normal_user(self):
        self.user_store.ensure_user_store()
        result = self.user_store.authenticate_user("user", "user123")
        self.assertIsNotNone(result)
        self.assertEqual(result["role"], "user")

    def test_authenticate_wrong_password(self):
        self.user_store.ensure_user_store()
        self.assertIsNone(self.user_store.authenticate_user("admin", "wrong"))

    def test_authenticate_nonexistent_user(self):
        self.user_store.ensure_user_store()
        self.assertIsNone(self.user_store.authenticate_user("nobody", "pass"))

    # ---------- create_user ----------

    def test_create_user_success(self):
        self.user_store.ensure_user_store()
        result = self.user_store.create_user("newguy", "pass123", "user")
        self.assertEqual(result["username"], "newguy")
        self.assertEqual(result["role"], "user")
        self.assertTrue(result["is_active"])

    def test_create_duplicate_user_raises(self):
        self.user_store.ensure_user_store()
        with self.assertRaises(ValueError):
            self.user_store.create_user("admin", "pass123", "admin")

    def test_create_user_short_password_raises(self):
        self.user_store.ensure_user_store()
        with self.assertRaises(ValueError):
            self.user_store.create_user("short", "12345", "user")

    def test_create_user_invalid_role_raises(self):
        self.user_store.ensure_user_store()
        with self.assertRaises(ValueError):
            self.user_store.create_user("badrole", "pass123", "superadmin")

    def test_created_user_can_authenticate(self):
        self.user_store.ensure_user_store()
        self.user_store.create_user("auth_test", "mypassword", "user")
        result = self.user_store.authenticate_user("auth_test", "mypassword")
        self.assertIsNotNone(result)
        self.assertEqual(result["username"], "auth_test")

    # ---------- list_users ----------

    def test_list_users_hides_password_hash(self):
        self.user_store.ensure_user_store()
        users = self.user_store.list_users()
        for u in users:
            self.assertNotIn("password_hash", u)

    def test_list_users_returns_expected_fields(self):
        self.user_store.ensure_user_store()
        users = self.user_store.list_users()
        for u in users:
            self.assertIn("username", u)
            self.assertIn("role", u)
            self.assertIn("is_active", u)
            self.assertIn("created_at", u)

    # ---------- find_user ----------

    def test_find_existing_user(self):
        self.user_store.ensure_user_store()
        user = self.user_store.find_user("admin")
        self.assertIsNotNone(user)
        self.assertEqual(user["username"], "admin")

    def test_find_nonexistent_user(self):
        self.user_store.ensure_user_store()
        self.assertIsNone(self.user_store.find_user("ghost"))

    # ---------- update_user_role ----------

    def test_update_user_role_success(self):
        self.user_store.ensure_user_store()
        self.user_store.create_user("promote_me", "pass123", "user")
        self.user_store.update_user_role("promote_me", "admin")
        user = self.user_store.find_user("promote_me")
        self.assertEqual(user["role"], "admin")

    def test_update_role_invalid_role_raises(self):
        self.user_store.ensure_user_store()
        with self.assertRaises(ValueError):
            self.user_store.update_user_role("admin", "superadmin")

    def test_update_role_nonexistent_user_raises(self):
        self.user_store.ensure_user_store()
        with self.assertRaises(ValueError):
            self.user_store.update_user_role("ghost", "admin")

    def test_update_role_last_admin_protection(self):
        self.user_store.ensure_user_store()
        # 只有一个 admin (admin)，不能改成 user
        with self.assertRaises(ValueError) as ctx:
            self.user_store.update_user_role("admin", "user")
        self.assertIn("last active admin", str(ctx.exception))

    # ---------- update_user_password ----------

    def test_update_password_success(self):
        self.user_store.ensure_user_store()
        self.user_store.create_user("pwuser", "oldpass1", "user")
        self.user_store.update_user_password("pwuser", "newpass1")
        result = self.user_store.authenticate_user("pwuser", "newpass1")
        self.assertIsNotNone(result)
        # 旧密码不能登录
        self.assertIsNone(self.user_store.authenticate_user("pwuser", "oldpass1"))

    def test_update_password_short_raises(self):
        self.user_store.ensure_user_store()
        with self.assertRaises(ValueError):
            self.user_store.update_user_password("admin", "12345")

    def test_update_password_nonexistent_raises(self):
        self.user_store.ensure_user_store()
        with self.assertRaises(ValueError):
            self.user_store.update_user_password("ghost", "pass123")

    # ---------- set_user_active ----------

    def test_disable_user(self):
        self.user_store.ensure_user_store()
        self.user_store.create_user("disable_me", "pass123", "user")
        self.user_store.set_user_active("disable_me", False)
        user = self.user_store.find_user("disable_me")
        self.assertFalse(user["is_active"])

    def test_disabled_user_cannot_authenticate(self):
        self.user_store.ensure_user_store()
        self.user_store.create_user("no_login", "pass123", "user")
        self.user_store.set_user_active("no_login", False)
        self.assertIsNone(self.user_store.authenticate_user("no_login", "pass123"))

    def test_enable_user(self):
        self.user_store.ensure_user_store()
        self.user_store.create_user("reenable", "pass123", "user")
        self.user_store.set_user_active("reenable", False)
        self.user_store.set_user_active("reenable", True)
        result = self.user_store.authenticate_user("reenable", "pass123")
        self.assertIsNotNone(result)

    def test_disable_last_admin_raises(self):
        self.user_store.ensure_user_store()
        with self.assertRaises(ValueError) as ctx:
            self.user_store.set_user_active("admin", False)
        self.assertIn("last active admin", str(ctx.exception))

    def test_disable_nonexistent_raises(self):
        self.user_store.ensure_user_store()
        with self.assertRaises(ValueError):
            self.user_store.set_user_active("ghost", False)

    # ---------- delete_user ----------

    def test_delete_user_success(self):
        self.user_store.ensure_user_store()
        self.user_store.create_user("doomed", "pass123", "user")
        self.user_store.delete_user("doomed")
        self.assertIsNone(self.user_store.find_user("doomed"))

    def test_deleted_user_not_in_list(self):
        self.user_store.ensure_user_store()
        self.user_store.create_user("vanish", "pass123", "user")
        self.user_store.delete_user("vanish")
        usernames = {u["username"] for u in self.user_store.list_users()}
        self.assertNotIn("vanish", usernames)

    def test_delete_last_admin_raises(self):
        self.user_store.ensure_user_store()
        with self.assertRaises(ValueError) as ctx:
            self.user_store.delete_user("admin")
        self.assertIn("last active admin", str(ctx.exception))

    def test_delete_nonexistent_raises(self):
        self.user_store.ensure_user_store()
        with self.assertRaises(ValueError):
            self.user_store.delete_user("ghost")

    def test_delete_admin_when_multiple_admins(self):
        """有多个 active admin 时可以删除其中一个。"""
        self.user_store.ensure_user_store()
        self.user_store.create_user("admin2", "pass123", "admin")
        self.user_store.delete_user("admin2")
        self.assertIsNone(self.user_store.find_user("admin2"))
        # 原 admin 仍在
        self.assertIsNotNone(self.user_store.find_user("admin"))


if __name__ == "__main__":
    unittest.main()
