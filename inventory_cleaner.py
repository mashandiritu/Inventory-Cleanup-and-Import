import csv
import re
from datetime import datetime, timedelta
from pathlib import Path
import sys
from typing import Dict, List, Tuple, Optional, Any, Set
from difflib import SequenceMatcher  # For similarity comparison

class InventoryDataCleaner:
    """Cleans and standardizes inventory data for Medicentre v3"""
    
    # Unit of measure normalization mapping (all lowercase for case-insensitive matching)
    UNIT_MAPPING = {
    "tab": "Tablet", "tablet": "Tablet", "tabs": "Tablet", "tb": "Tablet",
    "tbs": "Tablet", "tbl": "Tablet", "tbt": "Tablet", "caplet": "Tablet",
    "caplets": "Tablet", "loz": "Lozenge", "lozenge": "Lozenge",
    "troche": "Lozenge", "caps": "Capsule", "cp": "Capsule", "capsules":"Capsule",
    "capsule": "Capsule", "bottle": "Bottle", "bottles": "Bottle", "bottles":"Bottle",
    "btl": "Bottle", "vial": "Vial", "vials": "Vial", "amps": "Ampoule",
    "ampoule": "Ampoule", "ampul": "Ampoule", "ampule": "Ampoule",
    "ampules": "Ampoule", "sachet": "Sachet", "sachets": "Sachet",
    "satchet": "Sachet", "satchets": "Sachet", "strip": "Strip",
    "strips": "Strip", "blister": "Strip", "blisters": "Strip",
    "pack": "Pack", "packs": "Pack", "pkt": "Pack", "paket": "Packet",
    "box": "Box", "boxes": "Box", "bx": "Box", "ctn": "Carton", 
    "tin": "Tin", "can": "Can", "jar": "Jar", "tube": "Tube", "tubes": "Tube",
    "millilitre": "Ml", "mls": "Ml", "syrup": "Ml", "suspension": "Ml", 
    "susp": "Ml", "sol": "Ml", "solution": "Ml", "infusion": "Ml", 
    "injection": "Ml", "cc": "Ml", "emulsion": "Ml", "drop": "Drop", "drops": "Drop", 
    "oint": "Ointment", "crm": "Tube", "cream": "Tube", "gel": "Tube", 
    "l": "Litre", "litre": "Litre", "liters": "Litre", "ltr": "Litre", 
    "lts": "Litre", "mgs": "Mg", "milligram": "Mg", "gram": "G", 
    "gm": "G", "grm": "G", "gr": "G", "kilo": "Kg", "kilos": "Kg", 
    "kilogram": "Kg", "kilogrammes": "Kg", "pc": "Piece", "pcs": "Piece",
    "piece": "Piece", "pce": "Piece", "supp": "Suppository", 
    "supps": "Suppository", "supository": "Suppository", "pessary": "Pessary",
    "ovule": "Pessary", "kit":"Kit", "capsules": "Capsule", "tablets":"Tablet"
    }
    
    # List of canonical units in their correct Title Case form
    CANONICAL_UNITS = [
        'Tablet', 'Capsule', 'Bottle', 'Vial', 'Ampoule', 'Sachet', 'Strip',
        'Pack', 'Box', 'Tube', 'Ml', 'Mg', 'Litre', 'G', 'Kg', 'Unit', 'Jar',
        'Lozenge', 'Piece', 'Pessary', 'Kit', 'Suppository'
    ]
    
    REQUIRED_COLUMNS = [
        'Name', 'Batch', 'ItemCode', 'Barcode', 'AssetSubAccount', 'RevenueSubAccount',
        'CostOfSaleSubAccount', 'VATType', 'UnitOfMeasure', 'ItemClass', 'ItemCategory',
        'UnitCost', 'TotalQuantity', 'UnitPrice', 'ExpiryDate', 'ReorderLevel'
    ]
    
    # Columns to apply Title Case to BEFORE any other processing
    TITLE_CASE_COLUMNS = [
        'Name', 'UnitOfMeasure', 'AssetSubAccount', 'RevenueSubAccount',
        'CostOfSaleSubAccount', 'ItemClass', 'ItemCategory'
    ]
    
    def __init__(self, csv_path: str, user_defaults: Dict):
        """
        Initialize cleaner with CSV path and user defaults
        
        Args:
            csv_path: Path to input CSV file
            user_defaults: Dictionary containing:
                - default_vat_type: str
                - default_item_class: str
                - default_item_category: str
                - default_unit_of_measure: str
                - default_expiry_date: str (dd/mm/yyyy)
                - default_reorder_level: int (optional)
                - default_asset_account: str (optional)
                - default_revenue_account: str (optional)
                - default_cost_account: str (optional)
        """
        self.csv_path = csv_path
        self.user_defaults = user_defaults
        self.cleaned_data = []
        self.report = {
            'normalizations': [],
            'user_decisions': [],
            'defaults_used': [],
            'warnings': [],
            'errors': [],
            'duplicates_removed': []  # New section for tracking duplicates
        }
        self.unit_resolutions = {}  # Track user resolutions for unknown units
        self.seen_names: Set[str] = set()  # Track normalized product names for de-duplication
        
        # Set default defaults if not provided
        self.user_defaults.setdefault('default_reorder_level', 10)
        self.user_defaults.setdefault('default_asset_account', 'Inventory - Pharmacy Drugs')
        self.user_defaults.setdefault('default_revenue_account', 'Sales - Pharmacy Drugs')
        self.user_defaults.setdefault('default_cost_account', 'Cost Of Goods Sold - Pharmacy Drugs')
    
    def validate_defaults(self):
        """Validate user-provided defaults"""
        # Validate expiry date format and future date
        try:
            expiry = datetime.strptime(self.user_defaults['default_expiry_date'], '%d/%m/%Y')
            min_future_date = datetime.now() + timedelta(days=365)
            if expiry <= min_future_date:
                self.report['warnings'].append(
                    f"Default expiry date {expiry.strftime('%d/%m/%Y')} is not at least 1 year in future"
                )
        except ValueError:
            raise ValueError(f"Invalid expiry date format. Expected dd/mm/yyyy, got {self.user_defaults['default_expiry_date']}")
        
        # Validate reorder level is integer
        try:
            reorder_level = int(self.user_defaults['default_reorder_level'])
            if reorder_level < 0:
                raise ValueError("Reorder level cannot be negative")
        except (ValueError, TypeError):
            raise ValueError(f"Invalid default reorder level. Must be a positive integer, got {self.user_defaults['default_reorder_level']}")
    
    def apply_title_case(self, value: str, column_name: str) -> str:
        """
        Apply Proper/Title Case to string values
        Preserves special casing for known acronyms/patterns
        """
        if not value or not isinstance(value, str):
            return value
        
        original_value = value
        
        # Convert to Title Case with smart handling
        words = value.split()
        title_words = []
        
        for word in words:
            # Handle special cases
            if word.upper() in ['VAT', 'DR', 'MR', 'MRS', 'MS', 'CEO', 'CFO']:
                title_words.append(word.upper())
            elif '-' in word:
                # Handle hyphenated words
                parts = word.split('-')
                title_parts = [p.title() if not p.isupper() else p for p in parts]
                title_words.append('-'.join(title_parts))
            elif word.isupper():
                # If entire word is uppercase, title case it
                title_words.append(word.title())
            elif word.islower():
                # If entire word is lowercase, title case it
                title_words.append(word.title())
            else:
                # Mixed case - preserve existing capitalization if it's already Title Case
                # Check if it looks like Title Case (first letter capital, rest lowercase)
                if len(word) > 1 and word[0].isupper() and word[1:].islower():
                    title_words.append(word)  # Already Title Case, preserve
                else:
                    title_words.append(word.title())
        
        result = ' '.join(title_words)
        
        # Log if change was made
        if original_value != result:
            self.report['normalizations'].append(
                f"Title Case applied to {column_name}: '{original_value}' → '{result}'"
            )
        
        return result
    
    def normalize_sub_account(self, value: str, default_value: str, account_type: str, row_index: int) -> str:
        """
        Intelligently normalize sub-account names based on similarity to defaults.
        
        Args:
            value: The current value in the cell
            default_value: The authoritative default value for this account type
            account_type: One of 'AssetSubAccount', 'RevenueSubAccount', 'CostOfSaleSubAccount'
            row_index: Row number for reporting
        
        Returns:
            Normalized account name
        """
        if not value or value.strip() == '':
            # Empty value - use default (existing behavior)
            self.report['defaults_used'].append(
                f"Row {row_index}: Empty {account_type} replaced with default '{default_value}'"
            )
            return default_value
        
        original_value = value.strip()
        
        # Step 1: Preprocess for comparison
        def preprocess_for_comparison(text: str) -> str:
            """Normalize text for similarity comparison"""
            # Convert to lowercase
            text = text.lower()
            # Remove all hyphens and replace with space
            text = text.replace('-', ' ')
            # Remove extra whitespace
            text = re.sub(r'\s+', ' ', text)
            # Remove common filler words that don't affect meaning
            filler_words = ['the', 'and', '&', 'for', 'to', 'in', 'of']
            words = text.split()
            filtered_words = [w for w in words if w not in filler_words]
            return ' '.join(filtered_words).strip()
        
        # Step 2: Check similarity
        processed_value = preprocess_for_comparison(original_value)
        processed_default = preprocess_for_comparison(default_value)
        
        # Calculate similarity ratio using difflib
        similarity_ratio = SequenceMatcher(None, processed_value, processed_default).ratio()
        
        # Step 3: Determine action based on similarity
        # Thresholds can be adjusted based on testing
        if similarity_ratio >= 0.85:  # High similarity - normalize to exact default
            if original_value != default_value:
                self.report['normalizations'].append(
                    f"Row {row_index}: {account_type} normalized "
                    f"'{original_value}' → '{default_value}' "
                    f"(similarity: {similarity_ratio:.2f})"
                )
            return default_value
        elif similarity_ratio >= 0.60:  # Moderate similarity - still normalize
            if original_value != default_value:
                self.report['normalizations'].append(
                    f"Row {row_index}: {account_type} normalized "
                    f"'{original_value}' → '{default_value}' "
                    f"(similarity: {similarity_ratio:.2f})"
                )
            return default_value
        else:  # Low similarity - replace with default (not a normalization)
            self.report['defaults_used'].append(
                f"Row {row_index}: {account_type} replaced "
                f"'{original_value}' → '{default_value}' "
                f"(similarity: {similarity_ratio:.2f} too low)"
            )
            return default_value
    
    def clean_name(self, name: str) -> str:
        """Clean product name (after Title Case has been applied)"""
        original = name
        
        # Replace commas with spaces
        name = name.replace(',', ' ')
        # Remove duplicate spaces
        name = re.sub(r'\s+', ' ', name)
        # Trim spaces
        name = name.strip()
        
        if original != name:
            self.report['normalizations'].append(f"Name cleaned: '{original}' → '{name}'")
        
        return name
    
    def normalize_name_key(self, name: str) -> str:
        """
        Create a normalized key for name de-duplication
        - Convert to lowercase
        - Remove extra whitespace
        - Useful for case-insensitive and whitespace-insensitive comparison
        """
        if not name:
            return ''
        # Normalize whitespace and convert to lowercase
        return re.sub(r'\s+', ' ', name.strip()).lower()
    
    def check_duplicate_name(self, cleaned_name: str, row_index: int) -> Tuple[bool, Optional[int]]:
        """
        Check if cleaned_name is a duplicate
        Returns: (is_duplicate, retained_row_number)
        """
        normalized_name = self.normalize_name_key(cleaned_name)
        
        if not normalized_name:
            return False, None  # Empty names are not considered duplicates
        
        # Check if we've seen this normalized name before
        if normalized_name in self.seen_names:
            # Find which row originally had this name
            for i, row in enumerate(self.cleaned_data, 1):
                if self.normalize_name_key(row['Name']) == normalized_name:
                    return True, i  # Found duplicate, return original row number
        
        return False, None
    
    def clean_vat_type(self, vat_type: str, row_index: int) -> str:
        """Clean VAT type"""
        if not vat_type or vat_type.strip() == '':
            self.report['defaults_used'].append(
                f"Row {row_index}: Empty VATType replaced with default '{self.user_defaults['default_vat_type']}'"
            )
            return self.user_defaults['default_vat_type']
        
        vat_type = vat_type.strip()
        
        # Preserve existing casing for known VAT types
        valid_casings = ['VAT Exempt', 'Standard VAT', 'Zero Rated', 'Exempt']
        if vat_type in valid_casings:
            return vat_type
        
        # Try to match case-insensitively
        vat_lower = vat_type.lower()
        for valid in valid_casings:
            if valid.lower() == vat_lower:
                self.report['normalizations'].append(
                    f"Row {row_index}: VATType case corrected '{vat_type}' → '{valid}'"
                )
                return valid
        
        # If not a known type, use default
        self.report['warnings'].append(
            f"Row {row_index}: Unknown VATType '{vat_type}' replaced with default"
        )
        return self.user_defaults['default_vat_type']
    
    def normalize_unit_of_measure(self, unit: str, product_name: str, row_index: int) -> str:
        """
        Normalize unit of measure with user interaction for unknown units
        IMPORTANT: This runs AFTER Title Case has been applied
        
        Key Fix: Units already in canonical Title Case (e.g., 'Tablet', 'Capsule') 
        should NOT trigger user prompts.
        """
        if not unit or unit.strip() == '':
            self.report['defaults_used'].append(
                f"Row {row_index}: Empty UnitOfMeasure replaced with default '{self.user_defaults['default_unit_of_measure']}'"
            )
            return self.user_defaults['default_unit_of_measure']
        
        unit = unit.strip()
        
        # FIX 1: Check if unit is already in canonical Title Case form
        if unit in self.CANONICAL_UNITS:
            # Already correct, no normalization needed
            return unit
        
        # FIX 2: Check if unit matches default unit (which may not be in CANONICAL_UNITS)
        if unit == self.user_defaults['default_unit_of_measure']:
            # Matches default, no normalization needed
            return unit
        
        # Check if already resolved by user in this session (case-insensitive)
        unit_lower = unit.lower()
        if unit_lower in self.unit_resolutions:
            return self.unit_resolutions[unit_lower]
        
        # Check mapping (case-insensitive)
        if unit_lower in self.UNIT_MAPPING:
            normalized = self.UNIT_MAPPING[unit_lower]
            if unit != normalized:
                self.report['normalizations'].append(
                    f"Row {row_index}: Unit normalized '{unit}' → '{normalized}'"
                )
            return normalized
        
        # Check if unit is singular/plural variation of canonical unit
        # This handles cases like 'Tablets' (plural) when canonical is 'Tablet' (singular)
        for canonical in self.CANONICAL_UNITS:
            canonical_lower = canonical.lower()
            # Check for exact match after removing common plural suffixes
            unit_singular = self._make_singular(unit_lower)
            if unit_singular == canonical_lower:
                self.report['normalizations'].append(
                    f"Row {row_index}: Unit '{unit}' recognized as plural of '{canonical}'"
                )
                return canonical
        
        # FIX 3: Check if unit is Title Case version of something in our mapping
        # This handles cases where user might have manually entered correct Title Case
        # but it's not in our canonical list (e.g., 'Milliliter' vs 'Millilitre')
        for mapped_lower, mapped_canonical in self.UNIT_MAPPING.items():
            if unit.lower() == mapped_lower:
                # Found a match, return the canonical version
                self.report['normalizations'].append(
                    f"Row {row_index}: Unit '{unit}' normalized to '{mapped_canonical}'"
                )
                return mapped_canonical
        
        # Check if this looks like it could be a proper unit (Title Case, single word)
        if (unit.istitle() and ' ' not in unit and 
            len(unit) <= 20 and  # Reasonable length for a unit
            unit.isalpha()):  # Only letters
            # Might be a valid unit we don't know about
            self.report['warnings'].append(
                f"Row {row_index}: Unit '{unit}' appears to be valid Title Case but not in known units list"
            )
            # Still prompt user to confirm
            
        # Unknown unit - prompt user
        print(f"\n{'='*60}")
        print(f"Product: {product_name}")
        print(f"Unknown unit of measure: '{unit}'")
        print(f"{'='*60}")
        
        while True:
            print("\nOptions:")
            print("1. Use default unit of measure")
            print("2. Specify new unit of measure")
            print("3. Use for all similar units (case-insensitive)")
            print("4. Mark as valid (use as-is)")
            
            choice = input("Enter choice (1-4): ").strip()
            
            if choice == '1':
                resolved = self.user_defaults['default_unit_of_measure']
                self.report['user_decisions'].append(
                    f"Row {row_index}: Unknown unit '{unit}' → default '{resolved}'"
                )
                self.unit_resolutions[unit_lower] = resolved
                return resolved
                
            elif choice == '2':
                new_unit = input("Enter new unit (in Proper Case, e.g., 'Tablet'): ").strip()
                if not new_unit:
                    print("Unit cannot be empty. Please try again.")
                    continue
                
                # Apply Title Case to user input
                new_unit = self.apply_title_case(new_unit, 'UserSpecifiedUnit')
                
                self.report['user_decisions'].append(
                    f"Row {row_index}: Unknown unit '{unit}' → '{new_unit}'"
                )
                self.unit_resolutions[unit_lower] = new_unit
                return new_unit
                
            elif choice == '3':
                new_unit = input("Enter new unit (in Proper Case, e.g., 'Tablet'): ").strip()
                if not new_unit:
                    print("Unit cannot be empty. Please try again.")
                    continue
                
                # Apply Title Case to user input
                new_unit = self.apply_title_case(new_unit, 'UserSpecifiedUnit')
                
                self.unit_resolutions[unit_lower] = new_unit
                self.report['user_decisions'].append(
                    f"Row {row_index}: Unknown unit '{unit}' → '{new_unit}' (applied to all similar)"
                )
                return new_unit
                
            elif choice == '4':
                # User confirms this is a valid unit, use as-is
                self.report['user_decisions'].append(
                    f"Row {row_index}: Unit '{unit}' marked as valid and used as-is"
                )
                # Add to resolutions so future occurrences don't prompt
                self.unit_resolutions[unit_lower] = unit
                return unit
            else:
                print("Invalid choice. Please enter 1, 2, 3, or 4.")
    
    def _make_singular(self, word: str) -> str:
        """Convert plural word to singular (basic implementation)"""
        # Common plural endings
        if word.endswith('s'):
            if word.endswith('ies'):
                return word[:-3] + 'y'
            elif word.endswith('ves'):
                return word[:-3] + 'f'
            elif word.endswith('es') and len(word) > 2:
                # Check if removing 'es' makes sense
                base = word[:-2]
                if base.endswith(('ch', 'sh', 'x', 's', 'z')):
                    return base
            else:
                return word[:-1]
        return word
    
    def handle_empty_sub_accounts(self, row: Dict, row_index: int) -> Dict:
        """
        Handle sub-account fields with intelligent normalization
        Replaces the original simple empty-check logic
        """
        updated_row = row.copy()
        
        # Asset Sub Account
        asset_value = row.get('AssetSubAccount', '')
        updated_row['AssetSubAccount'] = self.normalize_sub_account(
            asset_value,
            self.user_defaults['default_asset_account'],
            'AssetSubAccount',
            row_index
        )
        
        # Revenue Sub Account
        revenue_value = row.get('RevenueSubAccount', '')
        updated_row['RevenueSubAccount'] = self.normalize_sub_account(
            revenue_value,
            self.user_defaults['default_revenue_account'],
            'RevenueSubAccount',
            row_index
        )
        
        # Cost of Sale Sub Account
        cost_value = row.get('CostOfSaleSubAccount', '')
        updated_row['CostOfSaleSubAccount'] = self.normalize_sub_account(
            cost_value,
            self.user_defaults['default_cost_account'],
            'CostOfSaleSubAccount',
            row_index
        )
        
        return updated_row
    
    def validate_numeric(self, value: Any, field_name: str, row_index: int) -> Tuple[Optional[float], bool]:
        """Validate numeric fields"""
        if value is None or (isinstance(value, str) and value.strip() == ''):
            self.report['warnings'].append(f"Row {row_index}: {field_name} is empty")
            return None, True  # Return True to allow default handling
        
        try:
            # Convert to string and clean
            str_value = str(value).strip()
            # Remove any currency symbols, commas, or extra spaces
            cleaned = re.sub(r'[^\d.-]', '', str_value)
            
            if field_name in ['UnitCost', 'UnitPrice']:
                num_value = float(cleaned)
                # Round to 2 decimal places for currency
                return round(num_value, 2), True
            else:  # TotalQuantity, ReorderLevel
                # Handle decimal values by truncating (not rounding)
                num_value = float(cleaned)
                int_value = int(num_value)
                if int_value != num_value:
                    self.report['normalizations'].append(
                        f"Row {row_index}: {field_name} '{value}' converted to integer '{int_value}'"
                    )
                return int_value, True
        except (ValueError, TypeError) as e:
            self.report['errors'].append(f"Row {row_index}: Invalid {field_name} value '{value}' - {str(e)}")
            return None, False
    
    def handle_reorder_level(self, value: Any, row_index: int) -> int:
        """Handle ReorderLevel with default value"""
        if value is None or (isinstance(value, str) and value.strip() == ''):
            self.report['defaults_used'].append(
                f"Row {row_index}: Empty ReorderLevel replaced with default '{self.user_defaults['default_reorder_level']}'"
            )
            return int(self.user_defaults['default_reorder_level'])
        
        # Validate numeric
        validated, is_valid = self.validate_numeric(value, 'ReorderLevel', row_index)
        if not is_valid:
            # If validation fails, use default
            self.report['defaults_used'].append(
                f"Row {row_index}: Invalid ReorderLevel '{value}' replaced with default '{self.user_defaults['default_reorder_level']}'"
            )
            return int(self.user_defaults['default_reorder_level'])
        
        if validated is None:
            # Empty but valid case
            self.report['defaults_used'].append(
                f"Row {row_index}: Empty ReorderLevel replaced with default '{self.user_defaults['default_reorder_level']}'"
            )
            return int(self.user_defaults['default_reorder_level'])
        
        # Ensure positive integer
        reorder_int = int(validated)
        if reorder_int < 0:
            self.report['warnings'].append(
                f"Row {row_index}: Negative ReorderLevel {reorder_int} replaced with default"
            )
            return int(self.user_defaults['default_reorder_level'])
        
        return reorder_int
    
    def handle_expiry_date(self, date_str: str, row_index: int) -> Tuple[str, bool]:
        """
        Handle expiry date with enhanced logic
        Returns: (date_string, is_valid)
        """
        today = datetime.now()
        default_date = self.user_defaults['default_expiry_date']
        
        # Case 1: Empty date
        if not date_str or date_str.strip() == '':
            # Use default date if valid
            try:
                default_dt = datetime.strptime(default_date, '%d/%m/%Y')
                if default_dt > today:
                    self.report['defaults_used'].append(
                        f"Row {row_index}: Missing expiry date replaced with default '{default_date}'"
                    )
                    return default_date, True
            except ValueError:
                pass
            
            # Compute future date (1 year from today)
            future_date = (today + timedelta(days=365)).strftime('%d/%m/%Y')
            self.report['defaults_used'].append(
                f"Row {row_index}: Missing expiry date replaced with computed future date '{future_date}'"
            )
            return future_date, True
        
        # Case 2: Validate format and check if expired
        try:
            expiry_dt = datetime.strptime(date_str.strip(), '%d/%m/%Y')
            
            # Check if date is in the past
            if expiry_dt <= today:
                # Use default date if valid and future
                try:
                    default_dt = datetime.strptime(default_date, '%d/%m/%Y')
                    if default_dt > today:
                        self.report['defaults_used'].append(
                            f"Row {row_index}: Expired date '{date_str}' replaced with default '{default_date}'"
                        )
                        return default_date, True
                except ValueError:
                    pass
                
                # Compute future date (1 year from today)
                future_date = (today + timedelta(days=365)).strftime('%d/%m/%Y')
                self.report['defaults_used'].append(
                    f"Row {row_index}: Expired date '{date_str}' replaced with computed future date '{future_date}'"
                )
                return future_date, True
            
            # Date is valid and in future
            return date_str.strip(), True
            
        except ValueError:
            # Invalid format
            self.report['errors'].append(f"Row {row_index}: Invalid expiry date format '{date_str}'")
            return date_str, False
    
    def clean_row(self, row: Dict, row_index: int) -> Optional[Dict]:
        """
        Clean a single row of data with strict ordering:
        1. Title Case normalization
        2. Name cleaning (comma removal, spacing)
        3. De-duplication check
        4. Unit of measure normalization
        5. Intelligent sub-account normalization
        6. Default value application
        7. Validation (numeric, dates)
        """
        cleaned_row = {}
        try:
            # PHASE 1: TITLE CASE NORMALIZATION (First Step)
            # Apply Title Case to specified columns BEFORE any other processing
            for column in self.TITLE_CASE_COLUMNS:
                if column in row:
                    cleaned_row[column] = self.apply_title_case(row[column], column)
                else:
                    cleaned_row[column] = ''
        
            # Copy other columns as-is for now
            for column in ['Batch', 'ItemCode', 'Barcode', 'VATType', 'ExpiryDate']:
                cleaned_row[column] = row.get(column, '')
        
            # PHASE 2: NAME CLEANING (After Title Case)
            cleaned_row['Name'] = self.clean_name(cleaned_row['Name'])

            # PHASE 3: DE-DUPLICATION CHECK (Immediately after Name cleaning)
            # Check for duplicate names BEFORE any further processing
            is_duplicate, retained_row = self.check_duplicate_name(cleaned_row['Name'], row_index)

            if is_duplicate:
                # This is a duplicate - log and skip processing
                self.report['duplicates_removed'].append(
                    f"Row {row_index} skipped: Duplicate Name '{cleaned_row['Name']}' (already processed in Row {retained_row})"
                )
                return None  # Skip this row entirely
        
            # Not a duplicate - add normalized name to tracking set
            normalized_name = self.normalize_name_key(cleaned_row['Name'])
            self.seen_names.add(normalized_name)
        
            # PHASE 4: UNIT OF MEASURE NORMALIZATION (After Title Case and de-duplication)
            # Note: UnitOfMeasure already has Title Case applied
            original_unit = cleaned_row['UnitOfMeasure']
            cleaned_row['UnitOfMeasure'] = self.normalize_unit_of_measure(
                original_unit, cleaned_row['Name'], row_index
            )
        
            # PHASE 5: INTELLIGENT SUB-ACCOUNT NORMALIZATION (After Title Case)
            # Note: Sub-account fields already have Title Case applied
            cleaned_row = self.handle_empty_sub_accounts(cleaned_row, row_index)
        
            # PHASE 6: DEFAULT VALUE APPLICATION
            # Handle VAT Type
            cleaned_row['VATType'] = self.clean_vat_type(cleaned_row['VATType'], row_index)
        
            # Handle Item Class
            if not cleaned_row['ItemClass'] or cleaned_row['ItemClass'].strip() == '':
                cleaned_row['ItemClass'] = self.user_defaults['default_item_class']
                self.report['defaults_used'].append(
                    f"Row {row_index}: Empty ItemClass replaced with default '{self.user_defaults['default_item_class']}'"
                )
        
            # Handle Item Category
            if not cleaned_row['ItemCategory'] or cleaned_row['ItemCategory'].strip() == '':
                cleaned_row['ItemCategory'] = self.user_defaults['default_item_category']
                self.report['defaults_used'].append(
                    f"Row {row_index}: Empty ItemCategory replaced with default '{self.user_defaults['default_item_category']}'"
                )
        
            # PHASE 7: VALIDATION
            # Numeric fields
            unit_cost, valid = self.validate_numeric(row.get('UnitCost', ''), 'UnitCost', row_index)
            if not valid:
                return None  # Numeric validation failures are critical - skip row
            cleaned_row['UnitCost'] = unit_cost or 0.0
        
            total_qty, valid = self.validate_numeric(row.get('TotalQuantity', ''), 'TotalQuantity', row_index)
            if not valid:
                return None  # Numeric validation failures are critical - skip row
            cleaned_row['TotalQuantity'] = total_qty or 0
        
            unit_price, valid = self.validate_numeric(row.get('UnitPrice', ''), 'UnitPrice', row_index)
            if not valid:
                return None  # Numeric validation failures are critical - skip row
            cleaned_row['UnitPrice'] = unit_price or 0.0
        
            # Handle ReorderLevel with default
            cleaned_row['ReorderLevel'] = self.handle_reorder_level(
                row.get('ReorderLevel', ''), row_index
            )
        
            # Handle Expiry Date - FIXED: Don't skip entire row on invalid date format
            expiry_date, valid = self.handle_expiry_date(
                cleaned_row.get('ExpiryDate', ''), row_index
            )
            if not valid:
                # Instead of skipping row, use default expiry date
                try:
                    default_dt = datetime.strptime(self.user_defaults['default_expiry_date'], '%d/%m/%Y')
                    if default_dt > datetime.now():
                        expiry_date = self.user_defaults['default_expiry_date']
                        self.report['defaults_used'].append(
                            f"Row {row_index}: Invalid expiry date format replaced with default '{expiry_date}'"
                        )
                    else:
                        # Compute future date (1 year from today)
                        future_date = (datetime.now() + timedelta(days=365)).strftime('%d/%m/%Y')
                        expiry_date = future_date
                        self.report['defaults_used'].append(
                            f"Row {row_index}: Invalid expiry date format replaced with computed future date '{expiry_date}'"
                        )
                except ValueError:
                    # Even default is invalid, compute future date
                    future_date = (datetime.now() + timedelta(days=365)).strftime('%d/%m/%Y')
                    expiry_date = future_date
                    self.report['defaults_used'].append(
                        f"Row {row_index}: Invalid expiry date format replaced with computed future date '{expiry_date}'"
                    )
        
            cleaned_row['ExpiryDate'] = expiry_date
        
            # Copy remaining fields
            cleaned_row['Batch'] = cleaned_row.get('Batch', '').strip()
            cleaned_row['ItemCode'] = str(cleaned_row.get('ItemCode', '')).strip()
            cleaned_row['Barcode'] = str(cleaned_row.get('Barcode', '')).strip()

            return cleaned_row

        except Exception as e:
            self.report['errors'].append(f"Row {row_index}: Error cleaning row - {str(e)}")
            import traceback
            self.report['errors'].append(f"Row {row_index}: Traceback - {traceback.format_exc()}")
            return None
    
    def process(self) -> Tuple[bool, str]:
        """Main processing method"""
        try:
            # Validate defaults first
            self.validate_defaults()
            
            # Read input CSV
            # with open(self.csv_path, 'r', encoding='utf-8') as f:
            with open(self.csv_path, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                
                # Validate required columns
                missing_cols = [col for col in self.REQUIRED_COLUMNS if col not in reader.fieldnames]
                if missing_cols:
                    raise ValueError(f"Missing required columns: {', '.join(missing_cols)}")
                
                # Reset tracking sets for new processing run
                self.seen_names.clear()
                
                # Process each row with strict ordering
                rows_processed = 0
                for i, row in enumerate(reader, 1):
                    # Skip empty rows (all values are empty or whitespace)
                    if all(str(value).strip() == '' for value in row.values()):
                        continue # Skip completely empty rows    
                    cleaned = self.clean_row(row, i)
                    if cleaned:
                        self.cleaned_data.append(cleaned)
                    rows_processed += 1

                print(f"Total non-empty rows processed: {rows_processed}")
                print(f"Rows successfully cleaned: {len(self.cleaned_data)}")

            # Generate output filename
            input_path = Path(self.csv_path)
            output_path = input_path.parent / f"{input_path.stem}_cleaned{input_path.suffix}"
            
            # Write cleaned data
            with open(output_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=self.REQUIRED_COLUMNS)
                writer.writeheader()
                writer.writerows(self.cleaned_data)
            
            # Generate report
            report_path = input_path.parent / f"{input_path.stem}_cleanup_report.txt"
            self.generate_report(report_path)
            
            return True, str(output_path)
            
        except Exception as e:
            self.report['errors'].append(f"Processing failed: {str(e)}")
            import traceback
            self.report['errors'].append(f"Traceback: {traceback.format_exc()}")
            self.generate_report(Path(self.csv_path).parent / "cleanup_error_report.txt")
            return False, str(e)
    
    def generate_report(self, report_path: Path):
        """Generate comprehensive cleanup report with duplicates section"""
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write("MEDICENTRE v3 INVENTORY DATA CLEANUP REPORT\n")
            f.write("=" * 80 + "\n\n")
            
            f.write(f"Input File: {self.csv_path}\n")
            f.write(f"Processed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Rows Processed: {len(self.cleaned_data)}\n")
            f.write(f"Rows Skipped: {len([e for e in self.report['errors'] if 'Row' in e])}\n")
            f.write(f"Duplicates Removed: {len(self.report['duplicates_removed'])}\n\n")
            
            f.write("DEFAULTS CONFIGURED:\n")
            f.write("-" * 80 + "\n")
            for key, value in self.user_defaults.items():
                if key.startswith('default_'):
                    f.write(f"• {key}: {value}\n")
            f.write("\n")
            
            f.write("CANONICAL UNITS RECOGNIZED:\n")
            f.write("-" * 80 + "\n")
            for unit in sorted(self.CANONICAL_UNITS):
                f.write(f"• {unit}\n")
            f.write("\n")
            
            f.write("DUPLICATES REMOVED:\n")
            f.write("-" * 80 + "\n")
            for item in self.report['duplicates_removed']:
                f.write(f"• {item}\n")
            if not self.report['duplicates_removed']:
                f.write("No duplicates found.\n")
            f.write("\n")
            
            f.write("DEFAULTS USED:\n")
            f.write("-" * 80 + "\n")
            for item in self.report['defaults_used']:
                f.write(f"• {item}\n")
            if not self.report['defaults_used']:
                f.write("No defaults were used.\n")
            f.write("\n")
            
            f.write("NORMALIZATIONS APPLIED:\n")
            f.write("-" * 80 + "\n")
            for item in self.report['normalizations']:
                f.write(f"• {item}\n")
            if not self.report['normalizations']:
                f.write("No normalizations were needed.\n")
            f.write("\n")
            
            f.write("USER DECISIONS (Interactive Resolutions):\n")
            f.write("-" * 80 + "\n")
            for item in self.report['user_decisions']:
                f.write(f"• {item}\n")
            if not self.report['user_decisions']:
                f.write("No user interventions were required.\n")
            f.write("\n")
            
            f.write("UNIT OF MEASURE RESOLUTIONS:\n")
            f.write("-" * 80 + "\n")
            for unit, resolution in self.unit_resolutions.items():
                f.write(f"• '{unit}' → '{resolution}'\n")
            if not self.unit_resolutions:
                f.write("No unit of measure resolutions were made.\n")
            f.write("\n")
            
            f.write("SUB-ACCOUNT NORMALIZATIONS SUMMARY:\n")
            f.write("-" * 80 + "\n")
            # Count sub-account normalizations
            sub_account_norms = [n for n in self.report['normalizations'] if 'SubAccount' in n]
            f.write(f"Total sub-account normalizations: {len(sub_account_norms)}\n")
            for norm in sub_account_norms:
                if 'AssetSubAccount' in norm:
                    f.write(f"  • Asset: {norm.split(': ')[1] if ': ' in norm else norm}\n")
                elif 'RevenueSubAccount' in norm:
                    f.write(f"  • Revenue: {norm.split(': ')[1] if ': ' in norm else norm}\n")
                elif 'CostOfSaleSubAccount' in norm:
                    f.write(f"  • Cost: {norm.split(': ')[1] if ': ' in norm else norm}\n")
            f.write("\n")
            
            f.write("WARNINGS:\n")
            f.write("-" * 80 + "\n")
            for item in self.report['warnings']:
                f.write(f"⚠ {item}\n")
            if not self.report['warnings']:
                f.write("No warnings.\n")
            f.write("\n")
            
            f.write("ERRORS:\n")
            f.write("-" * 80 + "\n")
            for item in self.report['errors']:
                f.write(f"✗ {item}\n")
            if not self.report['errors']:
                f.write("No errors.\n")
            
            f.write("\n" + "=" * 80 + "\n")
            f.write("CLEANING STATISTICS:\n")
            f.write("-" * 80 + "\n")
            total_rows = len(self.cleaned_data) + len([e for e in self.report['errors'] if 'Row' in e]) + len(self.report['duplicates_removed'])
            f.write(f"Total rows in input: {total_rows}\n")
            f.write(f"Rows successfully cleaned: {len(self.cleaned_data)}\n")
            f.write(f"Duplicates removed: {len(self.report['duplicates_removed'])}\n")
            f.write(f"Rows with errors: {len([e for e in self.report['errors'] if 'Row' in e])}\n")
            f.write(f"Defaults applied: {len(self.report['defaults_used'])}\n")
            f.write(f"Normalizations: {len(self.report['normalizations'])}\n")
            f.write(f"User decisions: {len(self.report['user_decisions'])}\n")
            f.write(f"Warnings: {len(self.report['warnings'])}\n")
            f.write(f"Errors: {len(self.report['errors'])}\n")
            
            # Sub-account statistics
            sub_account_norms = [n for n in self.report['normalizations'] if 'SubAccount' in n]
            f.write(f"Sub-account normalizations: {len(sub_account_norms)}\n")
            
            # De-duplication summary
            f.write("\n" + "=" * 80 + "\n")
            f.write("DE-DUPLICATION SUMMARY:\n")
            f.write("-" * 80 + "\n")
            f.write(f"Unique products after de-duplication: {len(self.cleaned_data)}\n")
            f.write(f"Duplicate products removed: {len(self.report['duplicates_removed'])}\n")
            if total_rows > 0:
                f.write(f"De-duplication efficiency: {len(self.report['duplicates_removed'])/total_rows*100:.1f}%\n")
            else:
                f.write(f"De-duplication efficiency: N/A (no rows processed)\n")

            f.write("\n" + "=" * 80 + "\n")
            f.write("END OF REPORT\n")


def run_data_cleaner():
    """Main function to run the data cleaner interactively"""
    print("=== Medicentre v3 Inventory Data Cleaner ===\n")
    print("ENHANCED VERSION WITH NAME DE-DUPLICATION & INTELLIGENT SUB-ACCOUNT NORMALIZATION\n")
    print("Processing Order:")
    print("1. Title Case normalization (Name, UnitOfMeasure, Accounts, Classes, Categories)")
    print("2. Name cleaning (comma removal, spacing)")
    print("3. DE-DUPLICATION - Remove duplicate product names")
    print("4. Unit of measure normalization")
    print("5. INTELLIGENT SUB-ACCOUNT NORMALIZATION - Enforce default naming conventions")
    print("6. Default value application")
    print("7. Validation (numeric, dates)\n")
    
    # Get input file
    csv_path = input("Enter path to CSV file: ").strip()
    if not Path(csv_path).exists():
        print(f"Error: File '{csv_path}' not found.")
        return
    
    # Get user defaults
    print("\n" + "="*60)
    print("ENTER DEFAULTS FOR MISSING VALUES")
    print("="*60)
    print("IMPORTANT: Sub-account defaults will be used as authoritative references.")
    print("Variations similar to these defaults will be normalized to exact matches.\n")
    
    user_defaults = {
        'default_vat_type': input("Default VAT Type (e.g., 'VAT Exempt'): ").strip(),
        'default_item_class': input("Default Item Class (e.g., 'Product'): ").strip(),
        'default_item_category': input("Default Item Category (e.g., 'Pharmacy Drugs'): ").strip(),
        'default_unit_of_measure': input("Default Unit of Measure (e.g., 'Pack'): ").strip(),
        'default_expiry_date': input("Default Expiry Date (dd/mm/yyyy): ").strip(),
        'default_reorder_level': input("Default Reorder Level (integer, e.g., 10): ").strip() or '10',
        'default_asset_account': input("Default Asset Sub-Account (e.g., 'Inventory - Pharmacy Drugs'): ").strip() or 'Inventory - Pharmacy Drugs',
        'default_revenue_account': input("Default Revenue Sub-Account (e.g., 'Sales - Pharmacy Drugs'): ").strip() or 'Sales - Pharmacy Drugs',
        'default_cost_account': input("Default Cost of Sale Sub-Account (e.g., 'Cost Of Goods Sold - Pharmacy Drugs'): ").strip() or 'Cost Of Goods Sold - Pharmacy Drugs'
    }
    
    print("\n" + "="*60)
    print("STARTING DATA CLEANING PROCESS...")
    print("="*60)
    print("Features enabled:")
    print("✓ Product name de-duplication")
    print("✓ Intelligent sub-account normalization")
    print("✓ Similarity-based matching (tolerant to minor variations)")
    print("\nNote: Duplicate product names will be automatically removed.")
    print("      Sub-accounts will be normalized to match configured defaults.\n")
    
    # Create cleaner and process
    cleaner = InventoryDataCleaner(csv_path, user_defaults)
    success, result = cleaner.process()
    
    if success:
        print(f"\n" + "="*60)
        print("✓ CLEANUP COMPLETED SUCCESSFULLY!")
        print("="*60)
        print(f"Cleaned file: {result}")
        print(f"Report generated: {Path(csv_path).parent / (Path(csv_path).stem + '_cleanup_report.txt')}")
        print(f"\nSummary:")
        print(f"  Total rows processed: {len(cleaner.cleaned_data) + len(cleaner.report['duplicates_removed']) + len([e for e in cleaner.report['errors'] if 'Row' in e])}")
        print(f"  Unique products retained: {len(cleaner.cleaned_data)}")
        print(f"  Duplicates removed: {len(cleaner.report['duplicates_removed'])}")
        print(f"  Defaults applied: {len(cleaner.report['defaults_used'])}")
        print(f"  Normalizations: {len(cleaner.report['normalizations'])}")
        print(f"  Sub-account normalizations: {len([n for n in cleaner.report['normalizations'] if 'SubAccount' in n])}")
        print(f"  User decisions: {len(cleaner.report['user_decisions'])}")
        print(f"  Warnings: {len(cleaner.report['warnings'])}")
        print(f"  Errors: {len(cleaner.report['errors'])}")
    else:
        print(f"\n✗ CLEANUP FAILED: {result}")
        print(f"Error report: {Path(csv_path).parent / 'cleanup_error_report.txt'}")


if __name__ == "__main__":
    run_data_cleaner()