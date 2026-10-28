import os
import unittest

os.environ["APP_SECRET_KEY"] = "test-app-secret-key-not-for-production-000000"
os.environ["DATABASE_BACKEND"] = "sqlite"
os.environ["SQLITE_FILE_NAME"] = ":memory:"

from fastapi.testclient import TestClient
from sqlalchemy import inspect
from sqlalchemy.pool import StaticPool
from sqlmodel import create_engine

from main import AppSettings, create_app
from tests.migration_support import upgrade_test_database


class AppFactoryTests(unittest.TestCase):
    def test_app_factory_uses_isolated_database_and_cors_settings(self):
        first_engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        second_engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.addCleanup(first_engine.dispose)
        self.addCleanup(second_engine.dispose)
        upgrade_test_database(first_engine)
        first_app = create_app(
            database_engine=first_engine,
            settings=AppSettings(cors_allowed_origins=("https://first.example",)),
        )
        second_app = create_app(
            database_engine=second_engine,
            initialize_database=False,
            settings=AppSettings(cors_allowed_origins=("https://second.example",)),
        )

        self.assertIsNot(first_app, second_app)
        self.assertNotEqual(
            first_app.dependency_overrides, second_app.dependency_overrides
        )
        with TestClient(first_app) as client:
            asset_links = client.get("/.well-known/assetlinks.json")
            self.assertEqual(asset_links.status_code, 200)
            self.assertTrue(
                asset_links.headers["content-type"].startswith("application/json")
            )
            self.assertEqual(
                asset_links.json(),
                [
                    {
                        "relation": ["delegate_permission/common.handle_all_urls"],
                        "target": {
                            "namespace": "android_app",
                            "package_name": "com.aurorah.can",
                            "sha256_cert_fingerprints": [
                                "F5:16:90:CF:4C:C1:15:0D:57:9A:8E:94:99:89:04:70:38:FC:5F:F8:55:34:4E:D5:6C:4D:E8:1F:D7:24:1E:A7"
                            ],
                        },
                    }
                ],
            )
            response = client.options(
                "/api/news",
                headers={
                    "Origin": "https://first.example",
                    "Access-Control-Request-Method": "GET",
                },
            )
            self.assertEqual(
                response.headers["access-control-allow-origin"],
                "https://first.example",
            )
            self.assertIn("user", inspect(first_engine).get_table_names())

        with TestClient(second_app) as client:
            response = client.options(
                "/api/news",
                headers={
                    "Origin": "https://second.example",
                    "Access-Control-Request-Method": "GET",
                },
            )
            self.assertEqual(
                response.headers["access-control-allow-origin"],
                "https://second.example",
            )
            self.assertEqual(inspect(second_engine).get_table_names(), [])
