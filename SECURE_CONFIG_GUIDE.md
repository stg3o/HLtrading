# Secure Configuration Guide

This guide explains how to set up and use the encrypted credential storage system for the crypto futures scalping bot.

## Overview

The secure configuration system provides:
- **Encrypted credential storage** at rest and in transit
- **Environment variable fallback** for development
- **Secure file permissions** (600) for sensitive files
- **Master password protection** with PBKDF2 key derivation
- **Migration tools** for existing `.env` files

## Quick Start

### 1. Set up secure configuration

```bash
# Run the interactive setup
python3 setup_secure_config.py

# Set your master password when prompted
# Enter your API keys and credentials
```

### 2. Set the master password environment variable

```bash
# For current session
export CONFIG_PASSWORD="your_master_password"

# For permanent use, add to your shell profile
echo 'export CONFIG_PASSWORD="your_master_password"' >> ~/.zshrc
```

### 3. Update your bot scripts

Replace imports from `config.py` to `config_secure.py`:

```python
# Before
from config import HL_WALLET_ADDRESS, HL_PRIVATE_KEY

# After  
from config_secure import HL_WALLET_ADDRESS, HL_PRIVATE_KEY
```

## Security Features

### 🔐 Encryption
- Uses AES-256 encryption via the `cryptography` library
- PBKDF2 key derivation with 100,000 iterations
- Salt-based key derivation for protection against rainbow table attacks

### 📁 File Permissions
- All secure files are created with 600 permissions (owner read/write only)
- Automatic permission validation on startup
- Warning if files are accessible by group or others

### 🔄 Fallback System
- Falls back to environment variables if secure config fails
- Graceful degradation for development environments
- Clear error messages for troubleshooting

## File Structure

```
project_root/
├── .config_salt          # Salt for key derivation (600 permissions)
├── .config_key           # Encrypted encryption key (600 permissions)  
├── secure_config.json    # Encrypted credentials (600 permissions)
├── setup_secure_config.py # Interactive setup script
├── secure_config.py      # Core encryption library
└── config_secure.py      # Secure configuration module
```

## Migration from .env

If you have an existing `.env` file, the system can migrate it:

```python
from secure_config import SecureConfig

secure_config = SecureConfig()
secure_config.migrate_env_to_secure()
```

This will:
1. Read your existing `.env` file
2. Encrypt the credentials and save to `secure_config.json`
3. Backup your original `.env` file as `.env.backup`
4. Warn you to remove the original `.env` file

## Development Workflow

### For Development

Keep sensitive credentials in the secure config, but you can still use environment variables for non-sensitive configuration:

```bash
# Set master password
export CONFIG_PASSWORD="dev_password"

# Use environment variables for non-sensitive config
export TESTNET=true
export DEBUG=true
```

### For Production

1. Set up secure configuration on the production server
2. Set `CONFIG_PASSWORD` as a system environment variable
3. Remove any `.env` files containing sensitive data
4. Verify file permissions are correct

## Troubleshooting

### "CONFIG_PASSWORD environment variable not set"

```bash
# Set the password
export CONFIG_PASSWORD="your_password"

# Or add to your shell profile for persistence
echo 'export CONFIG_PASSWORD="your_password"' >> ~/.zshrc
```

### "Failed to load secure configuration"

Check that these files exist and have correct permissions:
```bash
ls -la .config_salt .config_key secure_config.json
# Should show: -rw------- (600 permissions)
```

### "Required credential not found"

1. Run the setup script again: `python3 setup_secure_config.py`
2. Verify your master password is correct
3. Check that credentials are properly encrypted in `secure_config.json`

## Security Best Practices

### 🔒 Password Management
- Use a strong, unique master password
- Don't reuse passwords from other systems
- Consider using a password manager to store the master password

### 📂 File Security
- Never commit secure files to version control
- Use proper file permissions (600)
- Regularly audit file access logs

### 🌐 Network Security
- Use VPN when accessing production systems
- Enable firewall rules to restrict access
- Monitor for unauthorized access attempts

### 🔄 Backup Strategy
- Backup encrypted credentials securely
- Store backups in separate, secure locations
- Test restore procedures regularly

## API Reference

### SecureConfig Class

```python
from secure_config import SecureConfig

# Initialize with password
secure_config = SecureConfig(password="your_password")

# Or use environment variable
secure_config = SecureConfig()  # Uses CONFIG_PASSWORD env var

# Encrypt a value
encrypted = secure_config.encrypt_value("sensitive_data")

# Decrypt a value
decrypted = secure_config.decrypt_value(encrypted)

# Save configuration
config_data = {
    "API_KEY": "your_api_key",
    "PRIVATE_KEY": "your_private_key"
}
secure_config.save_config(config_data)

# Load configuration
config = secure_config.load_config()
```

### load_secure_credentials() Function

```python
from secure_config import load_secure_credentials

# Load credentials with fallback to environment variables
credentials = load_secure_credentials()

# Returns dict with available credentials
print(credentials)  # {'API_KEY': 'value', 'PRIVATE_KEY': 'value'}
```

## Integration Examples

### With config_secure.py

```python
# config_secure.py handles all the complexity
from config_secure import HL_WALLET_ADDRESS, HL_PRIVATE_KEY

# Credentials are automatically loaded from secure config
# Falls back to environment variables if needed
```

### Custom Integration

```python
from secure_config import load_secure_credentials

def get_api_credentials():
    credentials = load_secure_credentials()
    
    if 'API_KEY' in credentials and 'API_SECRET' in credentials:
        return credentials['API_KEY'], credentials['API_SECRET']
    else:
        raise ValueError("API credentials not found")
```

## Security Validation

The system includes automatic security validation:

```python
from config_secure import validate_security

# Check if security is properly configured
if validate_security():
    print("✅ Security validation passed")
else:
    print("❌ Security validation failed")
```

This checks:
- CONFIG_PASSWORD is set
- Secure files exist
- File permissions are correct (600)
- No sensitive data in plain text files

## Next Steps

1. **Set up secure configuration** using the setup script
2. **Update your bot scripts** to use `config_secure.py`
3. **Test the configuration** in a safe environment
4. **Deploy to production** with proper security measures
5. **Monitor and maintain** the security of your credentials

For additional security measures, see the [Security Review](SECURITY_REVIEW.md) document.