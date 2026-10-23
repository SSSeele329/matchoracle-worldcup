from src.worldcup import consumer_fixtures as cf
from src.worldcup.odds_import import import_live_odds_snapshots


def fixture_row(match_id, group, matchday, home, away, kickoff):
    return {
        "matchId": match_id,
        "snapshotTime": "2026-06-14T00:00:00+00:00",
        "source": "test",
        "providerId": "test",
        "fact": {
            "matchId": match_id,
            "stage": "GROUP_STAGE",
            "group": group,
            "matchday": matchday,
            "homeTeam": home,
            "awayTeam": away,
            "kickoffAt": kickoff,
        },
    }


def score_row(match_id, home, away):
    return {
        "matchId": match_id,
        "fact": {
            "status": "FINISHED",
            "winner": "HOME_TEAM" if home > away else "AWAY_TEAM" if away > home else "DRAW",
            "duration": "REGULAR",
            "fullTime": {"home": home, "away": away},
        },
    }


def test_live_odds_for_match_maps_reversed_provider_home_away(monkeypatch, tmp_path):
    monkeypatch.setenv("MATCHORACLE_ODDS_STORE", str(tmp_path / "odds.sqlite3"))
    monkeypatch.setattr(cf, "live_odds_payload", lambda: {
        "snapshots": [{
            "provider": "the_odds_api",
            "homeTeam": "Switzerland",
            "awayTeam": "Qatar",
            "kickoffAt": "2026-06-14T19:00:00+00:00",
            "snapshotTime": "2026-06-14T10:00:00+00:00",
            "source": "the_odds_api:consensus:2",
            "decimalOdds": {"home": 1.9, "draw": 3.4, "away": 4.2},
        }],
    })

    odds = cf.odds_for_match({
        "homeTeam": "Qatar",
        "awayTeam": "Switzerland",
        "kickoffAt": "2026-06-14T19:00:00+00:00",
    }, 2026)

    assert odds["decimalOdds"] == {"home": 4.2, "draw": 3.4, "away": 1.9}
    assert odds["source"] == "the_odds_api:consensus:2"


def test_odds_for_match_reads_persisted_market_snapshot(monkeypatch, tmp_path):
    monkeypatch.setenv("MATCHORACLE_ODDS_STORE", str(tmp_path / "odds.sqlite3"))
    monkeypatch.setattr(cf, "live_odds_payload", lambda: None)
    import_live_odds_snapshots([{
        "provider": "the_odds_api",
        "homeTeam": "Germany",
        "awayTeam": "Curaçao",
        "kickoffAt": "2026-06-14T19:00:00+00:00",
        "snapshotTime": "2026-06-14T10:00:00+00:00",
        "source": "the_odds_api:consensus:4",
        "decimalOdds": {"home": 1.86, "draw": 3.9, "away": 4.75},
    }], source_name="the_odds_api")

    odds = cf.odds_for_match({
        "homeTeam": "Germany",
        "awayTeam": "Curaçao",
        "kickoffAt": "2026-06-14T19:00:00+00:00",
    }, 2026)

    assert odds["decimalOdds"] == {"home": 1.86, "draw": 3.9, "away": 4.75}
    assert odds["source"] == "the_odds_api"


def test_auto_f05_contexts_generate_group_motivation(monkeypatch):
    fixture_rows = {}
    score_rows = {}
    for group_index, group_letter in enumerate("ABCDEFGHIJKL", start=1):
        teams = [f"Team {group_letter}{index}" for index in range(1, 5)]
        group = f"Group {group_letter}"
        pairings = [
            (1, teams[0], teams[1], "2026-06-12T19:00:00+00:00"),
            (1, teams[2], teams[3], "2026-06-13T19:00:00+00:00"),
            (2, teams[0], teams[2], "2026-06-18T19:00:00+00:00"),
            (2, teams[1], teams[3], "2026-06-19T19:00:00+00:00"),
            (3, teams[0], teams[3], "2026-06-24T19:00:00+00:00"),
            (3, teams[1], teams[2], "2026-06-24T19:00:00+00:00"),
        ]
        for item_index, (matchday, home, away, kickoff) in enumerate(pairings, start=1):
            match_id = f"m-{group_letter}-{item_index}"
            fixture_rows[match_id] = fixture_row(match_id, group, matchday, home, away, kickoff)
            if item_index == 1:
                score_rows[match_id] = score_row(match_id, 2 if group_index == 1 else 1, 0)

    contexts = cf.auto_f05_contexts(fixture_rows, score_rows)
    context = contexts["m-A-3"]

    assert context["qualificationModel"] == "WC2026_48_FAST_PATH"
    assert context["homeQualificationStatus"] in {"OPEN", "MUST_WIN", "NEED_DRAW", "ALREADY_QUALIFIED", "ELIMINATED_RISK"}
    assert set(context["homeQualificationByOutcome"]) == {"W", "D", "L"}
    assert "homeMotivationScore" in context
    assert "awayRotationRisk" in context
