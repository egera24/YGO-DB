import importlib
import os
import unittest
from unittest.mock import patch

from sqlalchemy.engine import make_url


class TestDatabaseMigrations(unittest.TestCase):
    def test_strips_neon_pooler_from_migration_url(self):
        pooled = (
            "postgresql://user:pass@ep-abc-pooler.us-east-2.aws.neon.tech/neondb?sslmode=require"
        )
        with patch.dict(
            os.environ,
            {"DATABASE_URL": pooled},
            clear=False,
        ):
            os.environ.pop("DATABASE_URL_MIGRATIONS", None)
            import ygo_app.config as cfg

            importlib.reload(cfg)
            url = cfg.database_url_for_migrations()
            self.assertNotIn("-pooler", make_url(url).host or "")
            self.assertEqual(cfg.database_host_fingerprint(url), "neon-direct")

    def test_host_fingerprint_pooler(self):
        import ygo_app.config as cfg

        self.assertEqual(
            cfg.database_host_fingerprint(
                "postgresql://u:p@ep-x-pooler.aws.neon.tech/db?sslmode=require"
            ),
            "neon-pooler",
        )


if __name__ == "__main__":
    unittest.main()
