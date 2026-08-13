import os

from vps.env import load_env
from vps.providers.hetzner import HetznerProvider


def test_load_env_reads_dotenv_from_current_directory(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("HETZNER_TOKEN=from-dotenv\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("HETZNER_TOKEN", raising=False)

    assert load_env() is True
    assert os.environ["HETZNER_TOKEN"] == "from-dotenv"
    assert HetznerProvider().token == "from-dotenv"


def test_load_env_does_not_override_existing_environment(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("HETZNER_TOKEN=from-dotenv\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HETZNER_TOKEN", "from-shell")

    assert load_env() is True
    assert os.environ["HETZNER_TOKEN"] == "from-shell"
