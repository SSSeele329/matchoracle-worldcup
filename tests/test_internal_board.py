from app import app


def test_internal_test_board_route_exposes_operator_sections():
    response = app.test_client().get("/internal")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "MatchOracle Internal Test Board" in html
    assert "id=\"view-overview\"" in html
    assert "id=\"view-predict\"" in html
    assert "id=\"view-data\"" in html
    assert "id=\"view-odds\"" in html
    assert "id=\"view-jobs\"" in html
    assert "id=\"view-snapshots\"" in html
    assert "id=\"view-calibration\"" in html


def test_internal_test_board_wires_existing_api_surface():
    response = app.test_client().get("/internal")
    html = response.get_data(as_text=True)

    for endpoint in [
        "/api/health",
        "/api/readiness",
        "/api/predict",
        "/api/structured-facts/sync",
        "/api/f05/monte-carlo",
        "/api/odds/import",
        "/api/jobs/run-next",
        "/api/snapshots",
        "/api/calibration/wc2022",
        "/api/calibration/split",
    ]:
        assert endpoint in html
