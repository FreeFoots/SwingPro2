import ast
import io
import logging
import os
from pathlib import Path
import secrets
import tempfile
import unittest

# Isolated local settings, without consulting an existing application database.
TEMP_ROOT = Path(tempfile.mkdtemp(prefix='swingpro2-test-'))
os.environ.update(PG_HOST='127.0.0.1', PG_PORT='5432', PG_USER='swingpro2', PG_DB='swingpro2',
                  PG_PASSWORD=secrets.token_urlsafe(24), JWT_SECRET=secrets.token_urlsafe(48),
                  REDIS_URL='', CELERY_TASK_ALWAYS_EAGER='false',
                  CELERY_BROKER_URL='memory://', CELERY_RESULT_BACKEND='cache+memory://',
                  VIDEO_ROOT=str(TEMP_ROOT / 'videos'), THUMB_ROOT=str(TEMP_ROOT / 'thumbs'),
                  VIDEO_TMP_ROOT=str(TEMP_ROOT / 'downloads'), DRAW_JSON_ROOT=str(TEMP_ROOT / 'drawings'),
                  LOG_DIR=str(TEMP_ROOT / 'logs'), APP_NAME='SwingPro2', SMS_PROVIDER='local')

from fastapi.testclient import TestClient
from pydantic import ValidationError
from app.core.config import PROJECT_ROOT, Settings
from app.main import app
from app.db.models.video import Video
from app.schemas.video import VideoOut
from app.core.celery_app import celery_app


class ConfigurationTests(unittest.TestCase):
    def config(self, **kwargs):
        return Settings(PG_PASSWORD=secrets.token_urlsafe(24), JWT_SECRET=secrets.token_urlsafe(48), **kwargs)

    def test_required_secrets_and_placeholders_are_rejected(self):
        for kwargs in ({}, {'PG_PASSWORD': 'replace-local', 'JWT_SECRET': 'replace-random'},
                       {'PG_PASSWORD': 'local-only', 'JWT_SECRET': 'short'}):
            with self.assertRaises(ValidationError):
                Settings(**kwargs)

    def test_example_covers_all_configuration_fields(self):
        keys = {line.split('=', 1)[0] for line in (PROJECT_ROOT / '.env.example').read_text().splitlines()
                if line and not line.startswith('#')}
        self.assertEqual(keys, set(Settings.model_fields))

    def test_paths_resolve_against_project_not_working_directory(self):
        cfg = self.config()
        self.assertEqual(cfg.VIDEO_ROOT, str(PROJECT_ROOT / 'storage/videos'))
        self.assertEqual(self.config(LOG_DIR='another/logs').LOG_DIR, str(PROJECT_ROOT / 'another/logs'))

    def test_database_password_special_characters_are_preserved(self):
        password = 'local @:/#? password'
        cfg = Settings(PG_PASSWORD=password, JWT_SECRET=secrets.token_urlsafe(48))
        self.assertEqual(cfg.database_url.password, password)
        self.assertIn('%40', cfg.database_url.render_as_string(hide_password=False))

    def test_boolean_cors_and_optional_redis_parsing(self):
        cfg = self.config(CELERY_TASK_ALWAYS_EAGER='false', REDIS_URL='',
                          CORS_ORIGINS='["http://localhost:8000"]')
        self.assertFalse(cfg.CELERY_TASK_ALWAYS_EAGER)
        self.assertIsNone(cfg.REDIS_URL)
        self.assertEqual(cfg.CORS_ORIGINS, ['http://localhost:8000'])
        self.assertEqual(self.config(CORS_ORIGINS='http://localhost:8000, http://localhost:3000').CORS_ORIGINS,
                         ['http://localhost:8000', 'http://localhost:3000'])


class ApplicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def test_health_and_static_assets(self):
        self.assertEqual(self.client.get('/health').json(), {'status': 'ok'})
        for path in ('/', '/platform.html', '/player.html', '/platform.js', '/player.js',
                     '/users/login/', '/users/login/auth.js', '/assets/logo.svg'):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_video_routes_still_require_login(self):
        self.assertEqual(self.client.get('/videos/admin/summary').status_code, 401)

    def test_no_recognition_api_or_schema(self):
        schema = self.client.get('/openapi.json').json()
        self.assertNotIn('/videos/admin/predicted-labels', schema['paths'])
        self.assertNotIn('predicted_label', Video.__table__.columns)
        self.assertNotIn('predicted_label', VideoOut.model_fields)
        self.assertNotIn('predicted_label', str(schema))
        self.assertEqual(self.client.get('/platform-fusenet.html').status_code, 404)

    def test_logging_does_not_capture_invalid_auth_body(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        logger = logging.getLogger('app.core.middleware')
        logger.addHandler(handler)
        try:
            marker = secrets.token_urlsafe(40)
            response = self.client.post('/auth/login', json={'password': marker})
            self.assertEqual(response.status_code, 422)
            self.assertNotIn(marker, stream.getvalue())
            self.assertIn('status=422', stream.getvalue())
        finally:
            logger.removeHandler(handler)

    def test_metadata_task_loads_without_identity_services(self):
        import app.services.tasks
        self.assertIn('analyze_video_metadata', celery_app.tasks)
        self.assertFalse(any('identity' in task for task in celery_app.tasks))

    def test_all_python_files_parse(self):
        for directory in ('app', 'scripts'):
            for path in (PROJECT_ROOT / directory).rglob('*.py'):
                with self.subTest(path=str(path.relative_to(PROJECT_ROOT))):
                    ast.parse(path.read_text())


if __name__ == '__main__':
    unittest.main()
