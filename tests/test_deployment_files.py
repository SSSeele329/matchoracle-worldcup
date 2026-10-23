from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_dockerfile_uses_gunicorn_and_app_module():
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "FROM python:3.13-slim" in dockerfile
    assert "gunicorn" in dockerfile
    assert "app:app" in dockerfile
    assert "EXPOSE 5012" in dockerfile


def test_production_compose_declares_web_worker_and_shared_volume():
    compose = (PROJECT_ROOT / "deploy" / "docker-compose.production.example.yml").read_text(encoding="utf-8")

    assert "web:" in compose
    assert "worker:" in compose
    assert "scripts/run_production_worker.py" in compose
    assert "MATCHORACLE_APP_ENV: production" in compose
    assert "MATCHORACLE_WORKER_RUNTIME_CONFIGURED: \"1\"" in compose
    assert "MATCHORACLE_STRUCTURED_FACTS_STORE: /var/lib/matchoracle/structured_facts.sqlite3" in compose
    assert "matchoracle-data:" in compose
    assert "/api/health" in compose


def test_dockerignore_keeps_data_but_excludes_local_state():
    dockerignore = (PROJECT_ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert ".venv" in dockerignore
    assert "__pycache__" in dockerignore
    assert "*.sqlite3" in dockerignore
    assert "\ndata\n" not in dockerignore
