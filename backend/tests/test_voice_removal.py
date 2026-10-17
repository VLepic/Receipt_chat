import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text

from app.main import app
from app.models.settings import UserSettings
from app.schemas.settings import UserSettingsRead, UserSettingsUpdate


def test_voice_routes_and_tts_setting_are_removed():
    assert not any(route.path.startswith("/api/voice") for route in app.routes)
    assert "tts_voice" not in UserSettings.__table__.columns
    assert "tts_voice" not in UserSettingsRead.model_fields
    assert "tts_voice" not in UserSettingsUpdate.model_fields


def test_voice_cleanup_migration_preserves_chat_data():
    migration_path = Path(__file__).parents[1] / "alembic/versions/0019_remove_voice.py"
    spec = importlib.util.spec_from_file_location("remove_voice", migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE "user" (id UUID PRIMARY KEY)'))
        connection.execute(text("CREATE TABLE conversations (id UUID PRIMARY KEY, title TEXT)"))
        connection.execute(text("INSERT INTO conversations VALUES ('test', 'My chat')"))
        connection.execute(text("CREATE TABLE user_settings (id UUID PRIMARY KEY, tts_voice VARCHAR(120))"))
        connection.execute(text("CREATE TABLE voice_sessions (id UUID PRIMARY KEY)"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert "voice_sessions" not in inspect(connection).get_table_names()
            assert [column["name"] for column in inspect(connection).get_columns("user_settings")] == ["id"]
            assert connection.scalar(text("SELECT title FROM conversations")) == "My chat"
            migration.downgrade()
            assert "voice_sessions" in inspect(connection).get_table_names()
            assert "tts_voice" in [column["name"] for column in inspect(connection).get_columns("user_settings")]
            migration.upgrade()
