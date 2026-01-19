# Inventory Import — Documentation

This document explains what `inventory_import.py` does, how to run it, what inputs it expects, how it processes data, and what outputs and reports it generates. It is intended to help a new maintainer or operator understand and use the importer safely.

---

**Purpose**

- Import cleaned inventory data from a CSV file into Medicentre v3 system using automated web browser interactions.
- Perform comprehensive prerequisite verification and creation before importing items.
- Handle creation of missing ledger accounts, VAT types, units of measure, item categories, and item classes.
- Provide detailed logging, screenshots for debugging, and comprehensive import reports.
- Support dry-run mode for validation without making actual changes.

**Files**

- `inventory_import.py` — Primary implementation containing the `MedicentreV3InventoryImporter` class.
- `config_loader.py` — Configuration management utility for loading, creating, and saving Medicentre settings.
- `manage_config.py` — Interactive configuration manager for viewing and updating settings.
- `inventory_cleaner.py` — Related script that produces the cleaned CSV input (see `inventory_cleaner.md`).
- Output directories created at runtime:
  - `logs/` — Contains timestamped log files and screenshots
  - `reports/` — Contains JSON import reports

---

**High-level Flow**

1. **Setup & Authentication**: Collect configuration, credentials, and CSV path through interactive prompts.
2. **Browser Initialization**: Launch Edge browser (or headless) and login to Medicentre v3.
3. **Prerequisite Verification**: Navigate to each relevant panel and verify/create required entities:
   - Chart of Accounts (main accounts and sub-accounts)
   - Taxes/VAT Types
   - Units of Measure
   - Item Categories
   - Item Classes
4. **Inventory Import**: Upload and process the cleaned CSV file through the Inventory panel.
5. **Reporting**: Generate detailed JSON report and console summary.

---

**Required Input**

**Cleaned CSV File**
- Must be produced by `inventory_cleaner.py` or follow the same schema.
- Expected columns: Name, Batch, ItemCode, Barcode, AssetSubAccount, RevenueSubAccount, CostOfSaleSubAccount, VATType, UnitOfMeasure, ItemClass, ItemCategory, UnitCost, TotalQuantity, UnitPrice, ExpiryDate, ReorderLevel

**Configuration Parameters** (collected interactively):
- Medicentre v3 base URL
- Authentication: Access Code, Branch, Username, Password
- Storage Location (e.g., "Main Store")
- Default Department for new categories (e.g., "Pharmacy")
- Headless mode (y/n)
- Dry run mode (y/n)

---

**Prerequisites Verification Process**

The importer verifies and creates missing prerequisites in the following order:

1. **Chart of Accounts**
   - Extracts unique sub-accounts from CSV columns: AssetSubAccount, RevenueSubAccount, CostOfSaleSubAccount
   - Maps sub-accounts to main accounts (configurable)
   - Creates missing main accounts and sub-accounts hierarchically

2. **VAT Types**
   - Extracts unique VAT types from CSV VATType column
   - Verifies existing VAT types in Taxes panel
   - Allows bulk or individual creation of missing VAT types with rates and tax codes

3. **Units of Measure**
   - Extracts unique units from CSV UnitOfMeasure column
   - Normalizes to Title Case
   - Creates missing units in Unit of Measure panel

4. **Item Categories**
   - Extracts unique categories from CSV ItemCategory column
   - Creates missing categories in Item Categories panel
   - Associates with specified department

5. **Item Classes**
   - Extracts unique classes from CSV ItemClass column
   - Creates missing classes in Item Classes panel

---

**How to Run**

The script is interactive. Typical run:

```bash
py inventory_import.py
```

The script will prompt for all required information:

1. **Configuration**
   - Headless mode: Run browser invisibly (recommended for production)
   - Storage Location: Default inventory location
   - Default Department: For new item categories

2. **Authentication**
   - Medicentre v3 URL: Base URL of the system
   - Access Code: Hospital access code
   - Branch: Branch name
   - Username: Login username
   - Password: Login password

3. **CSV File**
   - Path to cleaned CSV file from inventory_cleaner.py

4. **Execution Mode**
   - Dry run: Validate prerequisites without making changes
   - Live mode: Perform actual import

**Example Interactive Session:**

```
============================================================
MEDICENTRE v3 INVENTORY IMPORTER
============================================================

--- Configuration ---
Run in headless mode? (y/n): y
Storage Location (e.g., 'Main Store'): Main Store
Default department for new categories (e.g., 'Pharmacy'): Pharmacy

--- Authentication ---
Medicentre v3 URL: https://medicentre.example.com
Access Code: ABC123
Branch: Main Branch
Username: admin
Password: ********

--- CSV File ---
Path to cleaned CSV file: cleaned_inventory.csv

--- Execution Mode ---
Dry run (validate only, no changes)? (y/n): n

Proceed with import? (y/n): y
```

---

**Programmatic Usage**

For integration or automated runs, you can instantiate the importer directly:

```python
from inventory_import import MedicentreV3InventoryImporter

# Configuration
config = {
    "headless": True,
    "storage_location": "Main Store",
    "default_department": "Pharmacy",
    "account_mappings": {
        "inventory_main": "Inventory",
        "inventory_class": "Current Assets",
        "revenue_main": "Revenue", 
        "revenue_class": "Income",
        "cost_main": "Cost of Goods Sold",
        "cost_class": "Cost of Goods Sold"
    },
    "vat_default_rate": 16,
    "vat_default_tax_code": "E"
}

# Credentials
credentials = {
    "accesscode": "ABC123",
    "branch": "Main Branch", 
    "username": "admin",
    "password": "secret"
}

# Create importer
importer = MedicentreV3InventoryImporter(
    base_url="https://medicentre.example.com",
    credentials=credentials,
    config=config,
    dry_run=False
)

# Run import
stats = importer.import_data("cleaned_inventory.csv")
```

---

**Configuration Management**

The importer uses a JSON-based configuration system for persistent settings:

- `medicentre_config.json` — Stores all configuration including credentials, URLs, and mappings
- `config_loader.py` — Utility class for loading, creating, and saving configurations
- `manage_config.py` — Interactive tool for managing configuration files

**Using Configuration Files:**

```bash
# Create new configuration interactively
py manage_config.py
# Select option 1 to create new config

# Or load existing config in importer
py inventory_import.py
# Select "Load existing configuration? (y/n): y"
```

**Configuration Structure:**
```json
{
  "base_url": "https://medicentre.example.com",
  "accesscode": "ABC123",
  "branch": "Main Branch",
  "username": "admin",
  "password": "secret",
  "headless": true,
  "storage_location": "Main Store",
  "default_department": "Pharmacy",
  "account_mappings": {
    "inventory_main": "Inventory",
    "inventory_class": "Current Assets",
    "revenue_main": "Revenue",
    "revenue_class": "Income",
    "cost_main": "Cost of Goods Sold",
    "cost_class": "Cost of Goods Sold"
  },
  "vat_default_rate": 16,
  "vat_default_tax_code": "E",
  "last_csv_path": "cleaned_inventory.csv"
}
```

---

**Output Files and Reports**

**Log Files** (`logs/` directory):
- `medicentre_import_YYYYMMDD_HHMMSS.log` — Detailed execution log with timestamps
- `screenshots/` subdirectory — PNG screenshots captured on errors or key actions

**Import Reports** (`reports/` directory):
- `import_report_YYYYMMDD_HHMMSS.json` — Comprehensive JSON report with:
  - Execution timestamp
  - Dry run flag
  - Detailed statistics for each verification step
  - Success rates and summary metrics

**Console Output:**
- Real-time progress updates
- Final summary with counts of created items and success rates

---

**Verification Statistics**

The importer tracks detailed statistics in `verification_stats`:

- `accounts_verified/created` — Chart of accounts entities
- `vat_verified/vat_errors` — VAT type verification
- `units_verified/created` — Units of measure
- `categories_verified/created` — Item categories  
- `classes_verified/created` — Item classes
- `items_imported/failed/skipped` — Final import results

---

**Error Handling and Recovery**

- **Session Management**: Automatically re-logs in if session expires
- **Screenshot Capture**: Takes screenshots on errors for debugging
- **Graceful Failure**: Stops import if critical prerequisites fail
- **Detailed Logging**: All actions logged with timestamps and error details

---

**Safety Features**

- **Dry Run Mode**: Validate all prerequisites without making changes
- **Confirmation Prompts**: Requires explicit confirmation before live import
- **Comprehensive Logging**: Full audit trail of all actions
- **Screenshot Evidence**: Visual records of system state during execution

---

**Troubleshooting**

**Common Issues:**

1. **Login Failures**
   - Verify credentials and URL
   - Check network connectivity
   - Review login screenshots in `logs/screenshots/`

2. **Prerequisite Creation Failures**
   - Check user permissions in Medicentre
   - Verify account class names match system options
   - Review panel-specific error logs

3. **Import Failures**
   - Ensure CSV was properly cleaned by inventory_cleaner.py
   - Check for special characters or encoding issues
   - Verify all prerequisite entities were created successfully

**Debug Mode:**
- Run with `dry_run=True` to test without changes
- Check detailed logs for specific error messages
- Use screenshots to understand system state

---

**Dependencies**

- Python 3.7+
- selenium — Web automation
- Edge WebDriver (included with Edge browser)
- Standard library modules: csv, logging, pathlib, json, datetime

**Environment Setup:**
```bash
# Install dependencies (if using venv)
pip install selenium

# Ensure Edge browser is installed
# WebDriver is managed automatically by selenium
```

**Configuration Management**

The importer uses a JSON-based configuration system for persistent settings:

- `medicentre_config.json` — Stores all configuration including credentials, URLs, and mappings
- `config_loader.py` — Utility class for loading, creating, and saving configurations
- `manage_config.py` — Interactive tool for managing configuration files

**Using Configuration Files:**

```bash
# Create new configuration interactively
py manage_config.py
# Select option 1 to create new config

# Or load existing config in importer
py inventory_import.py
# Select "Load existing configuration? (y/n): y"
```

**Configuration Structure:**
```json
{
  "base_url": "https://medicentre.example.com",
  "accesscode": "ABC123",
  "branch": "Main Branch",
  "username": "admin",
  "password": "secret",
  "headless": true,
  "storage_location": "Main Store",
  "default_department": "Pharmacy",
  "account_mappings": {
    "inventory_main": "Inventory",
    "inventory_class": "Current Assets",
    "revenue_main": "Revenue",
    "revenue_class": "Income",
    "cost_main": "Cost of Goods Sold",
    "cost_class": "Cost of Goods Sold"
  },
  "vat_default_rate": 16,
  "vat_default_tax_code": "E",
  "last_csv_path": "cleaned_inventory.csv"
}
```

---

**Best Practices**

1. **Always run dry-run first** on new data or system changes
2. **Monitor logs closely** during execution
3. **Keep screenshots** for audit trails
4. **Review import reports** for success metrics
5. **Use headless mode** for production runs to avoid interference

---

**Integration with Inventory Cleaner**

This importer is designed to work with the output of `inventory_cleaner.py`:

1. Run `inventory_cleaner.py` to clean and validate raw inventory data
2. Use the generated `_cleaned.csv` file as input to this importer
3. Review the cleanup report to understand any data transformations
4. Proceed with import using the cleaned data