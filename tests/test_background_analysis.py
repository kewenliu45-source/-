import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.routers import upload_router


class BackgroundDatabaseAnalysisTests(unittest.TestCase):
    def setUp(self):
        upload_router._analysis_tasks.clear()
        self.user = {"username": "background-test-user", "role": "user"}

    def test_database_analysis_returns_before_work_is_executed(self):
        submitted = []

        def capture_submit(function, *args):
            submitted.append((function, args))

        with (
            patch("app.main.get_current_user", return_value=self.user),
            patch("app.routers.upload_router.get_current_user", return_value=self.user),
            patch.object(upload_router._analysis_executor, "submit", side_effect=capture_submit),
            patch.object(upload_router, "build_standard_data_from_database") as build_data,
        ):
            client = TestClient(app)
            response = client.post("/database-analysis")

        self.assertEqual(response.status_code, 202)
        self.assertIn("正在分析库存数据", response.text)
        self.assertEqual(len(submitted), 1)
        build_data.assert_not_called()

        task_id = submitted[0][1][0]
        self.assertEqual(upload_router._analysis_tasks[task_id]["status"], "queued")

    def test_task_status_is_isolated_by_user(self):
        task_id = upload_router._create_analysis_task("alice")

        self.assertIsNotNone(upload_router._get_analysis_task(task_id, "alice"))
        self.assertIsNone(upload_router._get_analysis_task(task_id, "bob"))

    def test_worker_records_failure_for_polling_page(self):
        task_id = upload_router._create_analysis_task("alice")

        with patch.object(
            upload_router,
            "build_standard_data_from_database",
            side_effect=RuntimeError("background failure"),
        ):
            upload_router._run_database_analysis_task(task_id, None, None)

        task = upload_router._get_analysis_task(task_id, "alice")
        self.assertEqual(task["status"], "failed")
        self.assertIn("background failure", task["message"])

    def test_chunked_upload_starts_analysis_without_large_multipart_request(self):
        submitted = []

        def capture_submit(function, *args):
            submitted.append((function, args))

        with (
            patch("app.main.get_current_user", return_value=self.user),
            patch("app.routers.upload_router.get_current_user", return_value=self.user),
            patch.object(upload_router._analysis_executor, "submit", side_effect=capture_submit),
        ):
            client = TestClient(app)
            init_response = client.post(
                "/analysis-uploads/init",
                json={
                    "files": {
                        "hq_file": {"name": "hq.xlsx", "size": 6},
                    }
                },
            )
            self.assertEqual(init_response.status_code, 200)
            upload_id = init_response.json()["upload_id"]

            first_chunk = client.post(
                f"/analysis-uploads/{upload_id}/hq_file/chunks/0",
                content=b"abc",
                headers={"Content-Type": "application/octet-stream"},
            )
            second_chunk = client.post(
                f"/analysis-uploads/{upload_id}/hq_file/chunks/1",
                content=b"def",
                headers={"Content-Type": "application/octet-stream"},
            )
            self.assertFalse(first_chunk.json()["complete"])
            self.assertTrue(second_chunk.json()["complete"])

            start_response = client.post(
                "/database-analysis/start",
                json={"upload_id": upload_id},
            )

        self.assertEqual(start_response.status_code, 202)
        self.assertIn("/analysis-tasks/", start_response.json()["task_url"])
        self.assertEqual(len(submitted), 1)
        self.assertEqual(submitted[0][1][1], b"abcdef")


if __name__ == "__main__":
    unittest.main()
