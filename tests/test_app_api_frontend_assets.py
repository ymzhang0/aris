import asyncio

from fastapi.responses import FileResponse, HTMLResponse

from src import app_api


def test_spa_catch_all_serves_root_frontend_assets(tmp_path, monkeypatch) -> None:
    asset = tmp_path / "aris.svg"
    asset.write_text("<svg/>", encoding="utf-8")
    monkeypatch.setattr(app_api, "FRONTEND_DIST_DIR", str(tmp_path))

    response = asyncio.run(app_api.spa_catch_all("aris.svg"))

    assert isinstance(response, FileResponse)
    assert response.path == str(asset)


def test_spa_catch_all_rejects_paths_outside_frontend_dist(tmp_path, monkeypatch) -> None:
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    index_file = dist_dir / "index.html"
    index_file.write_text("<html/>", encoding="utf-8")
    secret = tmp_path / "secret.txt"
    secret.write_text("secret", encoding="utf-8")
    monkeypatch.setattr(app_api, "FRONTEND_DIST_DIR", str(dist_dir))
    monkeypatch.setattr(app_api, "FRONTEND_INDEX_FILE", str(index_file))

    response = asyncio.run(app_api.spa_catch_all("../secret.txt"))

    assert isinstance(response, FileResponse)
    assert response.path == str(index_file)


def test_spa_catch_all_keeps_api_paths_out_of_the_spa(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(app_api, "FRONTEND_DIST_DIR", str(tmp_path))

    response = asyncio.run(app_api.spa_catch_all("api/missing"))

    assert isinstance(response, HTMLResponse)
    assert response.status_code == 404
