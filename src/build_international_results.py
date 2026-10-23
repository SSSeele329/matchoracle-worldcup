import os
import urllib.request

from .worldcup.historical_features import DEFAULT_RESULTS_PATH, INTERNATIONAL_RESULTS_URL


def main():
    os.makedirs(os.path.dirname(DEFAULT_RESULTS_PATH), exist_ok=True)
    urllib.request.urlretrieve(INTERNATIONAL_RESULTS_URL, DEFAULT_RESULTS_PATH)
    print(f"wrote {DEFAULT_RESULTS_PATH}")


if __name__ == "__main__":
    main()
