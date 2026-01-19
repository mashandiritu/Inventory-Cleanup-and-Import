# manage_config.py
import json
from pathlib import Path
from config_loader import ConfigLoader

def manage_configuration():
    """Interactive configuration management utility"""
    print("=" * 60)
    print("MEDICENTRE CONFIGURATION MANAGER")
    print("=" * 60)
    
    while True:
        print("\nOptions:")
        print("  1. Create new configuration")
        print("  2. View current configuration")
        print("  3. Update specific field")
        print("  4. Test configuration (validate)")
        print("  5. Export configuration")
        print("  6. Import configuration")
        print("  7. Exit")
        
        choice = input("\nSelect option (1-7): ").strip()
        
        if choice == "1":
            config = ConfigLoader.create_new_config(ConfigLoader.DEFAULT_CONFIG_PATH)
            
        elif choice == "2":
            try:
                with open(ConfigLoader.DEFAULT_CONFIG_PATH, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                print("\nCurrent Configuration:")
                print("=" * 40)
                print(json.dumps(config, indent=2))
                print("=" * 40)
            except FileNotFoundError:
                print("No configuration file found.")
                
        elif choice == "3":
            try:
                with open(ConfigLoader.DEFAULT_CONFIG_PATH, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                
                print("\nCurrent configuration keys:")
                for key in config.keys():
                    print(f"  - {key}")
                
                field = input("\nEnter field to update: ").strip()
                if field in config:
                    new_value = input(f"Enter new value for '{field}': ").strip()
                    # Try to convert to appropriate type
                    if new_value.lower() == 'true':
                        new_value = True
                    elif new_value.lower() == 'false':
                        new_value = False
                    elif new_value.isdigit():
                        new_value = int(new_value)
                    
                    ConfigLoader.update_config_field(ConfigLoader.DEFAULT_CONFIG_PATH, field, new_value)
                else:
                    print(f"Field '{field}' not found in configuration.")
                    
            except FileNotFoundError:
                print("No configuration file found.")
                
        elif choice == "4":
            config = ConfigLoader.load_config()
            if config:
                print("\n✓ Configuration loaded successfully")
                print(f"  URL: {config.get('base_url', 'Not set')}")
                print(f"  Username: {config.get('username', 'Not set')}")
                print(f"  Storage: {config.get('storage_location', 'Not set')}")
                
        elif choice == "5":
            try:
                with open(ConfigLoader.DEFAULT_CONFIG_PATH, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                
                export_path = input("Export file path: ").strip()
                if export_path:
                    with open(export_path, 'w', encoding='utf-8') as f:
                        json.dump(config, f, indent=2, ensure_ascii=False)
                    print(f"✓ Configuration exported to: {export_path}")
                    
            except FileNotFoundError:
                print("No configuration file found.")
                
        elif choice == "6":
            import_path = input("Import file path: ").strip()
            if Path(import_path).exists():
                with open(import_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                ConfigLoader.save_config(config, ConfigLoader.DEFAULT_CONFIG_PATH)
                print("✓ Configuration imported successfully")
            else:
                print(f"File not found: {import_path}")
                
        elif choice == "7":
            print("Exiting configuration manager.")
            break
            
        else:
            print("Invalid choice. Please try again.")

if __name__ == "__main__":
    manage_configuration()