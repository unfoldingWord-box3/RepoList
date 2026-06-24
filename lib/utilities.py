"""Utility functions for ODS spreadsheet I/O, HTTP helpers, and data manipulation.

This module provides a set of misc utilities including:

- Reading and writing OpenDocument Spreadsheet (ODS) files
- Low-level HTTP request handling with retry logic
- Loading environment variables from .env files
- Parsing and manipulating spreadsheet data (dates, booleans, lists)
- Data validation and type conversions

GitHub API functions are in lib.github_utils.
npm registry functions are in lib.npm_utils.

Dependencies:
    - pandas: DataFrame operations and Excel/ODS file I/O
    - xml.etree.ElementTree: XML parsing for ODS internal structure
    - Standard library modules for HTTP requests, CSV, datetime operations

Environment Variables:
    GITHUB_TOKEN: Read by lib.github_utils; not used directly by this module.

Constants:
    NS: Namespace dictionary for ODS XML parsing (office, table, text namespaces)
"""
import csv
import datetime
import os
import re
import sys
import time
import urllib.error
import urllib.request
import zipfile
import xml.etree.ElementTree as ET

import pandas as pd

NS = {
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
}


def read_ods_sheets(input_file):
    """
    Read all sheets from an ODS file into pandas DataFrames.

    Uses pandas with the 'odf' engine to read an OpenDocument Spreadsheet file
    and return all sheets as a dictionary of DataFrames.

    Args:
        input_file (str): Path to the ODS file to read.

    Returns:
        dict[str, pandas.DataFrame]: Mapping of sheet names to DataFrames, where
                                     each DataFrame represents one sheet from the
                                     ODS file with columns and rows preserved.
    """
    return pd.read_excel(
        input_file,
        sheet_name=None,
        engine="odf"
    )


def write_ods_sheets(output_file, sheets):
    """
    Write one or more pandas DataFrames to an ODS file as named sheets.

    Creates or overwrites an OpenDocument Spreadsheet file with the provided
    sheet data. Sheet names longer than 31 characters are automatically truncated
    to comply with spreadsheet format limitations.

    Args:
        output_file (str): Path to the ODS file to write. Parent directories must exist.
        sheets (dict[str, pandas.DataFrame] | pandas.DataFrame): Sheet data to write.
            If a dict is provided, keys are sheet names and values are DataFrames.
            If a single DataFrame is provided, it is written to a sheet named "Sheet1".

    Returns:
        None
    """
    if isinstance(sheets, pd.DataFrame):
        sheets = {"Sheet1": sheets}

    with pd.ExcelWriter(output_file, engine="odf") as writer:
        for sheet_name, dataframe in sheets.items():
            dataframe.to_excel(
                writer,
                sheet_name=str(sheet_name)[:31],
                index=False,
            )

    print(f"Data saved to {output_file}")


def write_rows_to_ods(output_file, sheet_name, rows):
    """
    Write a list of row dictionaries to a single-sheet ODS file.

    Convenience wrapper that converts a list of dictionaries to a DataFrame
    and writes it as a single sheet in an ODS file.

    Args:
        output_file (str): Path to the ODS file to write.
        sheet_name (str): Name of the sheet. Will be truncated to 31 characters if longer.
        rows (list[dict]): List of row dictionaries where keys are column names.
                          All dictionaries should have the same keys for consistent columns.

    Returns:
        None
    """
    dataframe = pd.DataFrame(rows)
    write_ods_sheets(output_file, {sheet_name: dataframe})


def _convert_hyperlink_cells(table):
    """Convert =HYPERLINK("url","text") string cells to proper ODF hyperlink formula cells.

    LibreOffice requires three things for a clickable HYPERLINK cell:
      - table:formula='of:=HYPERLINK(url,display)'  (the formula)
      - office:string-value="display"               (cached result, suppresses the ' prefix)
      - <text:a xlink:href="url">display</text:a>  (rendered link text)
    """
    HYPERLINK_RE = re.compile(r'^=HYPERLINK\("([^"]+)",\s*"([^"]+)"\)$')

    TEXT_NS_URI = NS["text"]
    TABLE_NS_URI = NS["table"]
    OFFICE_NS_URI = NS["office"]
    XLINK_NS_URI = "http://www.w3.org/1999/xlink"

    TABLE_ROW_TAG = f"{{{TABLE_NS_URI}}}table-row"
    TABLE_CELL_TAG = f"{{{TABLE_NS_URI}}}table-cell"
    TEXT_P_TAG = f"{{{TEXT_NS_URI}}}p"
    TEXT_A_TAG = f"{{{TEXT_NS_URI}}}a"

    converted = 0
    for row_elem in table:
        if row_elem.tag != TABLE_ROW_TAG:
            continue
        for cell in row_elem:
            if cell.tag != TABLE_CELL_TAG:
                continue
            p_elems = [c for c in cell if c.tag == TEXT_P_TAG]
            if not p_elems:
                continue
            p = p_elems[0]
            cell_text = "".join(p.itertext()).strip()
            m = HYPERLINK_RE.match(cell_text)
            if not m:
                continue
            url, display = m.group(1), m.group(2)

            # Remove any formula attribute — it causes Err:508 in LibreOffice when
            # the of: namespace isn't declared. LibreOffice's own Insert > Hyperlink
            # uses <text:a> + office:string-value with no formula attribute.
            formula_attr = f"{{{TABLE_NS_URI}}}formula"
            if formula_attr in cell.attrib:
                del cell.attrib[formula_attr]

            cell.set(f"{{{OFFICE_NS_URI}}}value-type", "string")
            cell.set(f"{{{OFFICE_NS_URI}}}string-value", display)

            # Replace <text:p> content with a <text:a> hyperlink element.
            for child in list(p):
                p.remove(child)
            p.text = None
            a = ET.SubElement(p, TEXT_A_TAG)
            a.set(f"{{{XLINK_NS_URI}}}type", "simple")
            a.set(f"{{{XLINK_NS_URI}}}href", url)
            a.text = display
            converted += 1

    print(f"Converted {converted} cells to hyperlinks")


def update_ods_sheet_data(output_file, sheet_name, rows):
    """
    Update the data rows in a named sheet of an existing ODS file, preserving column styles.

    If the file does not yet exist, falls back to write_rows_to_ods() to create it fresh.
    When the file does exist, only the <table:table-row> elements in the target sheet are
    replaced; all other content (column-width styles, other sheets, metadata) is kept intact,
    so manually-set column widths survive across runs.

    Args:
        output_file (str): Path to the ODS file to update or create.
        sheet_name (str): Name of the sheet whose rows should be replaced.
        rows (list[dict]): New row data as a list of dictionaries.

    Returns:
        None
    """
    TABLE_TAG = f"{{{NS['table']}}}table"
    TABLE_NAME_ATTR = f"{{{NS['table']}}}name"
    TABLE_ROW_TAG = f"{{{NS['table']}}}table-row"

    def register_all_namespaces(xml_bytes):
        for prefix, uri in re.findall(rb'xmlns:(\w+)="([^"]+)"', xml_bytes):
            ET.register_namespace(prefix.decode(), uri.decode())

    def read_content_xml(zip_path):
        with zipfile.ZipFile(zip_path, "r") as z:
            return z.read("content.xml")

    def find_table(root, name):
        for table in root.iter(TABLE_TAG):
            if table.get(TABLE_NAME_ATTR) == name:
                return table
        return None

    def save_root_to_zip(root, src_zip_path, out_path):
        updated_xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        with zipfile.ZipFile(src_zip_path, "r") as src_zip:
            with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as out_zip:
                for item in src_zip.infolist():
                    if item.filename == "content.xml":
                        out_zip.writestr(item, updated_xml)
                    else:
                        out_zip.writestr(item, src_zip.read(item.filename))

    # Write new data to a temp file so pandas formats the rows as valid ODS XML.
    tmp_new = output_file + ".tmp_new.ods"
    tmp_out = output_file + ".tmp_out.ods"
    try:
        write_rows_to_ods(tmp_new, sheet_name, rows)

        new_content = read_content_xml(tmp_new)
        # Register namespaces found in new content plus xlink (needed for hyperlinks).
        register_all_namespaces(new_content)
        ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")
        ET.register_namespace("office", NS["office"])
        new_root = ET.fromstring(new_content)
        new_table = find_table(new_root, sheet_name)

        if new_table is not None:
            _convert_hyperlink_cells(new_table)

        if not os.path.exists(output_file):
            # Fresh create: save the hyperlink-converted content.
            save_root_to_zip(new_root, tmp_new, tmp_out)
            os.replace(tmp_out, output_file)
            print(f"Data saved to {output_file}")
            return

        existing_content = read_content_xml(output_file)
        register_all_namespaces(existing_content)
        existing_root = ET.fromstring(existing_content)
        existing_table = find_table(existing_root, sheet_name)

        if existing_table is None or new_table is None:
            # Sheet not found — replace whole file with converted content.
            save_root_to_zip(new_root, tmp_new, tmp_out)
            os.replace(tmp_out, output_file)
            print(f"Data saved to {output_file}")
            return

        # Remove old rows from the existing table, keeping column-style elements.
        for child in list(existing_table):
            if child.tag == TABLE_ROW_TAG:
                existing_table.remove(child)

        # Append new rows (already hyperlink-converted).
        for row in new_table:
            if row.tag == TABLE_ROW_TAG:
                existing_table.append(row)

        updated_xml = ET.tostring(existing_root, encoding="utf-8", xml_declaration=True)

        # Rebuild the ZIP: copy every file from the existing ODS, replacing content.xml.
        with zipfile.ZipFile(output_file, "r") as existing_zip:
            with zipfile.ZipFile(tmp_out, "w", zipfile.ZIP_DEFLATED) as out_zip:
                for item in existing_zip.infolist():
                    if item.filename == "content.xml":
                        out_zip.writestr(item, updated_xml)
                    else:
                        out_zip.writestr(item, existing_zip.read(item.filename))

        os.replace(tmp_out, output_file)
        print(f"Data updated in {output_file}")
    finally:
        for path in (tmp_new, tmp_out):
            if os.path.exists(path):
                os.remove(path)


def safe_filename(name):
    """
    Convert a sheet name into a safe filename by replacing invalid characters.

    This function removes or replaces characters that are not allowed in filenames
    on common filesystems (Windows, macOS, Linux). It replaces invalid characters
    with underscores and trims whitespace.

    Args:
        name (str): The original sheet name or string to convert.

    Returns:
        str: A filesystem-safe filename string. Returns "sheet" if the input
             is empty or becomes empty after processing.
    """
    name = re.sub(r'[\\/*?:"<>|]', "_", name)
    name = name.strip()
    return name or "sheet"


def urlopen_with_retry(request, retries=1, retry_delay_seconds=5):
    """
    Open a URL with automatic retry on transient network errors.

    Retries on OSError/URLError (e.g. connection reset, timeout) but raises
    immediately on HTTP errors so callers can inspect the status code and
    headers directly. Rate-limit handling (403/429) is the caller's responsibility.

    Args:
        request (urllib.request.Request): The HTTP request object to execute.
        retries (int, optional): Number of retry attempts for transient errors. Defaults to 1.
        retry_delay_seconds (int, optional): Seconds to wait between retries. Defaults to 5.

    Returns:
        http.client.HTTPResponse: The HTTP response object from a successful request.

    Raises:
        urllib.error.HTTPError: Immediately on any HTTP error (4xx, 5xx) — not retried here.
        urllib.error.URLError: If all retry attempts are exhausted for network errors
                              (connection refused, timeout, DNS failure, etc.).
    """
    for attempt in range(retries + 1):
        try:
            return urllib.request.urlopen(request)
        except urllib.error.HTTPError:
            raise
        except urllib.error.URLError as error:
            if attempt < retries:
                print(
                    f"Network error, retrying in {retry_delay_seconds}s ({attempt + 1}/{retries}): {error.reason}",
                    file=sys.stderr,
                )
                time.sleep(retry_delay_seconds)
                continue
            raise


def load_env_file(env_file):
    """
    Load environment variables from a .env file into os.environ.

    Parses a simple .env file format with KEY=value pairs. Lines starting with #
    are treated as comments. Quoted values (single or double quotes) are unquoted.
    Only sets variables that don't already exist in os.environ.

    Args:
        env_file (str): Path to the .env file to load.

    Returns:
        None
    """
    if not os.path.exists(env_file):
        return

    with open(env_file, mode="r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()

            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")

            if key and key not in os.environ:
                os.environ[key] = value


def get_cell_text(cell):
    """
    Extract plain text from an ODS table cell.

    Extracts and concatenates text from all paragraphs within a cell,
    joining multiple paragraphs with newlines.

    Args:
        cell (xml.etree.ElementTree.Element): ODS table cell XML element.

    Returns:
        str: Plain text content of the cell with paragraphs separated by newlines.
    """
    parts = []

    for paragraph in cell.findall(".//text:p", NS):
        text = "".join(paragraph.itertext())
        parts.append(text)

    return "\n".join(parts)


def read_ods_sheet(filename, sheet_name):
    """Read rows from a named sheet in an ODS file.

    This function extracts tabular data from an OpenDocument Spreadsheet (ODS) file
    by parsing its internal XML structure. It handles ODS-specific features like
    repeated rows/columns and normalizes the output to a consistent rectangular grid.

    Args:
        filename (str): Path to the ODS file to read.
        sheet_name (str): Name of the sheet to extract from the ODS file.

    Returns:
        list[list[str]]: A 2D list representing the sheet data, where each inner list
                         is a row of cells. All rows have the same width (determined
                         by the first non-empty row, typically the header).

    Raises:
        ValueError: If the specified sheet_name is not found in the ODS file.

    Processing Details:
        1. Extracts and parses the content.xml file from the ODS ZIP archive
        2. Locates the sheet matching the provided sheet_name
        3. For each row in the sheet:
           - Handles ODS row repetition (number-rows-repeated attribute)
           - For each cell:
             * Extracts text content using get_cell_text()
             * Handles ODS column repetition (number-columns-repeated attribute)
             * Prevents excessive empty column repetition in the header row
             * Constrains cells to the established header width for data rows
           - First row establishes header_width by trimming trailing empty cells
           - Subsequent rows are padded or truncated to match header_width
        4. Returns all rows with consistent column counts

    Note:
        - Empty cells are represented as empty strings ("")
        - The first row determines the number of columns for all subsequent rows
        - ODS files may contain repeated row/column attributes for compression;
          this function expands them to their full representation
    """

    # ODS files are ZIP archives. The spreadsheet data lives in content.xml,
    # so open the archive, read that XML file, and parse it into an ElementTree.
    with zipfile.ZipFile(filename, "r") as ods:
        with ods.open("content.xml") as content:
            tree = ET.parse(content)

    root = tree.getroot()

    # Find every table element in the document. Each table represents one sheet.
    sheets = root.findall(".//table:table", NS)

    for sheet in sheets:
        # ODS stores the sheet name as a namespaced table:name attribute.
        name = sheet.attrib.get(f"{{{NS['table']}}}name")

        # Skip sheets until we find the one the caller requested.
        if name != sheet_name:
            continue

        rows = []

        # The first row is treated as the header. Its width is used to normalize
        # all following rows so CSV output has a consistent number of columns.
        header_width = None

        for row in sheet.findall("table:table-row", NS):
            # ODS may compress identical consecutive rows using
            # table:number-rows-repeated. Default to 1 when it is not present.
            repeated_rows = int(
                row.attrib.get(f"{{{NS['table']}}}number-rows-repeated", "1")
            )

            row_data = []

            for cell in row.findall("table:table-cell", NS):
                # ODS may also compress identical consecutive cells using
                # table:number-columns-repeated.
                repeated_cols = int(
                    cell.attrib.get(f"{{{NS['table']}}}number-columns-repeated", "1")
                )

                # Extract the displayed text from the cell's XML content.
                value = get_cell_text(cell)

                # In the header row, trailing blank cells can be stored as a huge
                # repeated empty range. Keep each empty header cell to one column
                # so the header width does not become artificially large.
                if header_width is None and value == "":
                    repeated_cols = 1

                # After the header width is known, do not read more columns than
                # the header defines. Extra spreadsheet cells are ignored.
                if header_width is not None:
                    remaining_cols = header_width - len(row_data)
                    if remaining_cols <= 0:
                        break
                    repeated_cols = min(repeated_cols, remaining_cols)

                # Expand repeated columns into regular cell values so callers get
                # a normal list of strings instead of ODS compression metadata.
                for _ in range(repeated_cols):
                    row_data.append(value)

            if header_width is None:
                # The first row establishes the number of columns. Remove trailing
                # blanks so accidental empty spreadsheet columns are not included.
                while row_data and row_data[-1] == "":
                    row_data.pop()

                header_width = len(row_data)

            else:
                # Keep data rows rectangular: trim rows that are too wide and pad
                # rows that are too short with empty strings.
                row_data = row_data[:header_width]

                while len(row_data) < header_width:
                    row_data.append("")

            # ODS files often store the remaining blank spreadsheet area as a
            # repeated empty row. Do not expand those rows, or a small sheet can
            # become hundreds of thousands of empty rows in memory.
            if header_width is not None and all(is_empty(value) for value in row_data):
                continue

            # Expand repeated rows after the row has been normalized. Use copy()
            # so each output row is an independent list.
            for _ in range(repeated_rows):
                rows.append(row_data.copy())

        return rows

    raise ValueError(f"Sheet not found: {sheet_name}")


def write_list_to_csv(output_csv, headers, data):
    """
    Write row dictionaries to a CSV file, flattening list values.

    Converts list values to comma-separated strings before writing to CSV.
    Useful for exporting spreadsheet data with multi-value cells.

    Args:
        output_csv (str): Path to the output CSV file.
        headers (list[str]): Column headers for the CSV file.
        data (list[dict]): List of row dictionaries to write.

    Returns:
        None
    """
    with open(output_csv, 'w', newline='', encoding='utf-8') as csvfile:
        if data:
            writer = csv.DictWriter(csvfile, fieldnames=headers)
            writer.writeheader()

            for row in data:
                flattened_row = {}
                for key, value in row.items():
                    if isinstance(value, list):
                        flattened_row[key] = ', '.join(value)
                    else:
                        flattened_row[key] = value
                writer.writerow(flattened_row)

            print(f"Data saved to {output_csv}")


def load_repository_data(ODS_FILE, SHEET_NAME):
    """
    Load repository rows from an ODS sheet and normalize comma-separated values.

    Reads a sheet from an ODS file, treats the first row as headers, and
    converts comma-separated cell values into lists.

    Args:
        ODS_FILE (str): Path to the ODS file.
        SHEET_NAME (str): Name of the sheet to read.

    Returns:
        tuple[list[str], list[dict]]: A tuple of (headers, data) where headers
                                      is the list of column names and data is a
                                      list of row dictionaries with comma-separated
                                      values split into lists.
    """
    rows = read_ods_sheet(ODS_FILE, SHEET_NAME)

    headers = rows[0]
    data = [
        dict(zip(headers, row))
        for row in rows[1:]
        if any(not is_empty(value) for value in row)
    ]

    for row in data:
        for key, value in row.items():
            if isinstance(value, str) and ',' in value:
                row[key] = [item.strip() for item in value.split(',')]

    return headers, data


def is_empty(value):
    """
    Return True when a spreadsheet value is empty.

    Handles various empty representations including None, empty strings,
    whitespace-only strings, and lists containing only empty values.

    Args:
        value: Any value from a spreadsheet cell (str, list, None, etc.).

    Returns:
        bool: True if the value is considered empty, False otherwise.
    """
    if value is None:
        return True

    if isinstance(value, list):
        return len([item for item in value if str(item).strip()]) == 0

    return str(value).strip() == ""


def is_true(value):
    """
    Return True for common spreadsheet boolean values.

    Recognizes common textual representations of boolean true values used
    in spreadsheets (case-insensitive).

    Args:
        value: Any value from a spreadsheet cell.

    Returns:
        bool: True if value matches 'true', 'yes', '1', or 'y' (case-insensitive),
              False otherwise.
    """
    return str(value).strip().lower() in {"true", "yes", "1", "y"}


def as_int(value):
    """
    Convert spreadsheet numeric values to int, treating blanks as zero.

    Handles comma-separated thousands, list values (uses first element),
    and converts via float to handle decimal strings.

    Args:
        value: Any value from a spreadsheet cell.

    Returns:
        int: Integer representation of the value, or 0 if the value is empty
             or cannot be converted.
    """
    if is_empty(value):
        return 0

    if isinstance(value, list):
        value = value[0] if value else ""

    try:
        return int(float(str(value).replace(",", "").strip()))
    except ValueError:
        return 0


def parse_date(value):
    """
    Parse common spreadsheet date formats.

    Attempts to parse date strings using multiple common formats including
    ISO 8601, US formats, and datetime with timezone.

    Args:
        value: Any value from a spreadsheet cell that may contain a date.

    Returns:
        datetime.datetime | None: Parsed datetime object, or None if the value
                                  is empty or cannot be parsed by any known format.
    """
    if is_empty(value):
        return None

    if isinstance(value, list):
        value = value[0] if value else ""

    value = str(value).strip()

    for date_format in (
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m/%d/%y",
    ):
        try:
            return datetime.datetime.strptime(value, date_format)
        except ValueError:
            continue

    try:
        return datetime.datetime.strptime(value[:10], "%Y-%m-%d")
    except ValueError:
        return None


def months_old(value):
    """
    Return approximate age in months for a date value.

    Calculates the number of complete months between a given date and today.
    Useful for determining repository or package age.

    Args:
        value: Any value that can be parsed as a date.

    Returns:
        int | None: Number of months between the date and today, or None if
                    the value cannot be parsed as a date.
    """
    date_value = parse_date(value)

    if date_value is None:
        return None

    today = datetime.datetime.today()
    return (today.year - date_value.year) * 12 + today.month - date_value.month


def contains_any(value, terms):
    """
    Return the first matching term if value contains any term from the list.

    Performs case-insensitive substring matching. Returns the matched term
    (truthy) so callers can inspect which term fired, or empty string (falsy)
    when no term matches. All existing boolean call-sites are unaffected.

    Args:
        value: Any value to search within (converted to lowercase string).
        terms (list[str]): List of terms to search for.

    Returns:
        str: The first matching term, or empty string if no term matches.
    """
    value_lower = str(value).lower()
    for term in terms:
        if term.lower() in value_lower:
            return term

    return ""