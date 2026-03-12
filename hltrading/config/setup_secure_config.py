#!/usr/bin/env python3
"""
setup_secure_config.py — Interactive setup for secure credential management
"""
import os
import sys
from hltrading.config.secure_config import setup_secure_config


def main():
    """Main setup function"""
    print("🔐 Crypto Futures Scalping Bot - Secure Configuration Setup")
    print("=" * 60)
    print()
    print("This will help you set up encrypted credential storage.")
    print("Your API keys and sensitive data will be encrypted at rest.")
    print()

    if os.environ.get("CONFIG_PASSWORD"):
        print("✅ CONFIG_PASSWORD environment variable is already set")
    else:
        print("⚠️  CONFIG_PASSWORD environment variable not set")
        print("   You'll need to set this before running the bot")
        print("   Example: export CONFIG_PASSWORD='your_password'")
        print()

    setup_secure_config()

    print()
    print("📋 Next steps:")
    print("1. Set the CONFIG_PASSWORD environment variable")
    print("2. Update your bot scripts to use secure_config.py")
    print("3. Test the configuration with: python3 -c 'from hltrading.config.secure_config import load_secure_credentials; print(load_secure_credentials())'")
    print()
    print("🔒 Your credentials are now encrypted and secure!")


__all__ = [
    "os",
    "sys",
    "setup_secure_config",
    "main",
]
