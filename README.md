# Inventory Cleanup & Import — Quick README

This repository contains scripts to clean and import inventory data for Medicentre v3.

Quick overview

- `inventory_cleaner.py` — Interactive cleaner that normalizes names, units, accounts, removes duplicate product names, validates numeric/date fields, and writes a cleaned CSV plus a cleanup report.
- `inventory_import.py` — (Separate) handles importing the cleaned CSV into the target system.

Run (interactive)

```powershell
py inventory_cleaner.py
```

Follow prompts to provide:
- CSV path
- Defaults: VAT, Item Class, Item Category, Unit of Measure, Expiry Date, Reorder Level, and default sub-account names

Run (programmatic / non-interactive)

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
    print('Cleaned CSV:', out)
else:
    print('Error:', out)
```

Outputs

- Cleaned CSV: `<input>_cleaned.<ext>` (same folder as input)
- Cleanup report: `<input>_cleanup_report.txt`
- On failure: `cleanup_error_report.txt`

Tips

- Keep a copy of the raw file; cleaned files are written next to the original with a `_cleaned` suffix.
- Provide robust `user_defaults` to reduce interactive prompts (especially `default_unit_of_measure`).
- Test on a small sample first.