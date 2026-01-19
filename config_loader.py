# config_loader.py
import json
from pathlib import Path
from typing import Dict, Any, Optional
import os


class ConfigLoader:
    """Load configuration from file or create new configuration"""
    
    DEFAULT_CONFIG_PATH = Path("medicentre_config.json")
    
    @staticmethod
    def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
        """Load configuration from file or create new if doesn't exist"""
        if config_path:
            config_file = Path(config_path)
        else:
            config_file = ConfigLoader.DEFAULT_CONFIG_PATH
        
        if config_file.exists():
            print(f"Loading configuration from: {config_file}")
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                print("✓ Configuration loaded successfully")
                return config
            except Exception as e:
                print(f"✗ Error loading configuration: {e}")
                return ConfigLoader.create_new_config(config_file)
        else:
            print(f"No configuration file found at: {config_file}")
            return ConfigLoader.create_new_config(config_file)
    
    @staticmethod
    def create_new_config(config_file: Path) -> Dict[str, Any]:
        """Create a new configuration through interactive prompts"""
        print("\n" + "="*60)
        print("CREATING NEW CONFIGURATION")
        print("="*60)
        
        config = {}
        
        # System settings
        print("\n--- System Settings ---")
        config['headless'] = input("Run in headless mode? (y/n): ").strip().lower() in ["y", "yes"]
        config['storage_location'] = input("Storage Location (e.g., 'Main Store'): ").strip() or "Main Store"
        config['default_department'] = input("Default department for new categories (e.g., 'Pharmacy'): ").strip() or "Pharmacy"
        
        # Authentication
        print("\n--- Authentication ---")
        config['base_url'] = input("Medicentre v3 URL: ").strip()
        config['accesscode'] = input("Access Code: ").strip()
        config['branch'] = input("Branch: ").strip()
        config['username'] = input("Username: ").strip()
        config['password'] = input("Password: ").strip()
        
        # Account mappings
        print("\n--- Account Mappings (Optional - can be configured later) ---")
        print("These are the main accounts that sub-accounts will be created under.")
        print("Press Enter to use defaults or specify custom names.")
        
        config['account_mappings'] = {
            'inventory_main': input("Inventory main account [Inventory]: ").strip() or "Inventory",
            'inventory_class': input("Inventory account class [Current Assets]: ").strip() or "Current Assets",
            'revenue_main': input("Revenue main account [Revenue]: ").strip() or "Revenue",
            'revenue_class': input("Revenue account class [Income]: ").strip() or "Income",
            'cost_main': input("Cost of Sales main account [Cost of Goods Sold]: ").strip() or "Cost of Goods Sold",
            'cost_class': input("Cost of Sales account class [Cost of Goods Sold]: ").strip() or "Cost of Goods Sold"
        }
        
        # VAT configurations (can be extended)
        print("\n--- VAT Defaults (Optional) ---")
        config['vat_default_rate'] = input("Default VAT rate if not specified (0-100) [16]: ").strip()
        config['vat_default_rate'] = int(config['vat_default_rate']) if config['vat_default_rate'].isdigit() else 16
        
        config['vat_default_tax_code'] = input("Default VAT tax code [E]: ").strip() or "E"
        
        # File paths
        print("\n--- File Paths ---")
        config['last_csv_path'] = input("Default CSV file path: ").strip() or ""
        
        # Additional settings
        print("\n--- Additional Settings ---")
        config['default_timeout'] = 30
        config['enable_screenshots'] = True
        config['screenshot_dir'] = "logs/screenshots"
        config['log_dir'] = "logs"
        
        # Save the configuration
        ConfigLoader.save_config(config, config_file)
        
        return config
    
    @staticmethod
    def save_config(config: Dict[str, Any], config_file: Optional[Path] = None):
        """Save configuration to file"""
        if not config_file:
            config_file = ConfigLoader.DEFAULT_CONFIG_PATH
        
        try:
            config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            print(f"✓ Configuration saved to: {config_file}")
        except Exception as e:
            print(f"✗ Error saving configuration: {e}")
    
    @staticmethod
    def update_config_field(config_file: Path, field_path: str, value: Any):
        """Update a specific field in the configuration"""
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # Navigate through nested structure
            keys = field_path.split('.')
            current = config
            for key in keys[:-1]:
                if key not in current:
                    current[key] = {}
                current = current[key]
            current[keys[-1]] = value
            
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            
            print(f"✓ Updated {field_path} = {value}")
            
        except Exception as e:
            print(f"✗ Error updating configuration: {e}")