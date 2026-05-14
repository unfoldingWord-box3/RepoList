import os

from utilities import read_ods_sheets, safe_filename

INPUT_FILE = "unfoldingword_repos.ods"
OUTPUT_DIR = "."


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    sheets = read_ods_sheets(INPUT_FILE)

    for sheet_name, df in sheets.items():
        filename = safe_filename(sheet_name) + ".csv"
        output_path = os.path.join(OUTPUT_DIR, filename)

        df.to_csv(output_path, index=False, encoding="utf-8")

        print(f"Saved sheet '{sheet_name}' to {output_path}")


if __name__ == "__main__":
    main()
