import csv
from logging import config
import time
import logging
import json
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (NoSuchElementException)
from datetime import datetime
from config_loader import ConfigLoader
import json


class MedicentreV3InventoryImporter:
    """Enhanced Medicentre v3 Inventory Importer with robust prerequisite verification"""

    def __init__(
    self, base_url: str, credentials: Dict, config: Dict, dry_run: bool = False
):
        """Initialize enhanced importer
    
        Args:
            base_url: Medicentre v3 base URL
            credentials: Dictionary with accesscode, username, password, branch
            config: Configuration dictionary with all settings
            dry_run: If True, only validate without importing
        """
        self.base_url = base_url.rstrip("/")
        self.credentials = credentials
        self.config = config
        self.dry_run = dry_run
        self.driver = None
        self.wait = None
        self.logger = self.setup_logging()
        self.session_active = False

        # Validate credentials
        required_credentials = ['accesscode', 'branch', 'username', 'password']
        missing_creds = [cred for cred in required_credentials if not self.credentials.get(cred)]
        if missing_creds:
            self.logger.warning(f"Missing credentials: {missing_creds}")

        # Store account mappings from config with validation
        default_mappings = {
            'inventory_main': 'Inventory',
            'inventory_class': 'Current Assets',
            'revenue_main': 'Revenue',
            'revenue_class': 'Income',
            'cost_main': 'Cost of Goods Sold',
            'cost_class': 'Cost of Goods Sold'
        }
    
        self.account_mappings = config.get("account_mappings", {})
        # Fill in any missing keys with defaults
        for key, default_value in default_mappings.items():
            if key not in self.account_mappings or not self.account_mappings[key]:
                self.account_mappings[key] = default_value
                self.logger.info(f"Using default for {key}: {default_value}")

        # Store VAT defaults
        self.vat_default_rate = config.get("vat_default_rate", 16)
        self.vat_default_tax_code = config.get("vat_default_tax_code", "E")
    
        # Store storage location
        if "storage_location" not in config or not config["storage_location"]:
            self.logger.warning("storage_location not in config, using default")
            config["storage_location"] = "Main Store"

        self.verification_stats = {
            "accounts_verified": 0,
            "accounts_created": 0,
            "vat_verified": 0,
            "vat_errors": 0,
            "units_verified": 0,
            "units_created": 0,
            "categories_verified": 0,
            "categories_created": 0,
            "classes_verified": 0,
            "classes_created": 0,
            "items_imported": 0,
            "items_failed": 0,
            "items_skipped": 0,
        }

    def setup_logging(self):
        """Setup comprehensive logging configuration"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)

        log_file = log_dir / f"medicentre_import_{timestamp}.log"

        logger = logging.getLogger("MedicentreImporter")
        logger.setLevel(logging.INFO)

        # Remove existing handlers to avoid duplicates
        if logger.hasHandlers():
            logger.handlers.clear()

        # File handler
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        file_handler.setFormatter(file_formatter)

        # Console handler
        console_handler = logging.StreamHandler()
        console_formatter = logging.Formatter(
            "%(asctime)s - %(levelname)s - %(message)s"
        )
        console_handler.setFormatter(console_formatter)

        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

        # Screenshot directory
        self.screenshot_dir = log_dir / "screenshots"
        self.screenshot_dir.mkdir(exist_ok=True)

        return logger

    def take_screenshot(self, name: str):
        """Take screenshot and save to logs directory"""
        if self.driver:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            screenshot_path = self.screenshot_dir / f"{name}_{timestamp}.png"
            self.driver.save_screenshot(str(screenshot_path))
            self.logger.info(f"Screenshot saved: {screenshot_path}")

    def setup_driver(self):
        """Initialize Chrome driver with options"""
        options = webdriver.EdgeOptions()
        if self.config.get("headless", False):
            options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-notifications")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")

        self.driver = webdriver.Edge(options=options)
        self.driver.maximize_window()
        self.wait = WebDriverWait(self.driver, 30)
        self.logger.info("Browser driver initialized")

    def login(self) -> bool:
        """Login to Medicentre v3"""
        try:
            self.logger.info("Initializing browser and logging in...")
            self.setup_driver()

            # Navigate to login page
            self.logger.info(f"Navigating to {self.base_url}")
            self.driver.get(self.base_url)
            time.sleep(2)

            # Enter access code (FIRST STEP)
            accesscode_field = self.wait.until(
                EC.presence_of_element_located((By.ID, "hospCode"))
            )
            accesscode_proceed_button = self.wait.until(
                EC.element_to_be_clickable((By.ID, "btnProceed"))
            )

            accesscode_field.send_keys(self.credentials["accesscode"])
            accesscode_proceed_button.click()
            time.sleep(2)

            # Select branch (SECOND STEP - after access code)
            branch_select = Select(self.driver.find_element(By.ID, "CompanyBranchID"))
            branch_select.select_by_visible_text(self.credentials["branch"])
            time.sleep(1)

            # Enter username and password (THIRD STEP)
            username_field = self.driver.find_element(By.ID, "userName")
            password_field = self.driver.find_element(By.ID, "userPassword")
            login_button = self.driver.find_element(By.ID, "btnLogin")

            username_field.send_keys(self.credentials["username"])
            password_field.send_keys(self.credentials["password"])
            login_button.click()

            # Wait for successful login
            self.wait.until(
                EC.presence_of_element_located(
                    (By.XPATH, "//h5[normalize-space()='My Appointments']")
                )
            )

            self.session_active = True
            self.logger.info("✓ Login successful")
            return True

        except Exception as e:
            self.logger.error(f"✗ Login failed: {str(e)}")
            self.take_screenshot("login_error")
            if self.driver:
                self.driver.quit()
            return False

    def check_session(self) -> bool:
        """Check if session is still active, re-login if needed"""
        if not self.session_active:
            return self.login()

        try:
            # Check for common session timeout indicators
            self.driver.find_element(
                By.XPATH, "//h5[contains(text(), 'My Appointments')]"
            )
            return True
        except:
            self.logger.warning(
                "Session appears to have expired, attempting to re-login..."
            )
            self.session_active = False
            if self.driver:
                self.driver.quit()
                self.driver = None
            return self.login()

    # def navigate_to_module(self, module_path: List[str]) -> bool:
    #     """Navigate through menu hierarchy to target module"""
    #     try:
    #         if not self.check_session():
    #             return False

    #         self.logger.info(f"Navigating to: {' → '.join(module_path)}")

    #         # Handle specific navigation based on target module
    #         if module_path == ["Inventory", "Inventory"]:
    #             return self.navigate_to_inventory_items()
    #         elif module_path == ["Inventory", "Inventory Setup", "Item Categories"]:
    #             return self.navigate_to_item_categories()
    #         elif module_path == ["Inventory", "Inventory Setup", "Item Classes"]:
    #             return self.navigate_to_item_classes()
    #         elif module_path == ["Inventory", "Unit of Measure"]:
    #             return self.navigate_to_unit_of_measure()
    #         elif module_path == ["Accounts", "Chart of Accounts"]:
    #             return self.navigate_to_chart_of_accounts()
    #         elif module_path == ["Accounts", "Taxes"]:
    #             return self.navigate_to_taxes()
    #         else:
    #             self.logger.error(f"Unknown module path: {module_path}")
    #             return False

    #     except Exception as e:
    #         self.logger.error(f"✗ Navigation failed to {module_path}: {str(e)}")
    #         self.take_screenshot(f"navigation_error_{'_'.join(module_path)}")
    #         return False

    # ==================== CHART OF ACCOUNTS PANEL ====================

    def navigate_to_chart_of_accounts(self) -> bool:
        """Navigate to Chart of Accounts panel and perform all actions there"""
        try:
            # Expand Accounts module first
            accounts_module = self.wait.until(
                EC.element_to_be_clickable(
                    (By.XPATH, "//a[normalize-space()='Accounts']")
                )
            )
            accounts_module.click()
            time.sleep(1)

            # Click Ledger Accounts
            coa_link = self.wait.until(
                EC.element_to_be_clickable(
                    (By.XPATH, "//a[normalize-space()='Ledger Accounts']")
                )
            )
            coa_link.click()
            time.sleep(3)  # Wait for page to fully load

            # Verify we're on the right page
            try:
                self.driver.find_element(By.XPATH, "//h6[normalize-space()='View: Accounts']")
                self.driver.find_element(By.XPATH, "//h6[normalize-space()='View: Sub-Accounts ()']")
                self.logger.info("✓ Successfully navigated to Chart of Accounts")
                return True
            except:
                self.logger.error("Chart of Accounts page elements not found")
                return False

        except Exception as e:
            self.logger.error(f"Navigation to Chart of Accounts failed: {str(e)}")
            return False
        
    def search_and_select_main_account(self, account_name: str) -> bool:
        """Search for a main account and select it if found"""
        try:
            self.logger.info(f"Searching for main account: '{account_name}'")
        
            # Find the main accounts search box
            main_search_box = self.driver.find_element(
                By.XPATH, "//input[@aria-controls='accountstable']"
            )
        
            # Clear and search
            main_search_box.clear()
            main_search_box.send_keys(account_name)
            main_search_box.send_keys(Keys.RETURN)
            time.sleep(2)
        
            # Get all rows in the main accounts table
            try:
                main_table = self.driver.find_element(By.XPATH, "//table[@id='accountstable']")
                rows = main_table.find_elements(By.XPATH, "//table[@id='accountstable']/tbody/tr")
            
                if not rows:
                    # Try alternative table selector
                    rows = self.driver.find_elements(By.XPATH, "//table[contains(@class, 'dataTable')]//tbody/tr")
        
            except:
                # If table not found, try general table rows
                rows = self.driver.find_elements(By.XPATH, "(//table//tbody/tr)[1]//tr")
        
            # Look for the account in the rows
            account_found = False
            for row in rows:
                try:
                    cells = row.find_elements(By.TAG_NAME, "td")
                    if cells:
                        # Check second column for account name (assuming: ID, Name, ...)
                        cell_text = cells[1].text.strip() if len(cells) > 1 else cells[0].text.strip()
                    
                        if cell_text.lower() == account_name.lower():
                            # Found the account, click to select it
                            row.click()
                            self.logger.info(f"✓ Selected main account: '{account_name}'")
                            time.sleep(2)
                            account_found = True
                            break
                        
                except Exception as e:
                    self.logger.debug(f"Error checking row: {e}")
                    continue
        
            # Clear search
            main_search_box.clear()
            main_search_box.send_keys(Keys.RETURN)
            time.sleep(1)
        
            if not account_found:
                self.logger.warning(f"Main account '{account_name}' not found in table")
                return False
            
            return True

        except Exception as e:
            self.logger.error(f"Error searching for main account '{account_name}': {str(e)}")
            return False

    def verify_and_create_accounts_in_panel(self, csv_data: List[Dict]) -> bool:
        """Verify and create ledger accounts in hierarchical structure"""
        try:
            if not self.navigate_to_chart_of_accounts():
                return False

            self.logger.info("=== Verifying Ledger Accounts in Hierarchical Panel ===")
    
            # Extract unique sub-accounts from CSV
            asset_sub_accounts = {row['AssetSubAccount'].strip() for row in csv_data if row.get('AssetSubAccount', '').strip()}
            revenue_sub_accounts = {row['RevenueSubAccount'].strip() for row in csv_data if row.get('RevenueSubAccount', '').strip()}
            cost_sub_accounts = {row['CostOfSaleSubAccount'].strip() for row in csv_data if row.get('CostOfSaleSubAccount', '').strip()}
    
            self.logger.info(f"Found {len(asset_sub_accounts)} asset sub-accounts")
            self.logger.info(f"Found {len(revenue_sub_accounts)} revenue sub-accounts")
            self.logger.info(f"Found {len(cost_sub_accounts)} cost sub-accounts")
    
            # Get user configuration for main accounts
            if not self.dry_run:
                main_account_config = self.get_main_account_configuration()
            else:
                main_account_config = self.get_default_main_account_config()
    
            accounts_verified = 0
            accounts_created = 0
    
            # Process Asset Sub-Accounts (under Inventory main account)
            if asset_sub_accounts:
                self.logger.info(f"\nProcessing {len(asset_sub_accounts)} Asset Sub-Accounts...")
        
                # Get or configure Inventory main account
                inventory_main = main_account_config.get('inventory_main')
                inventory_class = main_account_config.get('inventory_class', 'Current Assets')
        
                # Verify/Create Inventory main account
                if not self.verify_or_create_main_account(inventory_main, inventory_class):
                    self.logger.error(f"Failed with Inventory main account: {inventory_main}")
                    return False
        
                # Process sub-accounts under Inventory
                sub_accounts_created = self.verify_and_create_sub_accounts(inventory_main, asset_sub_accounts)
                if sub_accounts_created is None:
                    self.logger.error(f"Failed with sub-accounts for Inventory")
                    return False
            
                accounts_created += sub_accounts_created
                accounts_verified += len(asset_sub_accounts) - sub_accounts_created
    
            # Process Revenue Sub-Accounts (under Revenue main account)
            if revenue_sub_accounts:
                self.logger.info(f"\nProcessing {len(revenue_sub_accounts)} Revenue Sub-Accounts...")
        
                # Get or configure Revenue main account
                revenue_main = main_account_config.get('revenue_main')
                revenue_class = main_account_config.get('revenue_class', 'Revenue')
        
                # Verify/Create Revenue main account
                if not self.verify_or_create_main_account(revenue_main, revenue_class):
                    self.logger.error(f"Failed with Revenue main account: {revenue_main}")
                    return False
        
                # Process sub-accounts under Revenue
                sub_accounts_created = self.verify_and_create_sub_accounts(revenue_main, revenue_sub_accounts)
                if sub_accounts_created is None:
                    self.logger.error(f"Failed with sub-accounts for Revenue")
                    return False
            
                accounts_created += sub_accounts_created
                accounts_verified += len(revenue_sub_accounts) - sub_accounts_created
    
            # Process Cost of Sales Sub-Accounts (under Cost of Sales main account)
            if cost_sub_accounts:
                self.logger.info(f"\nProcessing {len(cost_sub_accounts)} Cost of Sales Sub-Accounts...")
        
                # Get or configure Cost of Sales main account
                cost_main = main_account_config.get('cost_main')
                cost_class = main_account_config.get('cost_class', 'Cost of Sales')
        
                # Verify/Create Cost of Sales main account
                if not self.verify_or_create_main_account(cost_main, cost_class):
                    self.logger.error(f"Failed with Cost of Sales main account: {cost_main}")
                    return False
        
                # Process sub-accounts under Cost of Sales
                sub_accounts_created = self.verify_and_create_sub_accounts(cost_main, cost_sub_accounts)
                if sub_accounts_created is None:
                    self.logger.error(f"Failed with sub-accounts for Cost of Sales")
                    return False
            
                accounts_created += sub_accounts_created
                accounts_verified += len(cost_sub_accounts) - sub_accounts_created
    
            self.verification_stats['accounts_verified'] = accounts_verified
            self.verification_stats['accounts_created'] = accounts_created
    
            self.logger.info(f"✓ Ledger Accounts verification complete: {accounts_verified} verified, {accounts_created} created")
            return True
    
        except Exception as e:
            self.logger.error(f"✗ Ledger Accounts verification failed: {str(e)}")
            self.take_screenshot("chart_of_accounts_verification_error")
            return False

    def verify_or_create_main_account(self, account_name: str, account_class: str) -> bool:
        """Verify if a main account exists, create if missing"""
        try:
            self.logger.info(f"Checking main account: {account_name} ({account_class})")
        
            # First, try to search and select the account
            if self.search_and_select_main_account(account_name):
                self.logger.info(f"✓ Main account '{account_name}' already exists")
                return True
        
            # Account doesn't exist, create it
            if not self.dry_run:
                self.logger.info(f"Creating main account: {account_name}")
            
                # Make sure we're on the main accounts tab
                try:
                    self.driver.find_element(By.XPATH, "//input[@id='Account_Name']")
                except:
                    # Click on main accounts tab if needed
                    try:
                        main_accounts_tab = self.driver.find_element(
                            By.XPATH, "//a[normalize-space()='Ledger Accounts']"
                        )
                        main_accounts_tab.click()
                        time.sleep(2)
                    except:
                        pass
            
                # Fill account name
                account_name_field = self.driver.find_element(
                    By.XPATH, "//input[@id='Account_Name']"
                )
                account_name_field.clear()
                account_name_field.send_keys(account_name)
        
                # Select account class
                try:
                    account_class_select = Select(self.driver.find_element(
                        By.XPATH, "//select[@id='Account_AccountClassID']"
                    ))
                    try:
                        account_class_select.select_by_visible_text(account_class)
                    except:
                        # Try to find similar class
                        for option in account_class_select.options:
                            if account_class.lower() in option.text.lower():
                                account_class_select.select_by_visible_text(option.text)
                                self.logger.info(f"Selected account class (similar): {option.text}")
                                break
                        else:
                            # Select first available option
                            account_class_select.select_by_index(1)
                except Exception as e:
                    self.logger.warning(f"Could not set account class: {e}")
                    # Continue anyway
        
                # Click add button
                new_account_button = self.driver.find_element(
                    By.XPATH, "//button[@id='btnaddaccount']"
                )
                new_account_button.click()
                time.sleep(3)
        
                # Verify account was created by searching for it
                if self.search_and_select_main_account(account_name):
                    self.logger.info(f"✓ Created main account: {account_name}")
                    return True
                else:
                    self.logger.error(f"✗ Failed to verify creation of main account: {account_name}")
                    return False
            
            else:
                self.logger.info(f"✓ Would create main account: {account_name} (dry run)")
                return True  # In dry run, assume success
            
        except Exception as e:
            self.logger.error(f"Error verifying/creating main account '{account_name}': {str(e)}")
            self.take_screenshot(f"main_account_error_{account_name}")
            return False

    def verify_and_create_sub_accounts(self, main_account_name: str, sub_account_names: Set[str]) -> Optional[int]:
        """Verify and create sub-accounts for a given main account"""
        try:
            self.logger.info(f"Processing sub-accounts for '{main_account_name}'...")
        
            # First, select the main account
            if not self.search_and_select_main_account(main_account_name):
                self.logger.error(f"Could not select main account '{main_account_name}'")
                return None
        
            sub_accounts_created = 0
        
            # Find the sub-accounts table search box
            sub_search_box = self.driver.find_element(
                By.XPATH, "//input[@aria-controls='subaccountstable']"
            )
        
            for sub_account_name in sub_account_names:
                self.logger.info(f"Checking sub-account: '{sub_account_name}'")
            
                # Search for sub-account
                sub_search_box.clear()
                sub_search_box.send_keys(sub_account_name)
                sub_search_box.send_keys(Keys.RETURN)
                time.sleep(2)
            
                # Check if sub-account exists in the table
                sub_account_exists = False
                try:
                    # Get sub-accounts table
                    sub_table = self.driver.find_element(By.XPATH, "//table[@id='subaccountstable']")
                    rows = sub_table.find_elements(By.XPATH, "//table[@id='subaccountstable']/tbody/tr")
                
                    for row in rows:
                        try:
                            cells = row.find_elements(By.TAG_NAME, "td")
                            if cells:
                                # Check second column for sub-account name
                                cell_text = cells[1].text.strip()
                                if cell_text.lower() == sub_account_name.lower():
                                    sub_account_exists = True
                                    self.logger.info(f"✓ Sub-account '{sub_account_name}' already exists")
                                    break
                        except:
                            continue

                except Exception as e:
                    self.logger.debug(f"Error checking sub-account table: {e}")
            
                # Clear search
                sub_search_box.clear()
                sub_search_box.send_keys(Keys.RETURN)
                time.sleep(1)
            
                if sub_account_exists:
                    continue
            
                # Sub-account doesn't exist, create it
                if not self.dry_run:
                    self.logger.info(f"Creating sub-account: '{sub_account_name}'")

                    # Fill sub-account name
                    sub_account_name_field = self.driver.find_element(
                        By.XPATH, "//input[@id='SubAccount_Name']"
                    )
                    sub_account_name_field.clear()
                    sub_account_name_field.send_keys(sub_account_name)
                
                    # Verify main account is selected (should be auto-selected)
                    try:
                        parent_account_field = self.driver.find_element(
                            By.XPATH, "//input[@id='Account_Name']"
                        )
                        current_value = parent_account_field.get_attribute("value")
                        if current_value.lower() != main_account_name.lower():
                            self.logger.warning(f"Parent account mismatch: {current_value} != {main_account_name}")
                    except:
                        pass
                
                    # Click add button
                    add_button = self.driver.find_element(
                        By.XPATH, "//button[@id='btnaddsubaccount']"
                    )
                    add_button.click()
                    time.sleep(2)
                
                    # Verify creation by searching again
                    sub_search_box.clear()
                    sub_search_box.send_keys(sub_account_name)
                    sub_search_box.send_keys(Keys.RETURN)
                    time.sleep(2)
                
                    # Check if it appears
                    try:
                        sub_table = self.driver.find_element(By.XPATH, "//table[@id='subaccountstable']")
                        rows = sub_table.find_elements(By.XPATH, "//table[@id='subaccountstable']/tbody/tr")
                    
                        created = False
                        for row in rows:
                            try:
                                cells = row.find_elements(By.TAG_NAME, "td")
                                if cells:
                                    cell_text = cells[0].text.strip()
                                    if cell_text.lower() == sub_account_name.lower():
                                        created = True
                                        break
                            except:
                                continue
                    
                        if created:
                            self.logger.info(f"✓ Created sub-account: '{sub_account_name}'")
                            sub_accounts_created += 1
                        else:
                            self.logger.error(f"✗ Failed to verify creation of sub-account: '{sub_account_name}'")
                            return None
                        
                    except Exception as e:
                        self.logger.error(f"Error verifying sub-account creation: {e}")
                        return None
                
                    # Clear search for next iteration
                    sub_search_box.clear()
                    sub_search_box.send_keys(Keys.RETURN)
                    time.sleep(1)
                
                else:
                    self.logger.info(f"✓ Would create sub-account: '{sub_account_name}' (dry run)")
                    sub_accounts_created += 1
        
            self.logger.info(f"Created {sub_accounts_created} sub-accounts for '{main_account_name}'")
            return sub_accounts_created
        
        except Exception as e:
            self.logger.error(f"Error in sub-account processing for '{main_account_name}': {str(e)}")
            self.take_screenshot(f"sub_accounts_error_{main_account_name}")
            return None

    def get_main_account_configuration(self) -> Dict:
        """Get user configuration for main accounts from config or prompt"""
        print("\n" + "="*60)
        print("MAIN ACCOUNT CONFIGURATION")
        print("="*60)
    
        # Check if we have account mappings in config
        if self.account_mappings and all(self.account_mappings.values()):
            print("\nUsing account mappings from configuration:")
            for key, value in self.account_mappings.items():
                print(f"  {key}: {value}")
        
            confirm = input("\nUse these account mappings? (y/n): ").strip().lower()
            if confirm in ['y', 'yes']:
                return self.account_mappings
    
        # If no config or user wants to change, proceed with interactive setup
        print("\nThe CSV contains sub-accounts that need to be mapped to main accounts.")
        print("\nYou need to specify which existing main accounts these sub-accounts")
        print("should be created under, or we can create new main accounts.")
        print("="*60)
    
        while True:
            print("\nWould you like to:")
            print("  1. Let me check existing main accounts and suggest matches")
            print("  2. Manually specify main account names")
            print("  3. Use default main accounts")
        
            choice = input("\nSelect option (1-3): ").strip()

            if choice == "1":
                # Auto-detect and suggest
                config = self.auto_detect_main_accounts()
                if config:
                    return config
                else:
                    print("Could not auto-detect. Returning to menu...")
                    continue  # Go back to menu instead of falling through

            elif choice == "2":
                # Manual specification
                return self.get_manual_main_account_config()

            elif choice == "3":
                # Use defaults
                return self.get_default_main_account_config()

            else:
                print("Invalid choice. Please enter 1, 2, or 3.")

    def auto_detect_main_accounts(self) -> Dict:
        """Try to auto-detect existing main accounts by scanning the table"""
        try:
            self.logger.info("Attempting to auto-detect existing main accounts...")
    
            config = {}
    
            # Clear any search
            try:
                search_box = self.driver.find_element(
                    By.XPATH, "//input[@aria-controls='accountstable']"
                )
                search_box.clear()
                search_box.send_keys(Keys.RETURN)
                time.sleep(2)
            except:
                pass
    
            # Get all main accounts from the table
            existing_accounts = []
            try:
                # Get table rows
                rows = self.driver.find_elements(By.XPATH, "//table[@id='accountstable']//tbody/tr")
            
                for row in rows:
                    try:
                        cells = row.find_elements(By.TAG_NAME, "td")
                        if len(cells) >= 2:  # At least ID and Name columns
                            account_name = cells[1].text.strip()
                            if account_name and account_name.lower() not in ['name', 'account']:
                                existing_accounts.append(account_name)
                    except:
                        continue
                    
            except Exception as e:
                self.logger.warning(f"Could not fetch existing accounts: {e}")
                return {}
    
            if not existing_accounts:
                print("No existing main accounts found.")
                return {}
    
            # Categorize existing accounts by keywords
            inventory_candidates = []
            revenue_candidates = []
            cost_candidates = []
    
            for account in existing_accounts:
                name_lower = account.lower()
            
                # Check for inventory accounts
                if any(keyword in name_lower for keyword in ['inventory', 'stock', 'asset']):
                    inventory_candidates.append(account)
        
                # Check for revenue accounts
                if any(keyword in name_lower for keyword in ['revenue', 'income', 'sales']):
                    revenue_candidates.append(account)
        
                # Check for cost accounts
                if any(keyword in name_lower for keyword in ['cost', 'expense', 'cogs']):
                    cost_candidates.append(account)
    
            # Build configuration with suggestions
            if inventory_candidates:
                print(f"\nSuggested Inventory main accounts: {', '.join(inventory_candidates[:3])}")
                use_default = input(f"Use '{inventory_candidates[0]}' for Inventory? (y/n): ").strip().lower()
                config['inventory_main'] = inventory_candidates[0] if use_default in ['y', 'yes'] else input("Enter Inventory main account name: ").strip()
            else:
                print("\nNo existing Inventory accounts found.")
                config['inventory_main'] = input("Enter Inventory main account name: ").strip()
    
            if revenue_candidates:
                print(f"\nSuggested Revenue main accounts: {', '.join(revenue_candidates[:3])}")
                use_default = input(f"Use '{revenue_candidates[0]}' for Revenue? (y/n): ").strip().lower()
                config['revenue_main'] = revenue_candidates[0] if use_default in ['y', 'yes'] else input("Enter Revenue main account name: ").strip()
            else:
                print("\nNo existing Revenue accounts found.")
                config['revenue_main'] = input("Enter Revenue main account name: ").strip()
    
            if cost_candidates:
                print(f"\nSuggested Cost of Sales main accounts: {', '.join(cost_candidates[:3])}")
                use_default = input(f"Use '{cost_candidates[0]}' for Cost of Sales? (y/n): ").strip().lower()
                config['cost_main'] = cost_candidates[0] if use_default in ['y', 'yes'] else input("Enter Cost of Sales main account name: ").strip()
            else:
                print("\nNo existing Cost of Sales accounts found.")
                config['cost_main'] = input("Enter Cost of Sales main account name: ").strip()
    
            # Get account classes
            config['inventory_class'] = 'Current Assets'  # Default for inventory
            config['revenue_class'] = 'Revenue'  # Default for revenue
            config['cost_class'] = 'Cost of Sales'  # Default for cost
    
            return config
    
        except Exception as e:
            self.logger.error(f"Auto-detection failed: {e}")
            return {}

    def get_manual_main_account_config(self) -> Dict:
        """Get manual configuration for main accounts"""
        config = {}
    
        print("\n" + "="*60)
        print("MANUAL MAIN ACCOUNT CONFIGURATION")
        print("="*60)
    
        print("\n--- ASSET SUB-ACCOUNTS (from CSV: AssetSubAccount column) ---")
        print("These sub-accounts will be created under a main Inventory account.")
        config['inventory_main'] = input("Enter main Inventory account name: ").strip()
        config['inventory_class'] = input("Enter account class for Inventory [Current Assets]: ").strip() or "Current Assets"
    
        print("\n--- REVENUE SUB-ACCOUNTS (from CSV: RevenueSubAccount column) ---")
        print("These sub-accounts will be created under a main Revenue account.")
        config['revenue_main'] = input("Enter main Revenue account name: ").strip()
        config['revenue_class'] = input("Enter account class for Revenue [Revenue]: ").strip() or "Revenue"
    
        print("\n--- COST OF SALES SUB-ACCOUNTS (from CSV: CostOfSaleSubAccount column) ---")
        print("These sub-accounts will be created under a main Cost of Sales account.")
        config['cost_main'] = input("Enter main Cost of Sales account name: ").strip()
        config['cost_class'] = input("Enter account class for Cost of Sales [Cost of Sales]: ").strip() or "Cost of Sales"
    
        # Show summary
        print("\n" + "="*60)
        print("CONFIGURATION SUMMARY")
        print("="*60)
        print(f"1. ASSET Sub-Accounts → Main: {config['inventory_main']} ({config['inventory_class']})")
        print(f"2. REVENUE Sub-Accounts → Main: {config['revenue_main']} ({config['revenue_class']})")
        print(f"3. COST OF SALES Sub-Accounts → Main: {config['cost_main']} ({config['cost_class']})")
    
        confirm = input("\nConfirm this configuration? (y/n): ").strip().lower()
        if confirm not in ['y', 'yes']:
            print("Configuration cancelled. Please try again.")
            return self.get_manual_main_account_config()
        return config

    def get_default_main_account_config(self) -> Dict:
        """Get default main account configuration"""
        return {
            'inventory_main': 'Inventory',
            'inventory_class': 'Current Assets',
            'revenue_main': 'Revenue',
            'revenue_class': 'Income',
            'cost_main': 'Cost of Goods Sold',
            'cost_class': 'Cost of Goods Sold'
        }

    # ==================== TAXES/VAT PANEL ====================

    def navigate_to_taxes(self) -> bool:
        """Navigate to Taxes/VAT panel and perform all actions there"""
        try:
            # Click Taxes
            taxes_link = self.wait.until(
                EC.element_to_be_clickable((By.XPATH, "//a[contains(text(),'Taxes')]"))
            )
            taxes_link.click()
            time.sleep(3)  # Wait for page to fully load

            self.logger.info("✓ Successfully navigated to Taxes panel")
            return True

        except Exception as e:
            self.logger.error(f"Navigation to Taxes panel failed: {str(e)}")
            return False

    def create_vat_types_bulk(self, missing_vat_types: List[str]) -> bool:
        """Allow user to configure multiple VAT types at once"""
        print("\n" + "=" * 60)
        print("BULK VAT TYPE CONFIGURATION")
        print("=" * 60)
        print("Configure VAT rates and tax codes for all missing types:")

        vat_configurations = {}

        for vat_type in missing_vat_types:
            print(f"\n--- {vat_type} ---")

            # Get VAT rate
            while True:
                rate_input = input(f"VAT rate (0-100) for '{vat_type}': ").strip()
                if rate_input.isdigit():
                    rate = int(rate_input)
                    if 0 <= rate <= 100:
                        break
                    else:
                        print("Rate must be between 0 and 100")
                else:
                    print("Please enter a valid number")

            # Get tax code
            tax_code = input(f"Tax code for '{vat_type}' (default: E): ").strip()
            if not tax_code:
                tax_code = "E"

            vat_configurations[vat_type] = {"rate": rate, "tax_code": tax_code}

        # Confirm configurations
        print("\n" + "=" * 60)
        print("CONFIGURATION SUMMARY")
        print("=" * 60)
        for vat_type, config in vat_configurations.items():
            print(f"{vat_type}: {config['rate']}%, Tax Code: {config['tax_code']}")

        confirm = (
            input("\nProceed with creating these VAT types? (y/n): ").strip().lower()
        )
        if confirm not in ["y", "yes"]:
            print("VAT type creation cancelled.")
            return False

        # Create all VAT types
        success_count = 0
        for vat_type, config in vat_configurations.items():
            print(f"\nCreating VAT type: {vat_type}...")
            if self.create_vat_type_in_panel(
                vat_type, config["rate"], config["tax_code"]
            ):
                success_count += 1
                print(f"✓ Created: {vat_type}")
            else:
                print(f"✗ Failed: {vat_type}")
                # Ask if user wants to continue after failure
                continue_choice = input("Continue with remaining VAT types? (y/n): ").strip().lower()
                if continue_choice not in ['y', 'yes']:
                    break

        return success_count == len(missing_vat_types)


    def verify_vat_types_in_panel(self, csv_data: List[Dict]) -> bool:
        """Verify VAT types exist in the Taxes/VAT panel with auto-creation option"""
        try:
            if not self.navigate_to_taxes():
                return False
    
            self.logger.info("=== Verifying VAT Types in Taxes Panel ===")
    
            # Extract unique VAT types from CSV
            csv_vat_types = set()
            for row in csv_data:
                vat_type = row.get('VATType', '').strip()
                if vat_type:
                    csv_vat_types.add(vat_type)
        
            self.logger.info(f"Found {len(csv_vat_types)} unique VAT types in CSV")
            self.logger.debug(f"CSV VAT types: {sorted(csv_vat_types)}")
    
            # Get existing VAT types from the system
            existing_vat_types = self.get_existing_vat_types()
        
            self.logger.info(f"Found {len(existing_vat_types)} existing VAT types in system")
            self.logger.debug(f"Existing VAT types: {sorted(existing_vat_types)}")
    
            # Identify missing VAT types
            missing_vat_types = []
            for vat_type in csv_vat_types:
                if vat_type not in existing_vat_types:
                    missing_vat_types.append(vat_type)
                    self.logger.warning(f"VAT type '{vat_type}' not found in system")
        
            self.logger.info(f"Missing VAT types: {len(missing_vat_types)}")
    
            # If no missing VAT types, return success
            if not missing_vat_types:
                self.logger.info("✓ All VAT types from CSV exist in the system")
                self.verification_stats['vat_verified'] = len(csv_vat_types)
                return True
    
            # Handle missing VAT types
            if self.dry_run:
                self.logger.info(f"Would create {len(missing_vat_types)} missing VAT types (dry run)")
                self.logger.info(f"Missing: {missing_vat_types}")
                return True
    
            print("\n" + "="*60)
            print("MISSING VAT TYPES DETECTED")
            print("="*60)
            print(f"Missing VAT types ({len(missing_vat_types)}):")
            for i, vat_type in enumerate(missing_vat_types, 1):
                print(f"  {i}. {vat_type}")
    
            print("\nOptions:")
            print("  1. Create all missing VAT types with bulk configuration")
            print("  2. Create VAT types one by one")
            print("  3. Skip VAT type creation (may cause import failures)")
            print("  4. Abort import")
    
            while True:
                choice = input("\nSelect option (1-4): ").strip()
                if choice == "1":
                    return self.create_vat_types_bulk(missing_vat_types)
                elif choice == "2":
                    return self.create_vat_types_individual(missing_vat_types)
                elif choice == "3":
                    self.logger.warning(f"Skipping creation of {len(missing_vat_types)} VAT types")
                    self.verification_stats['vat_verified'] = len(csv_vat_types) - len(missing_vat_types)
                    return True  # Continue anyway
                elif choice == "4":
                    self.logger.error("User chose to abort import due to missing VAT types")
                    return False
                else:
                    print("Invalid choice. Please enter 1, 2, 3, or 4.")
    
        except Exception as e:
            self.logger.error(f"✗ VAT types verification failed in panel: {str(e)}")
            self.take_screenshot("taxes_panel_verification_error")
            return False

    def get_existing_vat_types(self) -> Set[str]:
        """Get all existing VAT type names from the panel"""
        existing_vat_types = set()
        try:
            time.sleep(2)  # Wait for table to load
        
            # Find all table rows (skip header row if exists)
            vat_rows = self.driver.find_elements(By.XPATH, "//table[@id='vattypesstable']/tbody/tr")
        
            if not vat_rows:
                # Try alternative XPath if no tbody
                vat_rows = self.driver.find_elements(By.XPATH, "//table//tr")
        
            self.logger.info(f"Found {len(vat_rows)} rows in VAT table")
        
            for row in vat_rows:
                try:
                    # Get all cells in this row
                    cells = row.find_elements(By.TAG_NAME, "td")
                
                    # Need at least 3 cells (ID, Name, Rate) with second cell being name
                    if len(cells) >= 3:
                        vat_name = cells[1].text.strip()
                    
                        # Skip empty names and possible header values
                        if (vat_name and 
                            vat_name.lower() not in ['', 'name', 'vat', 'vat type', 'vattype'] and
                            not vat_name.isdigit()):  # Skip numeric values (likely IDs)
                        
                            existing_vat_types.add(vat_name)
                            self.logger.debug(f"Found VAT type: {vat_name}")
                        
                except Exception as e:
                    self.logger.debug(f"Error processing row: {str(e)}")
                    continue
                
            self.logger.info(f"Total unique VAT types found: {len(existing_vat_types)}")
        
        except Exception as e:
            self.logger.error(f"Error getting existing VAT types: {str(e)}")
            self.take_screenshot("get_existing_vat_types_error")
    
        return existing_vat_types

    def create_vat_types_individual(self, missing_vat_types: List[str]) -> bool:
        """Create VAT types one by one with user input"""
        success_count = 0

        for vat_type in missing_vat_types:
            print(f"\n" + "-"*40)
            print(f"Configuring VAT Type: {vat_type}")
            print("-"*40)
    
            # Get VAT rate
            while True:
                rate_input = input(f"Enter VAT rate (0-100) for '{vat_type}': ").strip()
                if rate_input.isdigit():
                    vat_rate = int(rate_input)
                    if 0 <= vat_rate <= 100:
                        break
                    else:
                        print("Rate must be between 0 and 100")
                else:
                    print("Please enter a valid number")
    
            # Get tax code
            tax_code = input(f"Enter tax code for '{vat_type}' (default: E): ").strip()
            if not tax_code:
                tax_code = "E"
    
            # Ask for liability sub-account
            liability_account = input(f"Enter VAT Liability Sub-Account (default: 'Accrued Liabilities - Vat Payable'): ").strip()
            if not liability_account:
                liability_account = "Accrued Liabilities - Vat Payable"
    
            # Create the VAT type
            if self.create_vat_type_in_panel(vat_type, vat_rate, tax_code, liability_account):
                success_count += 1
                print(f"✓ Created: {vat_type}")
            else:
                print(f"✗ Failed: {vat_type}")
        
                # Ask if user wants to continue after failure
                continue_choice = input("Continue with remaining VAT types? (y/n): ").strip().lower()
                if continue_choice not in ['y', 'yes']:
                    break

        return success_count == len(missing_vat_types)

    def create_vat_type_in_panel(
        self, vat_name: str, vat_rate: int, tax_code: str = "E",
        liability_account: str = "Accrued Liabilities - Vat Payable"
) -> bool:
        """Create a new VAT type in the Taxes panel"""
        try:
            # First, make sure we're on the Taxes page
            if not self.navigate_to_taxes():
                self.logger.error("Cannot create VAT type: not on Taxes page")
                return False

            # Wait for the form to appear
            try:
                form_indicators = [
                    "//h6[normalize-space()='VAT Type Details']",
                    "//h6[normalize-space()='Other Tax Details']",
                    "//h6[normalize-space()='View: VAT Types']",
                    "//h6[normalize-space()='View: Other Taxes']",
                ]
            
                for indicator in form_indicators:
                    try:
                        self.driver.find_element(By.XPATH, indicator)
                        self.logger.info(f"VAT form loaded (indicator: {indicator})")
                        break
                    except:
                        continue
            except:
                self.logger.warning("Could not confirm VAT form loaded, continuing anyway")

            # 1. Fill VAT Name
            name_field = self.driver.find_element(
                By.XPATH, "//input[@id='VATType_Name']"
            )
            name_field.clear()
            name_field.send_keys(vat_name)

            # 2. Fill VAT Rate (%)
            rate_field = self.driver.find_element(
                By.XPATH, "//input[@id='VATType_PerRate']"
            )
            rate_field.clear()
            rate_field.send_keys(str(vat_rate))

            # 3. Select VAT Liability Sub-Account
            try:
                liability_select = Select(
                    self.driver.find_element(
                        By.XPATH, "//select[@id='VATType_VATLiabSubAccountID']"
                    )
                )
            
                # Try to select the specified account
                try:
                    liability_select.select_by_visible_text(liability_account)
                    self.logger.info(f"Selected liability account: {liability_account}")
                except:
                    # Try partial match
                    for option in liability_select.options:
                        if liability_account.lower() in option.text.lower():
                            liability_select.select_by_visible_text(option.text)
                            self.logger.info(f"Selected liability account (partial match): {option.text}")
                            break
                    else:
                        # Select first non-empty option
                        for i in range(1, len(liability_select.options)):
                            option_text = liability_select.options[i].text.strip()
                            if option_text:
                                liability_select.select_by_index(i)
                                self.logger.info(f"Selected first available liability account: {option_text}")
                                break
            except Exception as e:
                self.logger.warning(f"Could not set liability sub-account: {e}")
                # Continue anyway - this field might not be required

            # 4. Fill Tax Code
            try:
                tax_code_field = self.driver.find_element(
                    By.XPATH, "//input[@id='VATType_ETimsTaxCode']"
                )
                tax_code_field.clear()
                tax_code_field.send_keys(tax_code)
            except:
                self.logger.warning("Could not find tax code field")

            # 5. Save the VAT type
            save_button_selectors = [
                "//button[@id='btnaddvattype']",
                "(//button[@id='btnaddvattype'])[1]",
            ]

            save_button = None
            for selector in save_button_selectors:
                try:
                    save_button = self.driver.find_element(By.XPATH, selector)
                    if save_button.is_displayed() and save_button.is_enabled():
                        self.logger.info(f"Found save button with selector: {selector}")
                        break
                except:
                    continue

            if not save_button:
                self.logger.error("Could not find Save button")
                self.take_screenshot("vat_save_button_not_found")
                return False

            save_button.click()
            time.sleep(3)

            # 6. Check for success
            # Look for success message or return to list
            try:
                # Check for success notification
                success_selectors = [
                    "//div[contains(@class, 'noty_body')]",
                    "(//div[@class='noty_body'])[1]",
                ]
            
                for selector in success_selectors:
                    try:
                        success_msg = self.driver.find_element(By.XPATH, selector)
                        if success_msg.is_displayed():
                            self.logger.info(f"Success message: {success_msg.text}")
                            return True
                    except:
                        continue
                    
                # Check if VAT appears in the table (search for it)
                if self.navigate_to_taxes():
                    # Search for the new VAT type
                    search_box = self.driver.find_element(
                        By.XPATH, "//input[@type='search']"
                    )
                    search_box.clear()
                    search_box.send_keys(vat_name)
                    search_box.send_keys(Keys.RETURN)
                    time.sleep(2)
                
                    # Check if it appears
                    try:
                        vat_cell = self.driver.find_element(
                            By.XPATH, f"//td[contains(text(), '{vat_name}')]"
                        )
                        if vat_cell.is_displayed():
                            self.logger.info(f"✓ VAT type '{vat_name}' created successfully")
                            return True
                    except:
                        pass
                    
            except Exception as e:
                self.logger.warning(f"Error checking success: {e}")
            
            # If we get here, creation might have failed
            self.logger.error(f"Could not confirm creation of VAT type '{vat_name}'")
            self.take_screenshot(f"vat_creation_uncertain_{vat_name}")
            return False

        except Exception as e:
            self.logger.error(f"Error creating VAT type '{vat_name}': {str(e)}")
            self.take_screenshot(f"vat_creation_error_{vat_name}")
            return False


    # ==================== UNIT OF MEASURE PANEL ====================

    def navigate_to_unit_of_measure(self) -> bool:
        """Navigate to Unit of Measure panel and perform all actions there"""
        try:
            # Expand Inventory module
            inventory_module = self.wait.until(
                EC.element_to_be_clickable(
                    (By.XPATH, "//a[normalize-space()='Inventory']")
                )
            )
            inventory_module.click()
            time.sleep(1)

            # Click Unit of Measure
            uom_link = self.wait.until(
                EC.element_to_be_clickable(
                    (By.XPATH, "(//a[normalize-space()='Unit Of Measure'])[1]")
                )
            )
            uom_link.click()
            time.sleep(3)  # Wait for page to fully load

            self.logger.info("✓ Successfully navigated to Unit of Measure panel")
            return True

        except Exception as e:
            self.logger.error(f"Navigation to Unit of Measure panel failed: {str(e)}")
            return False

    def verify_and_create_units_in_panel(self, csv_data: List[Dict]) -> bool:
        """Verify and create Units of Measure in the Unit of Measure panel with search support"""
        try:
            if not self.navigate_to_unit_of_measure():
                return False

            self.logger.info(
                "=== Verifying Units of Measure in Unit of Measure Panel ==="
            )

            # Extract unique units from CSV and normalize to Title Case
            csv_units = {row["UnitOfMeasure"].strip().title() for row in csv_data}
            self.logger.info(f"Looking for {len(csv_units)} units from CSV")

            units_verified = 0
            units_created = 0

            for unit in csv_units:
                # Check if unit exists using search + row scanning
                unit_exists = self.check_unit_exists_with_search(unit)

                if unit_exists:
                    self.logger.info(
                        f"✓ Unit of measure '{unit}' exists in panel"
                    )
                    units_verified += 1
                else:
                    # Create missing unit in the panel
                    if not self.dry_run:
                        try:
                            # Fill unit form in the panel
                            unit_field = self.wait.until(
                                EC.presence_of_element_located(
                                    (
                                        By.XPATH,
                                        "//input[@id='UnitOfMeasure_Name']",
                                    )
                                )
                            )
                            unit_field.clear()
                            unit_field.send_keys(unit)

                            # Select measurement unit
                            try:
                                measurement_unit_select = Select(self.driver.find_element(
                                    By.XPATH, "//select[@id='UnitOfMeasure_MeasurementUnit']"
                                ))
                                measurement_unit_select.select_by_visible_text("Pieces")
                            except:
                                self.logger.warning("Could not set measurement unit")

                            # Select packaging unit
                            try:
                                packaging_unit_select = Select(self.driver.find_element(
                                    By.XPATH, "//select[@id='UnitOfMeasure_PackagingUnit']"
                                ))
                                # Try to select first option
                                packaging_unit_select.select_by_index(1)
                            except:
                                self.logger.warning("Could not set packaging unit")

                            # Save in the panel
                            save_button = self.driver.find_element(
                                By.XPATH,
                                "//button[@id='btnaddunitofmeasure']",
                            )
                            save_button.click()
                            time.sleep(2)  # Wait for creation

                            # VERIFICATION: Check if unit was created using search
                            created = False
                            for attempt in range(3):  # Try 3 times
                                time.sleep(1)
                                if self.check_unit_exists_with_search(unit):
                                    created = True
                                    break
                        
                            if created:
                                self.logger.info(
                                    f"✓ Created unit of measure in panel: {unit}"
                                )
                                units_created += 1

                                # Clear any search filter to show all items again
                                self.clear_unit_search()
                            
                            else:
                                self.logger.error(
                                    f"✗ Failed to verify creation of unit '{unit}' in panel"
                                )
                                self.take_screenshot(f"unit_creation_error_{unit}")
                                return False

                        except Exception as e:
                            self.logger.error(
                                f"✗ Failed to create unit '{unit}' in panel: {str(e)}"
                            )
                            self.take_screenshot(f"unit_creation_error_{unit}")
                            return False
                    else:
                        self.logger.info(
                            f"✓ Would create unit of measure in panel: {unit} (dry run)"
                        )
                        units_created += 1

            self.verification_stats["units_verified"] = units_verified
            self.verification_stats["units_created"] = units_created

            self.logger.info(
                f"✓ Unit of Measure verification complete: {units_verified} verified, {units_created} created"
            )
            return True

        except Exception as e:
            self.logger.error(
                f"✗ Unit of Measure verification failed in panel: {str(e)}"
            )
            self.take_screenshot("unit_of_measure_panel_error")
            return False
    
    def check_unit_exists_with_search(self, unit_name: str) -> bool:
        """Check if a unit exists using table search and row scanning"""
        try:
            # First try to use search if available
            if self.search_unit_in_table(unit_name):
                return True
        
            # If search not available or didn't work, fall back to full table scan
            return self.scan_unit_table_for_match(unit_name)
        
        except Exception as e:
            self.logger.debug(f"Error checking unit existence: {e}")
            return False

    def search_unit_in_table(self, unit_name: str) -> bool:
        """Use the table search feature to find a unit"""
        try:
            # Look for search input - common selectors for DataTables
            search_selectors = [
                "input[aria-controls='unitofmeasurestable']",
                "//input[@aria-controls='unitofmeasurestable']",
                "(//input[@aria-controls='unitofmeasurestable'])[1]",
            ]
        
            search_box = None
            for selector in search_selectors:
                try:
                    search_box = self.driver.find_element(By.XPATH, selector)
                    if search_box.is_displayed():
                        self.logger.debug(f"Found search box with selector: {selector}")
                        break
                except:
                    continue
        
            if not search_box:
                self.logger.debug("No search box found in units panel")
                return False
        
            # Use search
            search_box.clear()
            search_box.send_keys(unit_name)
            time.sleep(1)  # Wait for table to filter
        
            # Check if any rows appear in the filtered table
            try:
                # Find the table
                table_selectors = [
                    "#unitofmeasurestable",
                    "//table[@id='unitofmeasurestable']",
                    "(//table[@id='unitofmeasurestable'])[1]",
                ]
            
                table = None
                for selector in table_selectors:
                    try:
                        table = self.driver.find_element(By.XPATH, selector)
                        break
                    except:
                        continue
            
                if not table:
                    return False
            
                # Get filtered rows
                rows = table.find_elements(By.XPATH, "//table[@id='unitofmeasurestable']/tbody/tr")
                if not rows:
                    rows = table.find_elements(By.XPATH, ".//tr[td]")  # Skip header
            
                # Check if any row contains the exact unit name
                for row in rows:
                    try:
                        cells = row.find_elements(By.TAG_NAME, "td")
                        if cells:
                            # Get unit name in second column
                            cell_text = cells[1].text.strip()
                            if cell_text.lower() == unit_name.lower():
                                self.logger.debug(f"Found unit '{unit_name}' via search")
                                return True
                    except:
                        continue
            
                return False
            
            finally:
                # Always clear the search to not affect subsequent operations
                search_box.clear()
                time.sleep(0.5)
            
        except Exception as e:
            self.logger.debug(f"Error during unit search: {e}")
            return False

    def scan_unit_table_for_match(self, unit_name: str) -> bool:
        """Scan the entire unit table for a match"""
        try:
            # Find the table
            table_selectors = [
                "#unitofmeasurestable",
                "//table[@id='unitofmeasurestable']",
                "(//table[@id='unitofmeasurestable'])[1]",
            ]
        
            table = None
            for selector in table_selectors:
                try:
                    table = self.driver.find_element(By.XPATH, selector)
                    break
                except:
                    continue
        
            if not table:
                self.logger.warning("Unit table not found")
                return False
        
            # Get all rows
            try:
                rows = table.find_elements(By.XPATH, "//table[@id='unitofmeasurestable']/tbody/tr")
            except:
                rows = table.find_elements(By.XPATH, ".//tr")
        
            self.logger.debug(f"Scanning {len(rows)} rows for unit '{unit_name}'")
        
            # Scan each row
            for row in rows:
                try:
                    cells = row.find_elements(By.TAG_NAME, "td")
                    if cells:
                        # Unit name in second column
                        cell_text = cells[1].text.strip()
                    
                        # Exact match
                        if cell_text.lower() == unit_name.lower():
                            self.logger.debug(f"Found unit '{unit_name}' in table")
                            return True
                    
                        # Partial match (in case of extra formatting)
                        if unit_name.lower() in cell_text.lower():
                            self.logger.debug(f"Found partial match: '{cell_text}' for '{unit_name}'")
                            return True
                except Exception as e:
                    self.logger.debug(f"Error checking row: {e}")
                    continue
        
            return False
        
        except Exception as e:
            self.logger.debug(f"Error scanning unit table: {e}")
            return False

    def clear_unit_search(self):
        """Clear any active search in the units table"""
        try:
            search_selectors = [
                "#unitofmeasurestable",
                "//table[@id='unitofmeasurestable']",
                "(//table[@id='unitofmeasurestable'])[1]",
            ]
        
            for selector in search_selectors:
                try:
                    search_box = self.driver.find_element(By.XPATH, selector)
                    search_box.clear()
                    search_box.send_keys(Keys.RETURN)  # Trigger search to show all
                    time.sleep(0.5)
                    break
                except:
                    continue
        except:
            pass  # Silently fail if search can't be cleared

    # ==================== ITEM CATEGORIES PANEL VIA SERVICES PANEL ====================

    def navigate_to_item_categories(self) -> bool:
        """Navigate to Item Categories panel and perform all actions there"""
        try:
            # Expand Configuration module
            config_module = self.wait.until(
                EC.element_to_be_clickable(
                    (By.XPATH, "//a[normalize-space()='Configuration']")
                )
            )
            config_module.click()
            time.sleep(1)

            # Open Services panel
            services_link = self.wait.until(
                EC.element_to_be_clickable(
                    (By.XPATH, "//a[normalize-space()='Services']")
                )
            )
            services_link.click()
            time.sleep(1)

            # Click Item Categories button to open modal
            item_categories_button = self.wait.until(
                EC.element_to_be_clickable(
                    (By.XPATH, "//button[@id='btnConfigureItemCat']")
                )
            )
            item_categories_button.click()
            time.sleep(3)  # Wait for modal to fully load

            self.logger.info("✓ Successfully navigated to Item Categories modal")
            return True

        except Exception as e:
            self.logger.error(f"Navigation to Item Categories modal failed: {str(e)}")
            return False

    def verify_and_create_categories_in_panel(self, csv_data: List[Dict]) -> bool:
        """Verify and create Item Categories in the Item Categories modal"""
        try:
            if not self.navigate_to_item_categories():
                return False

            self.logger.info(
                "=== Verifying Item Categories in Item Categories Modal ==="
            )

            # Extract unique categories from CSV and normalize to Title Case
            csv_categories = {row["ItemCategory"].strip().title() for row in csv_data}
            self.logger.info(f"Looking for {len(csv_categories)} categories from CSV")

            categories_verified = 0
            categories_created = 0

            # Default department to use when creating categories
            default_department = self.config.get("default_department", "Pharmacy")

            for category in csv_categories:
                # Check if category exists by looping through table rows
                category_exists = self.check_category_exists_by_row_scan(category)

                if category_exists:
                    self.logger.info(
                        f"✓ Item category '{category}' exists in modal"
                    )
                    categories_verified += 1
                else:
                    # Create missing category in the modal
                    if not self.dry_run:
                        try:
                            # Fill category form in the modal
                            # 1. Name field
                            category_name_field = self.wait.until(
                                EC.presence_of_element_located(
                                    (By.XPATH, "//input[@id='ItemCategory_Name']")
                                )
                            )
                            category_name_field.clear()
                            category_name_field.send_keys(category)

                            # 2. Department field
                            try:
                                department_select = Select(
                                    self.driver.find_element(
                                        By.XPATH,
                                        "//select[@id='ItemCategory_DepartmentID']",
                                    )
                                )
                                try:
                                    department_select.select_by_visible_text(
                                        default_department
                                    )
                                except:
                                    department_select.select_by_index(1)
                            except Exception as dept_error:
                                self.logger.warning(
                                    f"Could not set department: {dept_error}"
                                )

                            # 3. Click Add Category button in the modal
                            add_button = self.wait.until(
                                EC.element_to_be_clickable(
                                    (By.XPATH, "//button[@id='btnadditemcat']")
                                )
                            )
                            add_button.click()
                            time.sleep(2)  # Wait for creation

                            # VERIFICATION: Check if category was created by scanning rows
                            created = False
                            for attempt in range(3):  # Try 3 times
                                time.sleep(1)  # Wait for table to update
                                if self.check_category_exists_by_row_scan(category):
                                    created = True
                                    break
                        
                            if created:
                                self.logger.info(
                                    f"✓ Created item category in modal: {category}"
                                )
                                categories_created += 1
                            else:
                                self.logger.error(
                                    f"✗ Failed to verify creation of category '{category}' in modal"
                                )
                                self.take_screenshot(
                                    f"category_creation_error_{category}"
                                )
                                return False

                        except Exception as e:
                            self.logger.error(
                                f"✗ Failed to create category '{category}' in modal: {str(e)}"
                            )
                            self.take_screenshot(f"category_creation_error_{category}")
                            return False
                    else:
                        self.logger.info(
                            f"✓ Would create item category in modal: {category} (dry run)"
                        )
                        categories_created += 1

            self.verification_stats["categories_verified"] = categories_verified
            self.verification_stats["categories_created"] = categories_created
        
            # Close the item categories modal after processing
            self.close_item_categories_modal()

            self.logger.info(
                f"✓ Item Categories verification complete: {categories_verified} verified, {categories_created} created"
            )
            return True

        except Exception as e:
            self.logger.error(
                f"✗ Item Categories verification failed in modal: {str(e)}"
            )
            self.take_screenshot("item_categories_modal_error")
            return False

    def check_category_exists_by_row_scan(self, category_name: str) -> bool:
        """Check if a category exists by scanning table rows (similar to sub-accounts method)"""
        try:
            # Try different table selectors
            table_selectors = [
                "//table[@id='itemcategoriestable']",
                "#itemcategoriestable",
                "(//table[@id='itemcategoriestable'])[1]"
            ]
        
            table = None
            for selector in table_selectors:
                try:
                    table = self.driver.find_element(By.XPATH, selector)
                    break
                except:
                    continue
        
            if not table:
                self.logger.warning("Category table not found")
                return False
        
            # Get all rows in the table - THIS IS THE KEY PART
            try:
                rows = table.find_elements(By.XPATH, "//table[@id='itemcategoriestable']/tbody/tr")
            except:
                # If no tbody, try without it
                rows = table.find_elements(By.XPATH, ".//tr")
        
            self.logger.debug(f"Scanning {len(rows)} rows for category '{category_name}'")

            # Scan through each row
            for row in rows:
                try:
                    cells = row.find_elements(By.TAG_NAME, "td")
                    if cells and len(cells) >= 2:  # Need at least 2 columns
                        # Try different column indices - usually Name is in second column
                        cell_text = cells[1].text.strip() if len(cells) > 1 else cells[0].text.strip()
                    
                        if cell_text.lower() == category_name.lower():
                            self.logger.debug(f"Found category '{category_name}' in table")
                            return True
                        
                        # Also check for partial matches (in case of extra spaces, etc.)
                        if category_name.lower() in cell_text.lower():
                            self.logger.debug(f"Found partial match for '{category_name}': '{cell_text}'")
                            return True
                except Exception as e:
                    self.logger.debug(f"Error checking row: {e}")
                    continue
        
            # If not found, try with a search if available
            if not self.try_table_search(category_name):
                self.logger.debug(f"Category '{category_name}' not found in table")
        
            return False
        
        except Exception as e:
            self.logger.debug(f"Error in check_category_exists_by_row_scan: {e}")
            return False
    
    def close_item_categories_modal(self) -> bool:
        """Close the Item Categories modal"""
        try:
            # Look for close button in the modal
            close_selectors = [
                "//div[contains(@class, 'modal fade item-categories-modal')]//button[@aria-label='Close']",
                "//div[contains(@class, 'modal fade item-categories-modal')]//span[@aria-hidden='true'][normalize-space()='×']",
                "//div[contains(@class, 'modal')]//button[contains(@data-dismiss, 'modal')]",
                "//button[contains(text(), 'Close') and contains(@class, 'btn-default')]",
            ]
            
            for selector in close_selectors:
                try:
                    close_button = self.driver.find_element(By.XPATH, selector)
                    if close_button.is_displayed() and close_button.is_enabled():
                        close_button.click()
                        time.sleep(1)
                        self.logger.info("✓ Item Categories modal closed")
                        return True
                except:
                    continue
            
            # If no close button found, try pressing Escape
            self.driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.ESCAPE)
            time.sleep(1)
            self.logger.info("✓ Item Categories modal closed with Escape key")
            return True
            
        except Exception as e:
            self.logger.warning(f"Could not close Item Categories modal: {e}")
            # Continue anyway - the next navigation might override it
            return False

    # ==================== ITEM CLASSES PANEL ====================

    def navigate_to_item_classes(self) -> bool:
        """Navigate to Item Classes panel and perform all actions there"""
        try:
            # Click Item Classes
            item_classes_button = self.wait.until(
                EC.element_to_be_clickable(
                    (By.XPATH, "//button[normalize-space()='Item Classes']")
                )
            )
            item_classes_button.click()
            time.sleep(3)  # Wait for page to fully load

            self.logger.info("✓ Successfully navigated to Item Classes panel")
            return True

        except Exception as e:
            self.logger.error(f"Navigation to Item Classes panel failed: {str(e)}")
            return False

    def verify_and_create_classes_in_panel(self, csv_data: List[Dict]) -> bool:
        """Verify and create Item Classes in the Item Classes modal"""
        try:
            if not self.navigate_to_item_classes():
                return False

            self.logger.info("=== Verifying Item Classes in Item Classes Modal ===")

            # Extract unique classes from CSV and normalize to Title Case
            csv_classes = {row["ItemClass"].strip().title() for row in csv_data}

            # Get existing classes from the modal (normalized to Title Case)
            existing_classes = set()
            try:
                time.sleep(2)
                class_rows = self.driver.find_elements(By.XPATH, "//table[@id='itemclassestable']/tbody/tr")
                for row in class_rows[:100]:
                    try:
                        class_cells = row.find_elements(By.TAG_NAME, "td")
                        if class_cells:
                            class_name = class_cells[1].text.strip()
                            if class_name:
                                existing_classes.add(class_name.title())
                    except:
                        continue
                self.logger.info(
                    f"Found {len(existing_classes)} existing classes in modal"
                )
            except Exception as e:
                self.logger.warning(f"Could not fetch existing classes from modal: {e}")

            classes_verified = 0
            classes_created = 0

            for item_class in csv_classes:
                if item_class in existing_classes:
                    self.logger.info(
                        f"✓ Item class '{item_class}' exists in modal (normalized)"
                    )
                    classes_verified += 1
                else:
                    # Create missing class in the modal
                    if not self.dry_run:
                        try:
                            # Fill class form in the modal
                            class_name_field = self.wait.until(
                                EC.presence_of_element_located(
                                    (
                                        By.XPATH,
                                        "//input[@id='ItemClass_Name']",
                                    )
                                )
                            )
                            class_name_field.send_keys(item_class)

                            # Class type select field
                            class_type_select = Select(self.driver.find_element(
                                By.XPATH, "//select[@id='ItemClass_ItemClassType']"
                            ))
                            class_type_select.select_by_visible_text("Drug Class")

                            # Save in the modal
                            item_class_add_button = self.driver.find_element(
                                By.XPATH,
                                "//button[@id='btnadditemclass']",
                            )
                            item_class_add_button.click()
                            time.sleep(3)

                            # Verify creation in the modal
                            try:
                                self.driver.find_element(
                                    By.XPATH,
                                    f"//tr[td[contains(text(), '{item_class}')]]",
                                )
                                self.logger.info(
                                    f"✓ Created item class in modal: {item_class}"
                                )
                                classes_created += 1

                                # Add to existing classes for subsequent checks
                                existing_classes.add(item_class)

                            except NoSuchElementException:
                                self.logger.error(
                                    f"✗ Failed to verify creation of class '{item_class}' in modal"
                                )
                                self.take_screenshot(
                                    f"class_creation_error_{item_class}"
                                )
                                return False

                        except Exception as e:
                            self.logger.error(
                                f"✗ Failed to create class '{item_class}' in modal: {str(e)}"
                            )
                            self.take_screenshot(f"class_creation_error_{item_class}")
                            return False
                    else:
                        self.logger.info(
                            f"✓ Would create item class in modal: {item_class} (dry run)"
                        )
                        classes_created += 1

            self.verification_stats["classes_verified"] = classes_verified
            self.verification_stats["classes_created"] = classes_created
            
            # Close the item classes modal after processing
            self.close_item_classes_modal()
            
            self.logger.info(
                f"✓ Item Classes verification complete in modal: {classes_verified} verified, {classes_created} created"
            )
            return True

        except Exception as e:
            self.logger.error(f"✗ Item Classes verification failed in modal: {str(e)}")
            self.take_screenshot("item_classes_modal_error")
            return False
    
    def close_item_classes_modal(self) -> bool:
        """Close the Item Classes modal"""
        try:
            # Look for close button in the modal
            close_selectors = [
                "div[class='modal fade item-class-modal in'] span[aria-hidden='true']",
                "//div[@class='modal fade item-class-modal in']//span[@aria-hidden='true'][normalize-space()='×']",
                "//div[contains(@class, 'modal fade item-classes-modal')]//button[@aria-label='Close']",
                "//div[contains(@class, 'modal fade item-classes-modal')]//span[@aria-hidden='true'][normalize-space()='×']",
                "//div[contains(@class, 'modal')]//button[contains(@data-dismiss, 'modal')]",
                "//button[contains(text(), 'Close') and contains(@class, 'btn-default')]",
            ]
            
            for selector in close_selectors:
                try:
                    close_button = self.driver.find_element(By.XPATH, selector)
                    if close_button.is_displayed() and close_button.is_enabled():
                        close_button.click()
                        time.sleep(1)
                        self.logger.info("✓ Item Classes modal closed")
                        return True
                except:
                    continue
            
            # If no close button found, try pressing Escape
            self.driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.ESCAPE)
            time.sleep(1)
            self.logger.info("✓ Item Classes modal closed with Escape key")
            return True
            
        except Exception as e:
            self.logger.warning(f"Could not close Item Classes modal: {e}")
            # Continue anyway - the next navigation might override it
            return False

    # ==================== INVENTORY ITEMS PANEL ====================

    def navigate_to_inventory_items(self) -> bool:
        """Navigate to Inventory Items panel and perform all actions there"""
        try:
            # Click Inventory
            inventory_panel = self.wait.until(
                EC.element_to_be_clickable(
                    (By.XPATH, "(//a[normalize-space()='Inventory'])[2]")
                )
            )
            inventory_panel.click()
            time.sleep(2)

            # Select storage location
            storage_select = Select(
                self.driver.find_element(By.XPATH, "//select[@id='ItemStorageLocation_StorageLocationID']")
            )
            storage_select.select_by_visible_text(self.config["storage_location"])
            time.sleep(2)

            self.logger.info("✓ Successfully navigated to Inventory Items panel")
            return True

        except Exception as e:
            self.logger.error(f"Navigation to Inventory Items panel failed: {str(e)}")
            return False

    def upload_inventory_csv_in_panel(self, csv_path: str) -> bool:
        """Upload CSV file in the Inventory Items panel"""
        try:
            if not self.navigate_to_inventory_items():
                return False

            self.logger.info("=== Uploading Inventory CSV in Inventory Items Panel ===")

            # Count total items in CSV for reference
            csv_items = self.read_csv_items(csv_path)
            total_csv_items = len(csv_items)
            self.logger.info(f"CSV contains {total_csv_items} items for import")
        
            # Store CSV data for verification
            self.csv_data_for_verification = csv_items

            # Look for Import/Upload button in the panel
            try:
                import_products_button = self.wait.until(
                    EC.element_to_be_clickable(
                        (
                            By.XPATH, "//button[normalize-space()='Import Products']"
                        )
                    )
                )
                import_products_button.click()
                time.sleep(1)
                
                # Look for file input in the panel
                file_input = self.driver.find_element(By.XPATH, "//input[@id='csvFile']")
                file_path = str(Path(csv_path).absolute())
                file_input.send_keys(file_path)

                self.logger.info(f"✓ CSV file selected in panel: {csv_path}")
                time.sleep(3)

                upload_button = self.wait.until(
                    EC.element_to_be_clickable(
                        (
                            By.XPATH,
                            "//button[@id='btnImportCsv']",
                        )
                    )
                )
                upload_button.click()
                time.sleep(2)

                # Wait for upload to complete with dynamic timeout
                import_success = self.wait_for_upload_completion()
            
                if not import_success:
                    self.logger.error("✗ Upload process did not complete successfully")
                    return False
                # Close upload modal if it's still open
                self.close_upload_modal()
            
                # Wait for inventory table to refresh
                time.sleep(3)
            
                # Now verify what was actually imported
                verification_result = self.verify_imported_items(csv_items)
            
                # Update stats based on verification
                self.verification_stats["items_imported"] = verification_result["imported_count"]
                self.verification_stats["items_failed"] = verification_result["failed_count"]
                self.verification_stats["items_skipped"] = verification_result["skipped_count"]
            
                # Log detailed results
                self.log_import_verification_details(verification_result)
            
                return verification_result["imported_count"] > 0

            except Exception as e:
                self.logger.error(
                    f"✗ CSV upload feature not found in Inventory panel: {str(e)}"
                )
                self.take_screenshot("inventory_panel_no_upload_feature")

                # Fall back to manual import in the panel
                self.logger.info(
                    "Attempting manual item-by-item import in Inventory panel..."
                )
                return self.import_items_manually_in_panel(csv_path)

        except Exception as e:
            self.logger.error(f"✗ CSV upload failed in Inventory panel: {str(e)}")
            self.take_screenshot("inventory_panel_upload_process_error")
            return False
    
    def wait_for_upload_completion(self, timeout: int = 30) -> bool:
        """Wait for upload to complete and return success status"""
        try:
            start_time = time.time()

            while time.time() - start_time < timeout:
                # Check for success notification
                try:
                    success_msg = self.driver.find_element(
                        By.XPATH, "//div[@class='noty_body']"
                    )
                    if success_msg.is_displayed():
                        message_text = success_msg.text
                        self.logger.info(f"✓ Upload successful: {message_text}")
                        return True
                except:
                    pass
                
                # Check for error notification
                try:
                    error_msg = self.driver.find_element(
                        By.XPATH, "(//div[@class='noty_body'])[1]"
                    )
                    if error_msg.is_displayed():
                        message_text = error_msg.text
                        self.logger.error(f"✗ Upload failed: {message_text}")
                        return False
                except:
                    pass
                
                # Check if modal is closed (indicating completion)
                try:
                    modal = self.driver.find_element(
                        By.XPATH, "//div[contains(@class, 'modal fade') and contains(@class, 'in')]"
                    )
                    if not modal.is_displayed():
                        self.logger.info("✓ Upload modal closed, assuming completion")
                        return True
                except:
                    # Modal not found, might be already closed
                    pass
                
                time.sleep(1)
            
            self.logger.warning("Upload completion check timed out")
            return False
        
        except Exception as e:
            self.logger.error(f"Error waiting for upload completion: {e}")
            return False

    def close_upload_modal(self):
        """Close the upload modal if it's open"""
        try:
            # Try multiple close button selectors
            close_selectors = [
                "//div[contains(@class, 'modal')]//button[@data-dismiss='modal']",
                "//div[@class='modal fade import-products-modal in']//span[@aria-hidden='true'][normalize-space()='×']",
                "div[class='modal fade import-products-modal in'] span[aria-hidden='true']",
                "(//span[@aria-hidden='true'][normalize-space()='×'])[3]",
                "//div[contains(@class, 'modal')]//button[contains(text(), 'Close')]",
                "//div[contains(@class, 'modal')]//span[@aria-hidden='true'][normalize-space()='×']",
                "//button[@aria-label='Close']",
            ]
        
            for selector in close_selectors:
                try:
                    close_button = self.driver.find_element(By.XPATH, selector)
                    if close_button.is_displayed() and close_button.is_enabled():
                        close_button.click()
                        time.sleep(1)
                        self.logger.info("✓ Upload modal closed")
                        break
                except:
                    continue
                
            # If modal is still open, try Escape key
            try:
                modal = self.driver.find_element(
                    By.XPATH, "//div[contains(@class, 'modal fade') and contains(@class, 'in')]"
                )
                if modal.is_displayed():
                    self.driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.ESCAPE)
                    time.sleep(1)
                    self.logger.info("✓ Upload modal closed with Escape key")
            except:
                pass
            
        except Exception as e:
            self.logger.debug(f"Could not close upload modal: {e}")

    def read_csv_items(self, csv_path: str) -> List[Dict]:
        """Read CSV file and extract items with their line numbers"""
        items = []
        try:
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for line_num, row in enumerate(reader, start=2):  # Start at 2 (header is line 1)
                    item_data = {
                        'line_number': line_num,
                        'name': row.get('Name', '').strip(),
                        'item_code': row.get('ItemCode', '').strip(),
                        'barcode': row.get('Barcode', '').strip(),
                        'original_row': row  # Keep original data for reference
                    }
                    if item_data['name']:  # Only include items with names
                        items.append(item_data)
        
            self.logger.info(f"Read {len(items)} items from CSV")
            return items
        
        except Exception as e:
            self.logger.error(f"Error reading CSV file: {e}")
            return []

    def verify_imported_items(self, csv_items: List[Dict]) -> Dict:
        """Verify which items from CSV were actually imported using Name and Batch No"""
        try:
            self.logger.info("=== Verifying imported items against inventory table ===")
        
            # Make sure we're on the inventory page
            # self.navigate_to_inventory_items()
            time.sleep(3)  # Give extra time for table to load
        
            # Get all items currently in the inventory table
            inventory_items = self.get_inventory_table_items()
        
            # Initialize results
            results = {
                'imported_items': [],      # Items found in both CSV and inventory
                'failed_items': [],        # Items in CSV but not in inventory
                'skipped_items': [],       # Items that might have been skipped
                'imported_count': 0,
                'failed_count': 0,
                'skipped_count': 0,
                'duplicate_items': [],     # Items that appear multiple times in CSV
                'table_duplicates': [],    # Duplicate items found in inventory table
                'partial_matches': [],     # Items with name match but batch mismatch
                'verification_errors': []  # Any errors during verification
            }
        
            if not inventory_items:
                self.logger.warning("No items found in inventory table - may be empty or table not loaded")
                # All CSV items are considered failed
                for csv_item in csv_items:
                    results['failed_items'].append({
                        'csv_line': csv_item['line_number'],
                        'csv_name': csv_item['name'],
                        'csv_batch': csv_item.get('original_row', {}).get('Batch', ''),
                        'reason': 'Inventory table appears empty or not loaded'
                    })
                    results['failed_count'] += 1
                return results
        
            # Create lookup dictionary: key = (name_lower, batch_lower)
            inventory_lookup = {}
            table_name_counts = {}  # Track duplicates in table

            for inv_item in inventory_items:
                name_key = inv_item['name'].lower()
                batch_key = inv_item.get('batch', '').lower()
            
                # Create composite key
                composite_key = f"{name_key}|{batch_key}"
            
                # Check for duplicates in table
                if composite_key in inventory_lookup:
                    if composite_key not in results['table_duplicates']:
                        results['table_duplicates'].append({
                            'name': inv_item['name'],
                            'batch': inv_item.get('batch', ''),
                            'count': 2  # Starting count
                        })
                    else:
                        # Increment count for existing duplicate
                        for dup in results['table_duplicates']:
                            if dup['name'].lower() == name_key and dup['batch'].lower() == batch_key:
                                dup['count'] += 1
                                break
                else:
                    inventory_lookup[composite_key] = inv_item
            
                # Track name counts for duplicate detection
                table_name_counts[name_key] = table_name_counts.get(name_key, 0) + 1

            # Track found items to avoid double counting
            found_composite_keys = set()
        
            # Check each CSV item against inventory
            for csv_item in csv_items:
                csv_name = csv_item['name'].lower()
                csv_batch = csv_item.get('original_row', {}).get('Batch', '').lower()
            
                composite_key = f"{csv_name}|{csv_batch}"
            
                # Try exact match (name + batch)
                if composite_key in inventory_lookup:
                    inv_item = inventory_lookup[composite_key]
                    results['imported_items'].append({
                        'csv_line': csv_item['line_number'],
                        'csv_name': csv_item['name'],
                        'csv_batch': csv_item.get('original_row', {}).get('Batch', ''),
                        'inventory_name': inv_item['name'],
                        'inventory_batch': inv_item.get('batch', ''),
                        'match_type': 'exact',
                        'match_details': f"Name: '{csv_item['name']}', Batch: '{csv_item.get('original_row', {}).get('Batch', '')}'"
                    })
                    results['imported_count'] += 1
                    found_composite_keys.add(composite_key)
                
                # Try name-only match (batch might be different or empty)
                elif csv_name in [item['name'].lower() for item in inventory_items]:
                    # Find all inventory items with this name
                    matching_items = [item for item in inventory_items if item['name'].lower() == csv_name]
                
                    if len(matching_items) == 1:
                        # Single match by name
                        inv_item = matching_items[0]
                        results['imported_items'].append({
                            'csv_line': csv_item['line_number'],
                            'csv_name': csv_item['name'],
                            'csv_batch': csv_item.get('original_row', {}).get('Batch', ''),
                            'inventory_name': inv_item['name'],
                            'inventory_batch': inv_item.get('batch', ''),
                            'match_type': 'name_only',
                            'match_details': f"Name matched but batch differs: CSV='{csv_item.get('original_row', {}).get('Batch', '')}', Inventory='{inv_item.get('batch', '')}'",
                            'warning': 'Batch number mismatch'
                        })
                        results['imported_count'] += 1
                        found_composite_keys.add(f"{csv_name}|{inv_item.get('batch', '').lower()}")
                    
                    elif len(matching_items) > 1:
                        # Multiple items with same name - partial match
                        results['partial_matches'].append({
                            'csv_line': csv_item['line_number'],
                            'csv_name': csv_item['name'],
                            'csv_batch': csv_item.get('original_row', {}).get('Batch', ''),
                            'matching_inventory_items': [
                                {'name': item['name'], 'batch': item.get('batch', '')} 
                                for item in matching_items
                            ],
                            'match_type': 'multiple_name_matches'
                        })
                        # Count as imported but with warning
                        results['imported_items'].append({
                            'csv_line': csv_item['line_number'],
                            'csv_name': csv_item['name'],
                            'csv_batch': csv_item.get('original_row', {}).get('Batch', ''),
                            'inventory_name': csv_item['name'],
                            'inventory_batch': 'MULTIPLE',
                            'match_type': 'multiple_name_matches',
                            'match_details': f"Multiple inventory items with name '{csv_item['name']}'",
                            'warning': 'Multiple items with same name found'
                        })
                        results['imported_count'] += 1
                    
                # Item not found at all
                else:
                    results['failed_items'].append({
                        'csv_line': csv_item['line_number'],
                        'csv_name': csv_item['name'],
                        'csv_batch': csv_item.get('original_row', {}).get('Batch', ''),
                        'reason': 'No matching item found in inventory table',
                        'search_criteria': f"Name: '{csv_item['name']}', Batch: '{csv_item.get('original_row', {}).get('Batch', '')}'"
                    })
                    results['failed_count'] += 1
        
            # Check for duplicate items in CSV
            csv_name_batch_counts = {}
            for csv_item in csv_items:
                csv_name = csv_item['name'].lower()
                csv_batch = csv_item.get('original_row', {}).get('Batch', '').lower()
                key = f"{csv_name}|{csv_batch}"
                csv_name_batch_counts[key] = csv_name_batch_counts.get(key, 0) + 1
        
            for key, count in csv_name_batch_counts.items():
                if count > 1:
                    name, batch = key.split('|')
                    duplicate_items = [
                        item for item in csv_items 
                        if item['name'].lower() == name and 
                        item.get('original_row', {}).get('Batch', '').lower() == batch
                    ]
                    results['duplicate_items'].append({
                        'name': name,
                        'batch': batch if batch else '(empty)',
                        'count': count,
                        'lines': [item['line_number'] for item in duplicate_items]
                    })
        
            self.logger.info(f"Verification complete: {results['imported_count']} imported, {results['failed_count']} failed")

            return results
        
        except Exception as e:
            self.logger.error(f"Error verifying imported items: {e}")
            self.take_screenshot("import_verification_error")
            return {
                'imported_items': [],
                'failed_items': [],
                'skipped_items': [],
                'imported_count': 0,
                'failed_count': len(csv_items),
                'skipped_count': 0,
                'duplicate_items': [],
                'table_duplicates': [],
                'partial_matches': [],
                'verification_errors': [str(e)]
            }
        
    def get_inventory_table_items(self) -> List[Dict]:
        """Extract items from the inventory table with Name and Batch No columns"""
        items = []
        try:
            # Wait for table to load
            time.sleep(3)

            view_all_items_button = self.wait.until(
                EC.element_to_be_clickable((By.XPATH, "//button[@id='btnfilterproducts']"))
            )
            view_all_items_button.click()
            time.sleep(3)
        
            # Try different table selectors
            table_selectors = [
                "//table[@id='inventoryitemstable']",
                "#inventoryitemstable",
                "(//table[@id='inventoryitemstable'])[1]"
            ]
        
            table = None
            for selector in table_selectors:
                try:
                    table = self.driver.find_element(By.XPATH, selector)
                    self.logger.info(f"Found inventory table with selector: {selector}")
                    break
                except:
                    continue
        
            if not table:
                self.logger.warning("Inventory table not found with any selector")
                # Take screenshot for debugging
                self.take_screenshot("inventory_table_not_found")
                return items
        
            # Get all rows (skip header if present)
            rows = []
            try:
                rows = table.find_elements(By.XPATH, "//table[@id='inventoryitemstable']/tbody/tr")
            except:
                # Try without tbody
                rows = table.find_elements(By.XPATH, ".//tr")
        
            if not rows:
                self.logger.warning("No rows found in inventory table")
                return items
        
            self.logger.info(f"Found {len(rows)} rows in inventory table")
        
            # Determine column indices by checking header
            header_cells = []
            try:
                header_row = table.find_element(By.XPATH, ".//thead/tr") or table.find_element(By.XPATH, ".//tr[1]")
                header_cells = header_row.find_elements(By.TAG_NAME, "th")
                if not header_cells:
                    header_cells = header_row.find_elements(By.TAG_NAME, "td")
            except:
                # If can't find header, assume standard order
                pass
        
            # Log header for debugging
            if header_cells:
                headers = [cell.text.strip() for cell in header_cells]
                self.logger.info(f"Table headers: {headers}")
        
            # Process each data row
            for i, row in enumerate(rows):
                try:
                    # Skip if this looks like a header row
                    if i == 0 and header_cells:
                        continue
                    
                    cells = row.find_elements(By.TAG_NAME, "td")
                    if len(cells) >= 2:  # Need at least Name and Batch
                        # Based on your columns: Name, Batch No, Unit Cost, Unit Price, Total Quantity, Available Quantity
                        item_name = cells[0].text.strip() if len(cells) > 0 else ""
                        item_batch = cells[1].text.strip() if len(cells) > 1 else ""
                        unit_cost = cells[2].text.strip() if len(cells) > 2 else ""
                        unit_price = cells[3].text.strip() if len(cells) > 3 else ""
                        total_qty = cells[4].text.strip() if len(cells) > 4 else ""
                        available_qty = cells[5].text.strip() if len(cells) > 5 else ""
                    
                        if item_name:  # Only include items with names
                            items.append({
                                'name': item_name,
                                'batch': item_batch,
                                'unit_cost': unit_cost,
                                'unit_price': unit_price,
                                'total_quantity': total_qty,
                                'available_quantity': available_qty,
                                'row_index': i
                            })
                        
                            # Log first few items for verification
                            if len(items) <= 5:
                                self.logger.debug(f"Table item {len(items)}: Name='{item_name}', Batch='{item_batch}'")
                    else:
                        self.logger.debug(f"Row {i} has only {len(cells)} cells, skipping")
                    
                except Exception as e:
                    self.logger.debug(f"Error processing table row {i}: {e}")
                    continue
        
            self.logger.info(f"Extracted {len(items)} items from inventory table")
        
            # Log sample of extracted items
            if items:
                self.logger.info("Sample of extracted items (first 3):")
                for i, item in enumerate(items[:3]):
                    self.logger.info(f"  {i+1}. Name: '{item['name']}', Batch: '{item['batch']}'")
        
            return items

        except Exception as e:
            self.logger.error(f"Error reading inventory table: {e}")
            self.take_screenshot("inventory_table_read_error")
            return []


    def log_import_verification_details(self, verification_result: Dict):
        """Log detailed import verification results with Name+Batch focus"""
        self.logger.info("\n" + "="*60)
        self.logger.info("IMPORT VERIFICATION DETAILS (Name + Batch Matching)")
        self.logger.info("="*60)
    
        # Summary
        self.logger.info(f"\nSUMMARY:")
        self.logger.info(f"  Imported successfully: {verification_result['imported_count']}")
        self.logger.info(f"  Failed to import: {verification_result['failed_count']}")
        self.logger.info(f"  Skipped: {verification_result['skipped_count']}")
    
        if verification_result['imported_count'] + verification_result['failed_count'] > 0:
            success_rate = (verification_result['imported_count'] / 
                           (verification_result['imported_count'] + verification_result['failed_count'])) * 100
            self.logger.info(f"  Success Rate: {success_rate:.1f}%")
    
        # Imported items with match types
        if verification_result['imported_items']:
            self.logger.info(f"\nIMPORTED ITEMS ({len(verification_result['imported_items'])}):")

            # Group by match type
            exact_matches = [item for item in verification_result['imported_items'] if item['match_type'] == 'exact']
            name_only_matches = [item for item in verification_result['imported_items'] if item['match_type'] == 'name_only']
            multiple_matches = [item for item in verification_result['imported_items'] if item['match_type'] == 'multiple_name_matches']
        
            if exact_matches:
                self.logger.info(f"  Exact matches (Name + Batch): {len(exact_matches)}")
                for item in exact_matches[:5]:
                    self.logger.info(f"    ✓ Line {item['csv_line']}: '{item['csv_name']}' (Batch: '{item['csv_batch']}')")
                if len(exact_matches) > 5:
                    self.logger.info(f"    ... and {len(exact_matches) - 5} more exact matches")
        
            if name_only_matches:
                self.logger.info(f"\n  Name-only matches (Batch differs): {len(name_only_matches)}")
                for item in name_only_matches[:5]:
                    self.logger.info(f"    ⚠ Line {item['csv_line']}: '{item['csv_name']}'")
                    self.logger.info(f"      CSV Batch: '{item['csv_batch']}', Inventory Batch: '{item['inventory_batch']}'")
                if len(name_only_matches) > 5:
                    self.logger.info(f"    ... and {len(name_only_matches) - 5} more name-only matches")
        
            if multiple_matches:
                self.logger.info(f"\n  Multiple matches (ambiguous): {len(multiple_matches)}")
                for item in multiple_matches[:3]:
                    self.logger.info(f"    ⚠ Line {item['csv_line']}: '{item['csv_name']}' matches multiple inventory items")
    
        # Failed items
        if verification_result['failed_items']:
            self.logger.info(f"\nFAILED ITEMS ({len(verification_result['failed_items'])}):")
            for item in verification_result['failed_items'][:10]:
                batch_info = f", Batch: '{item['csv_batch']}'" if item['csv_batch'] else ""
                self.logger.info(f"  ✗ Line {item['csv_line']}: '{item['csv_name']}'{batch_info}")
                self.logger.info(f"    Reason: {item['reason']}")
            if len(verification_result['failed_items']) > 10:
                self.logger.info(f"  ... and {len(verification_result['failed_items']) - 10} more")
    
        # Duplicate items in CSV
        if verification_result['duplicate_items']:
            self.logger.info(f"\nDUPLICATE ITEMS IN CSV ({len(verification_result['duplicate_items'])}):")
            for dup in verification_result['duplicate_items']:
                batch_info = f" (Batch: {dup['batch']})" if dup['batch'] != '(empty)' else ''
                self.logger.info(f"  ⚠ '{dup['name']}'{batch_info} appears {dup['count']} times on lines: {dup['lines']}")
    
        # Duplicate items in inventory table
        if verification_result.get('table_duplicates'):
            self.logger.info(f"\nDUPLICATE ITEMS IN INVENTORY TABLE ({len(verification_result['table_duplicates'])}):")
            for dup in verification_result['table_duplicates'][:5]:
                batch_info = f" (Batch: {dup['batch']})" if dup['batch'] else ''
                self.logger.info(f"  ⚠ '{dup['name']}'{batch_info} appears {dup['count']} times in table")
    
        # Partial matches
        if verification_result.get('partial_matches'):
            self.logger.info(f"\nPARTIAL/AMBIGUOUS MATCHES ({len(verification_result['partial_matches'])}):")
            for match in verification_result['partial_matches'][:3]:
                self.logger.info(f"  ⚠ Line {match['csv_line']}: '{match['csv_name']}' could match multiple inventory items")
    
        # Save detailed report
        self.save_detailed_import_report(verification_result)

    def save_detailed_import_report(self, verification_result: Dict):
        """Save detailed import report to JSON file"""
        try:
            report_dir = Path("reports/detailed")
            report_dir.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            report_file = report_dir / f"import_verification_{timestamp}.json"
        
            report_data = {
                'timestamp': datetime.now().isoformat(),
                'summary': {
                    'imported': verification_result['imported_count'],
                    'failed': verification_result['failed_count'],
                    'skipped': verification_result['skipped_count'],
                    'success_rate': (
                        (verification_result['imported_count'] / 
                        max(1, verification_result['imported_count'] + verification_result['failed_count'])) * 100
                    ) if (verification_result['imported_count'] + verification_result['failed_count']) > 0 else 0
                },
                'imported_items': verification_result['imported_items'],
                'failed_items': verification_result['failed_items'],
                'duplicate_items': verification_result['duplicate_items'],
                'verification_errors': verification_result.get('verification_errors', [])
            }
        
            with open(report_file, 'w', encoding='utf-8') as f:
                json.dump(report_data, f, indent=2, ensure_ascii=False)
        
            self.logger.info(f"✓ Detailed import report saved to: {report_file}")

        except Exception as e:
            self.logger.error(f"Error saving detailed import report: {e}")

    def import_items_manually_in_panel(self, csv_path: str) -> bool:
        """Fallback: Import items one by one in the Inventory Items panel"""
        try:
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                csv_data = list(reader)

            total_items = len(csv_data)
            success_count = 0
            fail_count = 0

            self.logger.info(
                f"Starting manual import of {total_items} items in Inventory panel"
            )

            for i, item in enumerate(csv_data, 1):
                self.logger.info(
                    f"Importing item {i}/{total_items} in panel: {item['Name']}"
                )

                # Navigate to add item page within the panel
                try:
                    add_button = self.wait.until(
                        EC.element_to_be_clickable(
                            (
                                By.XPATH,
                                "//button[contains(text(), 'Add Item') or contains(text(), 'New Item')]",
                            )
                        )
                    )
                    add_button.click()
                    time.sleep(2)

                    # Fill form fields in the panel
                    form_mapping = {
                        "item_name": item.get("Name", ""),
                        "item_code": item.get("ItemCode", ""),
                        "barcode": item.get("Barcode", ""),
                        "batch": item.get("Batch", ""),
                        "unit_cost": str(item.get("UnitCost", 0)),
                        "unit_price": str(item.get("UnitPrice", 0)),
                        "total_quantity": str(item.get("TotalQuantity", 0)),
                        "reorder_level": str(item.get("ReorderLevel", 0)),
                        "expiry_date": item.get("ExpiryDate", ""),
                    }

                    for field_name, value in form_mapping.items():
                        try:
                            # Try multiple possible selectors
                            selectors = [
                                f"//input[@name='{field_name}']",
                                f"//input[@id='{field_name}']",
                                f"//input[contains(@name, '{field_name}')]",
                            ]

                            for selector in selectors:
                                try:
                                    field = self.driver.find_element(By.XPATH, selector)
                                    field.clear()
                                    field.send_keys(value)
                                    break
                                except:
                                    continue
                        except:
                            continue

                    # Select dropdowns in the panel
                    dropdown_mapping = {
                        "unit_of_measure": item.get("UnitOfMeasure", "").title(),
                        "item_category": item.get("ItemCategory", "").title(),
                        "item_class": item.get("ItemClass", "").title(),
                        "vat_type": item.get("VATType", ""),
                    }

                    for field_name, value in dropdown_mapping.items():
                        try:
                            selectors = [
                                f"//select[@name='{field_name}']",
                                f"//select[@id='{field_name}']",
                                f"//select[contains(@name, '{field_name}')]",
                            ]

                            for selector in selectors:
                                try:
                                    select = Select(
                                        self.driver.find_element(By.XPATH, selector)
                                    )
                                    select.select_by_visible_text(value)
                                    break
                                except:
                                    continue
                        except:
                            self.logger.warning(
                                f"Could not set {field_name} to {value} in panel"
                            )

                    # Save item in the panel
                    save_button = self.driver.find_element(
                        By.XPATH,
                        "//button[@type='submit' and contains(text(), 'Save')]",
                    )
                    save_button.click()
                    time.sleep(3)

                    # Check for success in the panel
                    try:
                        self.driver.find_element(
                            By.XPATH, "//div[contains(@class, 'alert-success')]"
                        )
                        success_count += 1
                        self.logger.info(f"✓ Item imported in panel: {item['Name']}")
                    except:
                        fail_count += 1
                        self.logger.error(
                            f"✗ Failed to import in panel: {item['Name']}"
                        )
                        self.take_screenshot(
                            f"inventory_panel_item_error_{item['Name']}"
                        )

                    # Navigate back to inventory list in the panel
                    self.navigate_to_inventory_items()

                except Exception as e:
                    fail_count += 1
                    self.logger.error(
                        f"✗ Error importing {item['Name']} in panel: {str(e)}"
                    )
                    self.take_screenshot(
                        f"inventory_panel_item_import_error_{item['Name']}"
                    )

                time.sleep(1)  # Delay between items

            self.verification_stats["items_imported"] = success_count
            self.verification_stats["items_failed"] = fail_count

            self.logger.info(
                f"Manual import complete in panel: {success_count} successful, {fail_count} failed"
            )
            return success_count > 0

        except Exception as e:
            self.logger.error(f"✗ Manual import failed in panel: {str(e)}")
            return False

    # ==================== MAIN VERIFICATION AND IMPORT METHODS ====================

    def verify_all_prerequisites(self, csv_data: List[Dict]) -> bool:
        """Verify all prerequisites in required order using panel-specific methods"""
        self.logger.info("=" * 60)
        self.logger.info("STARTING PREREQUISITE VERIFICATION")
        self.logger.info("=" * 60)

        # Define verification steps with panel-specific methods
        verification_steps = [
            ("Chart of Accounts", self.verify_and_create_accounts_in_panel),
            ("Taxes/VAT Types", self.verify_vat_types_in_panel), 
            ("Item Categories", self.verify_and_create_categories_in_panel),
            ("Item Classes", self.verify_and_create_classes_in_panel),
            ("Units of Measure", self.verify_and_create_units_in_panel),
        ]

        for step_name, verification_func in verification_steps:
            self.logger.info(f"\n▶ Processing: {step_name}")
            if not verification_func(csv_data):
                self.logger.error(
                    f"✗ {step_name} verification failed. Stopping import."
                )
                return False

        self.logger.info("=" * 60)
        self.logger.info("✓ ALL PREREQUISITES VERIFIED SUCCESSFULLY")
        self.logger.info("=" * 60)
        return True

    def import_inventory_data(self, csv_path: str) -> bool:
        """Import inventory data after prerequisites are verified"""
        self.logger.info("=" * 60)
        self.logger.info("STARTING INVENTORY IMPORT")
        self.logger.info("=" * 60)

        if self.dry_run:
            self.logger.info("✓ Dry run complete - skipping actual import")
            return True

        return self.upload_inventory_csv_in_panel(csv_path)

    def generate_report(self) -> Dict:
        """Generate comprehensive import report"""
        report = {
            "timestamp": datetime.now().isoformat(),
            "dry_run": self.dry_run,
            "verification_stats": self.verification_stats.copy(),
            "summary": {
                "total_prerequisites_created": (
                    self.verification_stats["accounts_created"]
                    + self.verification_stats["units_created"]
                    + self.verification_stats["categories_created"]
                    + self.verification_stats["classes_created"]
                ),
                "total_items_processed": (
                    self.verification_stats["items_imported"]
                    + self.verification_stats["items_failed"]
                    + self.verification_stats["items_skipped"]
                ),
                "success_rate": (
                    (
                        (
                            self.verification_stats["items_imported"]
                            / max(
                                1,
                                self.verification_stats["items_imported"]
                                + self.verification_stats["items_failed"],
                            )
                        )
                        * 100
                    )
                    if self.verification_stats["items_imported"]
                    + self.verification_stats["items_failed"]
                    > 0
                    else 0
                ),
            },
        }

        # Save report to file
        report_dir = Path("reports")
        report_dir.mkdir(exist_ok=True)

        report_file = (
            report_dir
            / f'import_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        )

        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        # Print summary to console
        print("\n" + "=" * 60)
        print("IMPORT COMPLETION REPORT")
        print("=" * 60)
        print(f"\nPrerequisites Created:")
        print(f"  Accounts: {self.verification_stats['accounts_created']}")
        print(f"  Units of Measure: {self.verification_stats['units_created']}")
        print(f"  Item Categories: {self.verification_stats['categories_created']}")
        print(f"  Item Classes: {self.verification_stats['classes_created']}")
        print(f"\nInventory Items:")
        print(f"  Imported: {self.verification_stats['items_imported']}")
        print(f"  Failed: {self.verification_stats['items_failed']}")
        print(f"  Skipped: {self.verification_stats['items_skipped']}")
        print(f"\nSuccess Rate: {report['summary']['success_rate']:.1f}%")
        print(f"\nReport saved to: {report_file}")
        print("=" * 60)

        return report

    def import_data(self, cleaned_csv_path: str) -> Dict:
        """Main import method with enhanced workflow"""
        try:
            # Read cleaned CSV
            self.logger.info(f"Loading CSV data from: {cleaned_csv_path}")
            with open(cleaned_csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                csv_data = list(reader)

            if not csv_data:
                self.logger.error("✗ CSV file is empty or could not be read")
                return self.verification_stats

            self.logger.info(f"Loaded {len(csv_data)} items from CSV")

            # Step 1: Login once
            if not self.login():
                self.logger.error("✗ Login failed, cannot proceed")
                return self.verification_stats

            # Step 2: Verify all prerequisites in their respective panels
            if not self.verify_all_prerequisites(csv_data):
                self.logger.error("✗ Prerequisite verification failed, aborting import")
                return self.verification_stats

            # Step 3: Import inventory data in the Inventory panel
            import_success = self.import_inventory_data(cleaned_csv_path)
            if not import_success:
                self.logger.error("✗ Inventory import failed")

            # Step 4: Generate report
            report = self.generate_report()

            return self.verification_stats

        except Exception as e:
            self.logger.error(f"✗ Import process failed: {str(e)}")
            self.take_screenshot("import_process_error")
            return self.verification_stats

        finally:
            if self.driver:
                self.driver.quit()
                self.logger.info("Browser session closed")

def run_enhanced_importer():
    """Main function to run the enhanced importer"""
    print("=" * 60)
    print("MEDICENTRE v3 ENHANCED INVENTORY IMPORTER")
    print("=" * 60)
    
    # Ask if user wants to use existing config or create new
    print("\n--- Configuration ---")
    use_existing = input("Load existing configuration? (y/n): ").strip().lower() in ["y", "yes"]
    
    config = None
    if use_existing:
        config_path = input("Config file path (press Enter for default): ").strip()
        if config_path:
            config = ConfigLoader.load_config(config_path)
        else:
            config = ConfigLoader.load_config()
    else:
        config = ConfigLoader.create_new_config(ConfigLoader.DEFAULT_CONFIG_PATH)
    
    if not config:
        print("Failed to load/create configuration. Exiting.")
        return
    
    # Validate essential configuration
    required_fields = ['base_url', 'accesscode', 'branch', 'username', 'password']
    missing_fields = [field for field in required_fields if not config.get(field)]
    
    if missing_fields:
        print(f"\n✗ Missing required configuration fields: {missing_fields}")
        print("Please create a new configuration with all required fields.")
        return
    
    # Extract configuration into required format
    credentials = {
        "accesscode": config.get("accesscode", ""),
        "branch": config.get("branch", ""),
        "username": config.get("username", ""),
        "password": config.get("password", ""),
    }
    
    importer_config = {
        "headless": config.get("headless", False),
        "storage_location": config.get("storage_location", "Main Store"),
        "default_department": config.get("default_department", "Pharmacy"),
        "account_mappings": config.get("account_mappings", {}),
        "vat_default_rate": config.get("vat_default_rate", 16),
        "vat_default_tax_code": config.get("vat_default_tax_code", "E"),
    }
    
    # Get CSV path
    print("\n--- CSV File ---")
    default_csv = config.get("last_csv_path", "")
    csv_path = input(f"Path to cleaned CSV file [{default_csv}]: ").strip()
    if not csv_path:
        csv_path = default_csv
    
    if not csv_path:
        print("✗ Error: No CSV file specified.")
        return
    
    csv_file = Path(csv_path)
    if not csv_file.exists():
        print(f"✗ Error: File '{csv_path}' not found.")
        # Offer to browse
        retry = input("Would you like to browse for the file? (y/n): ").strip().lower()
        if retry in ['y', 'yes']:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            csv_path = filedialog.askopenfilename(title="Select CSV file", filetypes=[("CSV files", "*.csv")])
            if not csv_path:
                print("No file selected. Exiting.")
                return
        else:
            return
    
    # Update last CSV path in config
    config['last_csv_path'] = csv_path
    ConfigLoader.save_config(config)
    
    # Dry run option
    print("\n--- Execution Mode ---")
    dry_run_input = input("Dry run (validate only, no changes)? (y/n): ").strip().lower()
    dry_run = dry_run_input in ["y", "yes"]
    
    if dry_run:
        print("\n⚠  DRY RUN MODE - No changes will be made to the system")
    else:
        print("\n⚠  LIVE MODE - Changes will be made to the system")
    
    confirm = input("\nProceed with import? (y/n): ").strip().lower()
    if confirm not in ["y", "yes"]:
        print("Import cancelled.")
        return
    
    # Create and run importer
    print("\n" + "=" * 60)
    print("STARTING IMPORT PROCESS")
    print("=" * 60)
    
    try:
        importer = MedicentreV3InventoryImporter(
            config.get("base_url", ""),
            credentials,
            importer_config,
            dry_run
        )
        stats = importer.import_data(csv_path)
        
        # Final message
        print("\n" + "=" * 60)
        print("PROCESS COMPLETE")
        print("=" * 60)
        print(f"Configuration saved to: {ConfigLoader.DEFAULT_CONFIG_PATH}")
        print(f"Check the logs directory for detailed execution logs and screenshots.")
        print(f"Check the reports directory for the import summary report.")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n✗ Error during import: {e}")
        print("Check the logs for more details.")


if __name__ == "__main__":
    run_enhanced_importer()