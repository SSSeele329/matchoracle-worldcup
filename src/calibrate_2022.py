import json
from argparse import ArgumentParser

from .calibration import DEFAULT_WC2022_METRICS_REPORT, run_wc2022_calibration, write_wc2022_probability_metrics_report


def parse_args():
    parser = ArgumentParser(description="Run the 2022 World Cup probability metrics replay.")
    parser.add_argument("--write-report", action="store_true", help="Write the Markdown probability metrics report.")
    parser.add_argument("--report-path", default=DEFAULT_WC2022_METRICS_REPORT, help="Markdown report path.")
    return parser.parse_args()


def main():
    args = parse_args()
    report = run_wc2022_calibration()
    if args.write_report:
        print(f"Wrote {write_wc2022_probability_metrics_report(report, args.report_path)}")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print("\n建议：")
    for item in report["recommendations"]:
        print(f"- {item}")
    print("\n过度自信样例：")
    for row in report["biggestOverconfidence"][:5]:
        print(
            f"- {row['match']} | 预测 {row['predictedResult']} 实际 {row['actualResult']} "
            f"| 概率 {row['probabilities']}"
        )


if __name__ == "__main__":
    main()
