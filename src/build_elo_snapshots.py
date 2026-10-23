import argparse
import json

from .elo_ratings import write_worldcup_elo_snapshot


def main():
    parser = argparse.ArgumentParser(description="Fetch World Cup pre-tournament Elo snapshots.")
    parser.add_argument("years", nargs="*", type=int, default=[2002, 2006, 2010, 2014, 2018, 2022])
    args = parser.parse_args()

    summary = {}
    for year in args.years:
        output_path, payload = write_worldcup_elo_snapshot(year)
        summary[str(year)] = {
            "output": output_path,
            "snapshotDate": payload["snapshotDate"],
            "teams": len(payload["ratings"]),
            "missingTeams": payload["missingTeams"],
        }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
