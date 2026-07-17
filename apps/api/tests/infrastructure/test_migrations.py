import subprocess
import sys
from pathlib import Path


def test_offline_migration_creates_usage_table_before_extending_it() -> None:
    api_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head", "--sql"],
        cwd=api_root,
        capture_output=True,
        text=True,
        check=True,
    )

    assert "CREATE TABLE token_usage_logs" in result.stdout
    assert result.stdout.index("CREATE TABLE token_usage_logs") < result.stdout.index(
        "CREATE TABLE chat_requests"
    )
