# Inventory Cleaner — Documentation

This document explains what `inventory_cleaner.py` does, how to run it, what inputs it expects, how it processes rows, and what outputs and reports it generates. It is intended to help a new maintainer or operator understand and use the cleaner safely.

---

**Purpose**

- Clean, normalize and validate inventory data intended for Medicentre v3 import.
- Enforce consistent formatting for product names, units of measure, and accounting sub-accounts.
- Remove duplicate product names (de-duplication), aggregate/normalize numeric fields, and apply safe defaults.
- Produce a cleaned output CSV and a human-readable cleanup report.

**Files**

- `inventory_cleaner.py` — Primary implementation of the cleaning logic.
- `cleaner.py`, `inventory_import.py` — related scripts in the repository (see those files separately).
- Output files created by `inventory_cleaner.py` at runtime: `<input>_cleaned.<ext>` and `<input>_cleanup_report.txt` (or `_cleanup_error_report.txt` on failure).

---

**High-level Flow**

1. Read the input CSV (expects headers; validated against the required schema).
2. Apply Title Case to selected columns.
3. Clean product `Name` (whitespace, commas).
4. De-duplicate product names (skip duplicates, keep the first occurrence).
5. Normalize `UnitOfMeasure` (using a mapping and canonical units). Unknown units can trigger an interactive resolution.
6. Intelligently normalize sub-account fields (`AssetSubAccount`, `RevenueSubAccount`, `CostOfSaleSubAccount`) by similarity to user-provided defaults.
7. Apply defaults for missing fields (VAT, ItemClass, ItemCategory, ReorderLevel, expiry dates, etc.).
8. Validate numeric and date fields; log errors/warnings and skip invalid rows.
9. Write cleaned CSV and a comprehensive report summarizing actions taken.

---

**Required Columns (input CSV header)**

The cleaner expects the following headers. If any are missing, processing aborts with an error:

- Name
- Batch
- ItemCode
- Barcode
- AssetSubAccount
- RevenueSubAccount
- CostOfSaleSubAccount
- VATType
- UnitOfMeasure
- ItemClass
- ItemCategory
- UnitCost
- TotalQuantity
- UnitPrice
- ExpiryDate
- ReorderLevel

Note: The script uses `csv.DictReader` so column ordering is not important, but the exact header names above are required.

---

**How to run**

The script is interactive. Typical run:

```bash
py inventory_cleaner.py
```

The script will prompt for:
- Path to CSV file
- A set of `user_defaults` (VAT, item class, item category, default unit, default expiry date, reorder level, and default sub-account names)

If you prefer non-interactive usage from another script, instantiate `InventoryDataCleaner(csv_path, user_defaults)` and call `.process()`.

Example (from a Python REPL/script):

```python
from inventory_cleaner import InventoryDataCleaner

user_defaults = {
    'default_vat_type': 'VAT Exempt',
    'default_item_class': 'Product',
    'default_item_category': 'Pharmacy Drugs',
    'default_unit_of_measure': 'Pack',
    'default_expiry_date': '31/12/2026',
    'default_reorder_level': 10,
    'default_asset_account': 'Inventory - Pharmacy Drugs',
    'default_revenue_account': 'Sales - Pharmacy Drugs',
    'default_cost_account': 'Cost Of Goods Sold - Pharmacy Drugs'
}

cleaner = InventoryDataCleaner('raw_inventory.csv', user_defaults)
success, out = cleaner.process()

if success:
    print('Cleaned file:', out)
else:
    print('Processing failed:', out)
```

---

**Interactive prompts and user decisions**

- The cleaner will prompt the user when it encounters an unknown `UnitOfMeasure` that cannot be matched via mapping or canonical units.
- Prompt options include: use default, specify a new canonical unit, apply a new unit for all similar entries, or mark the unknown as valid and use as-is.
- Unit resolutions are remembered for the current run (`unit_resolutions`) so subsequent occurrences do not re-prompt.
- To avoid interactive prompts, provide conservative `user_defaults['default_unit_of_measure']` values and ensure input units are already canonical (Title Case) or present in the internal mapping.

---

**Normalization and Rules — Key Details**

- Title Case: Applied to columns in `TITLE_CASE_COLUMNS` before other processing: `Name`, `UnitOfMeasure`, `AssetSubAccount`, `RevenueSubAccount`, `CostOfSaleSubAccount`, `ItemClass`, `ItemCategory`.
- Name Cleaning: Removes commas, trims whitespace, collapses multiple spaces.
- De-duplication: De-duplicated by a normalized name key (lowercased, collapsed whitespace). The first occurrence is retained; duplicates are skipped and logged.
- Unit Normalization: A large `UNIT_MAPPING` maps many variants to canonical forms (e.g., "tabs" → "Tablet"). `CANONICAL_UNITS` lists the canonical titles.
  - If the unit is already in `CANONICAL_UNITS` (e.g., "Tablet"), it is accepted without prompting.
  - Plural/singular and mapped lookups are handled.
  - Unknown units trigger interactive resolution.
- Sub-account normalization: Sub-account text is preprocessed (lowercased, filler words removed, hyphens replaced) and compared to user-provided defaults using a similarity ratio. Similar values above thresholds are normalized to the authoritative default and recorded.
- Numeric validation: `UnitCost` and `UnitPrice` are converted to floats (rounded to 2 decimals). `TotalQuantity` and `ReorderLevel` are converted to integers (decimals truncated to integer with a normalization logged).
- Expiry date handling: Accepts `dd/mm/YYYY`. Missing or expired dates are replaced with either the provided default expiry date (if valid and in future) or computed one year in the future. Invalid formats are logged as errors.

---

**Outputs**

1. Cleaned CSV: Named `<input>_cleaned<ext>` in the same folder as the input. It is written with headers matching `REQUIRED_COLUMNS`.
2. Cleanup report: `<input>_cleanup_report.txt` (human readable) containing:
   - Defaults configured
   - Canonical units
   - Duplicates removed list
   - Defaults used
   - Normalizations applied
   - User decisions (interactive resolutions)
   - Unit resolutions
   - Warnings and errors
   - Statistics and de-duplication summary
3. Error report: If processing fails, a `cleanup_error_report.txt` will be generated with recorded errors and tracebacks.

---

**Logging, Warnings & Errors**

- The tool accumulates informational lists in `self.report`: `normalizations`, `user_decisions`, `defaults_used`, `warnings`, `errors`, and `duplicates_removed`.
- If an unrecoverable error occurs during processing, `.process()` will return `(False, <error message>)` and an error report is written.
- Numeric and date validation failures either cause the row to be skipped or defaults to be used depending on context; all such events are recorded in the report.

---

**Important internal constants**

- `UNIT_MAPPING` — dictionary mapping many lowercase variants to canonical `Title` forms.
- `CANONICAL_UNITS` — list of accepted canonical unit labels.
- `REQUIRED_COLUMNS` — list of column names validated at input read stage.
- `TITLE_CASE_COLUMNS` — columns that get Title Case applied first.

(See `inventory_cleaner.py` for the full lists.)

---

**Design notes & rationale**

- Title Casing early avoids prompting on units or accounts that are already properly cased.
- De-duplication occurs early (just after name cleaning) to avoid unnecessary work on duplicates and to ensure the first occurrence is preserved.
- Similarity-based sub-account normalization allows tolerant cleanup while keeping authoritative defaults intact.
- Interactive resolution for unknown units reduces accidental normalization errors while allowing operator control.

---

**Operational recommendations**

- Keep a copy of raw inputs unchanged; cleaned files are written next to inputs with `_cleaned` suffix.
- Provide robust `user_defaults` to reduce interactive prompts.
- Use a small sample input to validate rules before processing a full dataset.
- If automating non-interactively, call `InventoryDataCleaner` from a script and provide `user_defaults` to avoid input() prompts.
- Add `--dry-run` behaviour if you want to extend the script: currently you can emulate by running on a small sample or modifying the class to accept a `dry_run` flag.

---

**Extending / Modifying**

- To add new canonical units, update `CANONICAL_UNITS` and `UNIT_MAPPING`.
- To accept alternate input header names, add a mapping layer before validation or change `REQUIRED_COLUMNS` accordingly.
- To persist `unit_resolutions` between runs, store `unit_resolutions` to a small JSON file after run and load it at start.
- To make sub-account thresholds configurable, expose the similarity thresholds as parameters.

---

**Quick reference of key public API**

- `InventoryDataCleaner(csv_path: str, user_defaults: dict)` — constructor.
- `.validate_defaults()` — validate `user_defaults` (expiry format, reorder level).
- `.process() -> Tuple[bool, str]` — run the full cleaning pipeline; returns (success, output_or_error).
- `.generate_report(report_path: Path)` — write the human-readable cleanup report.

---


