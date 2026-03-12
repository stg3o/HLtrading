#!/usr/bin/env python3
"""
secure_config.py — Secure credential management with encryption
Provides encrypted storage and retrieval of sensitive configuration data.
"""
import os
import json
import base64
import hashlib
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

class SecureConfig:
    """Secure configuration manager with encryption"""
    
    def __init__(self, password: Optional[str] = None, salt_file: str = ".config_salt", 
                 key_file: str = ".config_key"):
        """
        Initialize secure configuration manager
        
        Args:
            password: Master password for encryption (if None, uses environment variable)
            salt_file: File to store salt for key derivation
            key_file: File to store encrypted encryption key
        """
        self.password = password or os.environ.get("CONFIG_PASSWORD")
        if not self.password:
            raise ValueError("CONFIG_PASSWORD environment variable must be set or password provided")
        
        self.salt_file = salt_file
        self.key_file = key_file
        self._fernet = None
        
    def _derive_key(self, salt: bytes) -> bytes:
        """Derive encryption key from password and salt"""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(self.password.encode()))
        return key
    
    def _get_or_create_salt(self) -> bytes:
        """Get existing salt or create new one"""
        if os.path.exists(self.salt_file):
            with open(self.salt_file, 'rb') as f:
                return f.read()
        else:
            # Create new salt
            salt = os.urandom(16)
            with open(self.salt_file, 'wb') as f:
                f.write(salt)
            # Set restrictive permissions
            os.chmod(self.salt_file, 0o600)
            logger.info(f"Created new salt file: {self.salt_file}")
            return salt
    
    def _get_or_create_encrypted_key(self, salt: bytes) -> bytes:
        """Get existing encrypted key or create new one"""
        if os.path.exists(self.key_file):
            with open(self.key_file, 'rb') as f:
                return f.read()
        else:
            # Create new encryption key
            key = Fernet.generate_key()
            fernet = Fernet(self._derive_key(salt))
            encrypted_key = fernet.encrypt(key)
            with open(self.key_file, 'wb') as f:
                f.write(encrypted_key)
            # Set restrictive permissions
            os.chmod(self.key_file, 0o600)
            logger.info(f"Created new encrypted key file: {self.key_file}")
            return encrypted_key
    
    def _get_fernet(self) -> Fernet:
        """Get Fernet cipher instance"""
        if self._fernet is None:
            salt = self._get_or_create_salt()
            encrypted_key = self._get_or_create_encrypted_key(salt)
            
            # Decrypt the encryption key
            fernet = Fernet(self._derive_key(salt))
            key = fernet.decrypt(encrypted_key)
            self._fernet = Fernet(key)
        
        return self._fernet
    
    def encrypt_value(self, value: str) -> str:
        """Encrypt a configuration value"""
        if not value:
            return ""
        
        fernet = self._get_fernet()
        encrypted = fernet.encrypt(value.encode())
        return base64.b64encode(encrypted).decode('utf-8')
    
    def decrypt_value(self, encrypted_value: str) -> str:
        """Decrypt a configuration value"""
        if not encrypted_value:
            return ""
        
        try:
            fernet = self._get_fernet()
            encrypted_bytes = base64.b64decode(encrypted_value.encode())
            decrypted = fernet.decrypt(encrypted_bytes)
            return decrypted.decode('utf-8')
        except Exception as e:
            logger.error(f"Failed to decrypt value: {e}")
            raise ValueError(f"Invalid encrypted value or wrong password: {e}")
    
    def save_config(self, config_data: Dict[str, Any], config_file: str = "secure_config.json"):
        """Save configuration with encrypted sensitive values"""
        sensitive_fields = {
            'HL_PRIVATE_KEY', 'OPENROUTER_API_KEY', 'TELEGRAM_BOT_TOKEN',
            'API_KEY', 'API_SECRET', 'PRIVATE_KEY', 'WALLET_ADDRESS'
        }
        
        encrypted_config = {}
        for key, value in config_data.items():
            if key in sensitive_fields and value:
                encrypted_config[key] = self.encrypt_value(str(value))
            else:
                encrypted_config[key] = value
        
        # Save encrypted configuration
        with open(config_file, 'w') as f:
            json.dump(encrypted_config, f, indent=2)
        
        # Set restrictive permissions
        os.chmod(config_file, 0o600)
        logger.info(f"Saved encrypted configuration to: {config_file}")
    
    def load_config(self, config_file: str = "secure_config.json") -> Dict[str, Any]:
        """Load and decrypt configuration"""
        if not os.path.exists(config_file):
            raise FileNotFoundError(f"Configuration file not found: {config_file}")
        
        with open(config_file, 'r') as f:
            encrypted_config = json.load(f)
        
        decrypted_config = {}
        for key, value in encrypted_config.items():
            if isinstance(value, str) and key.endswith('_ENCRYPTED'):
                # Handle pre-encrypted values
                decrypted_config[key.replace('_ENCRYPTED', '')] = self.decrypt_value(value)
            else:
                decrypted_config[key] = value
        
        logger.info(f"Loaded encrypted configuration from: {config_file}")
        return decrypted_config
    
    def migrate_env_to_secure(self, env_file: str = ".env", config_file: str = "secure_config.json"):
        """Migrate existing .env file to encrypted configuration"""
        if not os.path.exists(env_file):
            logger.warning(f"Environment file not found: {env_file}")
            return
        
        # Load existing environment variables
        config_data = {}
        with open(env_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    config_data[key] = value
        
        # Save as encrypted configuration
        self.save_config(config_data, config_file)
        
        # Backup original .env file
        backup_file = f"{env_file}.backup"
        if not os.path.exists(backup_file):
            import shutil
            shutil.copy2(env_file, backup_file)
            logger.info(f"Backed up original .env to: {backup_file}")
        
        logger.info("Migration completed. Consider removing the original .env file.")


def load_secure_credentials() -> Dict[str, str]:
    """
    Load credentials using secure configuration or fallback to environment variables
    Returns a dictionary of credentials
    """
    credentials = {}
    
    # Try to load from secure configuration first
    try:
        secure_config = SecureConfig()
        config = secure_config.load_config()
        
        # Map configuration keys to expected credential names
        credential_mapping = {
            'HL_WALLET_ADDRESS': 'HL_WALLET_ADDRESS',
            'HL_PRIVATE_KEY': 'HL_PRIVATE_KEY', 
            'OPENROUTER_API_KEY': 'OPENROUTER_API_KEY',
            'TELEGRAM_BOT_TOKEN': 'TELEGRAM_BOT_TOKEN',
            'TELEGRAM_CHAT_ID': 'TELEGRAM_CHAT_ID'
        }
        
        for config_key, env_key in credential_mapping.items():
            if config_key in config:
                credentials[env_key] = config[config_key]
        
        if credentials:
            logger.info("Loaded credentials from secure configuration")
            return credentials
            
    except Exception as e:
        logger.warning(f"Failed to load secure configuration: {e}")
    
    # Fallback to environment variables
    logger.info("Falling back to environment variables")
    credential_keys = [
        'HL_WALLET_ADDRESS', 'HL_PRIVATE_KEY', 'OPENROUTER_API_KEY',
        'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID'
    ]
    
    for key in credential_keys:
        value = os.environ.get(key)
        if value:
            credentials[key] = value
    
    return credentials


def setup_secure_config():
    """Interactive setup for secure configuration"""
    print("🔐 Secure Configuration Setup")
    print("=" * 40)
    
    password = input("Enter master password for encryption: ")
    if not password:
        print("❌ Password is required")
        return
    
    confirm_password = input("Confirm master password: ")
    if password != confirm_password:
        print("❌ Passwords do not match")
        return
    
    # Set password as environment variable for this session
    os.environ["CONFIG_PASSWORD"] = password
    
    secure_config = SecureConfig(password)
    
    # Collect credentials
    credentials = {}
    print("\n📋 Enter your credentials (leave empty to skip):")
    
    credential_prompts = {
        'HL_WALLET_ADDRESS': 'Hyperliquid Wallet Address',
        'HL_PRIVATE_KEY': 'Hyperliquid Private Key',
        'OPENROUTER_API_KEY': 'OpenRouter API Key',
        'TELEGRAM_BOT_TOKEN': 'Telegram Bot Token',
        'TELEGRAM_CHAT_ID': 'Telegram Chat ID'
    }
    
    for key, prompt in credential_prompts.items():
        value = input(f"{prompt}: ")
        if value:
            credentials[key] = value
    
    if credentials:
        secure_config.save_config(credentials)
        print("✅ Secure configuration saved!")
        
        # Create example .env file with placeholders
        env_content = """# Example .env file with secure configuration
# Credentials are now stored encrypted in secure_config.json
# Set CONFIG_PASSWORD environment variable to access them

# Optional: Keep non-sensitive configuration here
TESTNET=true
DEBUG=false

# For development, you can still use direct environment variables:
# HL_WALLET_ADDRESS=your_address
# HL_PRIVATE_KEY=your_private_key
"""
        
        with open(".env.example", 'w') as f:
            f.write(env_content)
        
        print("📝 Created .env.example file")
    else:
        print("⚠️  No credentials provided")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "setup":
        setup_secure_config()
    else:
        print("Usage: python3 secure_config.py setup")
        print("Or import and use the SecureConfig class directly")