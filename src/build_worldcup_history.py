import argparse
import json

from .worldcup_history import write_year_matches


def main():
    parser = argparse.ArgumentParser(description="Fetch and normalize World Cup match results from OpenFootball.")
    parser.add_argument("years", nargs="*", type=int, default=[2014, 2018])
    args = parser.parse_args()

    summary = {}
    for year in args.years:
        output_path, matches = write_year_matches(year)
        summary[str(year)] = {
            "output": output_path,
            "matches": len(matches),
            "extraTimeMatches": sum(1 for match in matches if "afterExtraTimeScore" in match),
            "penaltyMatches": sum(1 for match in matches if "penaltyWinner" in match),
        }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
