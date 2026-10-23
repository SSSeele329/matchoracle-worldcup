# Data Sources and Licenses

The code license does not automatically apply to data. This repository includes only selected historical datasets whose upstream repositories identify them as public domain or CC0. Verify the upstream terms before redistributing modified copies.

| Included files | Source | Upstream terms |
| --- | --- | --- |
| `data/calibration/wc*_matches_openfootball.json` | [OpenFootball World Cup data](https://github.com/openfootball/worldcup.json) | Public domain, per upstream README |
| `data/calibration/wc2022_matches.json` | Normalized from OpenFootball 2022 World Cup match data | Public domain source data; normalized representation in this repository |
| `data/calibration/international_results.csv` | [martj42/international_results](https://github.com/martj42/international_results) | CC0-1.0, per upstream repository |
| `data/structured_facts/provider_adapter_fixture_template.json` | This project | Synthetic example; contains no live provider facts or credentials |
| `data/structured_facts/worldcup_structured_facts_sample.json` | This project | Synthetic example; not official match data |
| `data/odds/worldcup_odds_sample.csv` | This project | Synthetic example; odds are illustrative only |

`data/calibration/wc2022_fifa_ranks.json` is a manually prepared research seed, not an official archived ranking export. It should not be presented as authoritative evidence.

Historical Elo snapshot JSON files sourced from international-football.net are not included because redistribution terms were not verified. The optional fetch script retrieves those ratings directly from the source; users are responsible for reviewing the source terms before using or redistributing downloaded data. Local SQLite databases, live provider payloads, generated prediction reports, and API credentials are also excluded.
