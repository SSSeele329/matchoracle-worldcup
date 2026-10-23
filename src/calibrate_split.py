import json

from .calibration import run_split_backtest


def main():
    report = run_split_backtest(mode="historical")
    print(json.dumps({
        "mode": report["mode"],
        "calibrationYears": report["calibrationYears"],
        "blindTestYear": report["blindTestYear"],
        "calibrationSummary": report["calibrationSummary"],
        "blindTestSummary": report["blindTestSummary"],
        "yearSummaries": {
            item["year"]: item["summary"] for item in report["yearReports"]
        },
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
