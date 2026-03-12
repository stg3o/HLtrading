"""
certificate_pinning.py — Certificate pinning for critical endpoints
Implements HTTP Public Key Pinning (HPKP) and certificate validation
"""
import ssl
import hashlib
import socket
import requests
from datetime import datetime, timedelta
from urllib.parse import urlparse
from colorama import Fore, Style
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class CertificatePinner:
    """Certificate pinning implementation for critical endpoints."""

    def __init__(self):
        self.pinned_certificates = {}
        self.pinning_config = {}

    def add_pinned_certificate(self, hostname: str, sha256_fingerprint: str,
                             expires_days: int = 90) -> None:
        """Add a pinned certificate for a hostname."""
        self.pinned_certificates[hostname] = {
            'sha256_fingerprint': sha256_fingerprint,
            'pinned_at': datetime.now(),
            'expires_at': datetime.now() + timedelta(days=expires_days),
            'hostname': hostname
        }
        logger.info(f"Added pinned certificate for {hostname}")

    def get_certificate_fingerprint(self, hostname: str, port: int = 443):
        """Get the SHA-256 fingerprint of a server's certificate."""
        try:
            context = ssl.create_default_context()
            with socket.create_connection((hostname, port), timeout=10) as sock:
                with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                    cert = ssock.getpeercert(binary_form=True)
                    fingerprint = hashlib.sha256(cert).hexdigest()
                    return fingerprint
        except Exception as e:
            logger.error(f"Failed to get certificate for {hostname}: {e}")
            return None

    def validate_certificate_pinning(self, hostname: str, port: int = 443):
        """Validate certificate pinning for a hostname."""
        result = {
            'hostname': hostname,
            'port': port,
            'timestamp': datetime.now().isoformat(),
            'pinned': False,
            'valid': False,
            'certificate_fingerprint': None,
            'pinned_fingerprint': None,
            'match': False,
            'errors': [],
            'warnings': []
        }

        if hostname not in self.pinned_certificates:
            result['errors'].append(f"No pinned certificate found for {hostname}")
            return result

        pinned_cert = self.pinned_certificates[hostname]
        result['pinned'] = True
        result['pinned_fingerprint'] = pinned_cert['sha256_fingerprint']

        if datetime.now() > pinned_cert['expires_at']:
            result['warnings'].append(f"Pinning configuration expired for {hostname}")

        current_fingerprint = self.get_certificate_fingerprint(hostname, port)
        if not current_fingerprint:
            result['errors'].append("Failed to retrieve current certificate")
            return result

        result['certificate_fingerprint'] = current_fingerprint

        if current_fingerprint == pinned_cert['sha256_fingerprint']:
            result['valid'] = True
            result['match'] = True
        else:
            result['valid'] = False
            result['match'] = False
            result['errors'].append("Certificate fingerprint mismatch")

        return result

    def pin_critical_endpoints(self):
        """Pin certificates for critical endpoints used by the trading system."""
        print(f"{Fore.CYAN}Pinning certificates for critical endpoints...{Style.RESET_ALL}")

        critical_endpoints = [
            ('api.hyperliquid.xyz', 443),
            ('query1.finance.yahoo.com', 443),
            ('api.telegram.org', 443),
        ]

        results = {}

        for hostname, port in critical_endpoints:
            print(f"  Pinning {hostname}:{port}...")
            fingerprint = self.get_certificate_fingerprint(hostname, port)
            if fingerprint:
                self.add_pinned_certificate(hostname, fingerprint)
                results[hostname] = {
                    'status': 'pinned',
                    'fingerprint': fingerprint,
                    'port': port
                }
                print(f"    ✅ Pinned: {fingerprint[:16]}...")
            else:
                results[hostname] = {
                    'status': 'failed',
                    'error': 'Could not retrieve certificate'
                }
                print(f"    ❌ Failed to pin")

        return results

    def validate_all_pinned_endpoints(self):
        """Validate all pinned endpoints."""
        print(f"{Fore.CYAN}Validating all pinned endpoints...{Style.RESET_ALL}")

        validation_results = {}
        total_endpoints = len(self.pinned_certificates)
        valid_endpoints = 0
        invalid_endpoints = 0

        for hostname in self.pinned_certificates:
            result = self.validate_certificate_pinning(hostname)
            validation_results[hostname] = result

            if result['valid']:
                valid_endpoints += 1
                print(f"  ✅ {hostname}: Valid")
            else:
                invalid_endpoints += 1
                print(f"  ❌ {hostname}: Invalid")
                for error in result.get('errors', []):
                    print(f"    Error: {error}")

        summary = {
            'total_endpoints': total_endpoints,
            'valid_endpoints': valid_endpoints,
            'invalid_endpoints': invalid_endpoints,
            'validation_results': validation_results
        }

        return summary

    def create_pinning_config_file(self, filename: str = "certificate_pinning_config.json") -> None:
        """Create a configuration file with pinned certificates."""
        config = {
            'pinned_certificates': self.pinned_certificates,
            'created_at': datetime.now().isoformat(),
            'version': '1.0'
        }

        with open(filename, 'w') as f:
            import json
            json.dump(config, f, indent=2, default=str)

        print(f"{Fore.GREEN}Certificate pinning configuration saved to {filename}{Style.RESET_ALL}")

    def load_pinning_config_file(self, filename: str = "certificate_pinning_config.json") -> bool:
        """Load pinned certificates from configuration file."""
        try:
            with open(filename, 'r') as f:
                import json
                config = json.load(f)

            self.pinned_certificates = config.get('pinned_certificates', {})
            print(f"{Fore.GREEN}Loaded {len(self.pinned_certificates)} pinned certificates{Style.RESET_ALL}")
            return True
        except FileNotFoundError:
            print(f"{Fore.YELLOW}No existing pinning configuration found{Style.RESET_ALL}")
            return False
        except Exception as e:
            print(f"{Fore.RED}Error loading pinning configuration: {e}{Style.RESET_ALL}")
            return False


class SecureHTTPClient:
    """HTTP client with certificate pinning validation."""

    def __init__(self, certificate_pinner: CertificatePinner):
        self.certificate_pinner = certificate_pinner
        self.session = requests.Session()

        self.session.verify = True
        self.session.headers.update({
            'User-Agent': 'TradingBot/1.0 (Secure Client)'
        })

    def get(self, url: str, **kwargs) -> requests.Response:
        """Make a GET request with certificate pinning validation."""
        parsed_url = urlparse(url)
        hostname = parsed_url.hostname

        if hostname in self.certificate_pinner.pinned_certificates:
            validation_result = self.certificate_pinner.validate_certificate_pinning(hostname)

            if not validation_result['valid']:
                error_msg = f"Certificate pinning validation failed for {hostname}"
                logger.error(error_msg)
                raise requests.exceptions.SSLError(error_msg)

        return self.session.get(url, **kwargs)

    def post(self, url: str, **kwargs) -> requests.Response:
        """Make a POST request with certificate pinning validation."""
        parsed_url = urlparse(url)
        hostname = parsed_url.hostname

        if hostname in self.certificate_pinner.pinned_certificates:
            validation_result = self.certificate_pinner.validate_certificate_pinning(hostname)

            if not validation_result['valid']:
                error_msg = f"Certificate pinning validation failed for {hostname}"
                logger.error(error_msg)
                raise requests.exceptions.SSLError(error_msg)

        return self.session.post(url, **kwargs)


def main():
    """Main function to demonstrate certificate pinning."""
    print(f"{Fore.CYAN}Starting Certificate Pinning System...{Style.RESET_ALL}")

    pinner = CertificatePinner()
    pinner.load_pinning_config_file()
    pinning_results = pinner.pin_critical_endpoints()
    validation_summary = pinner.validate_all_pinned_endpoints()
    pinner.create_pinning_config_file()
    secure_client = SecureHTTPClient(pinner)

    try:
        response = secure_client.get('https://www.google.com', timeout=5)
        print(f"  ✅ Secure connection test successful: {response.status_code}")
    except Exception as e:
        print(f"  ❌ Secure connection test failed: {e}")

    print(f"\n{Fore.CYAN}{'='*60}")
    print(f"CERTIFICATE PINNING SUMMARY")
    print(f"{'='*60}{Style.RESET_ALL}")

    print(f"Total endpoints pinned: {len(pinning_results)}")
    print(f"Successfully pinned: {sum(1 for r in pinning_results.values() if r['status'] == 'pinned')}")
    print(f"Validation results:")
    print(f"  Valid endpoints: {validation_summary['valid_endpoints']}")
    print(f"  Invalid endpoints: {validation_summary['invalid_endpoints']}")

    if validation_summary['invalid_endpoints'] == 0:
        print(f"{Fore.GREEN}✅ All pinned certificates are valid!{Style.RESET_ALL}")
    else:
        print(f"{Fore.RED}⚠️  Some pinned certificates are invalid!{Style.RESET_ALL}")

    print(f"{'='*60}")

    return {
        'pinning_results': pinning_results,
        'validation_summary': validation_summary,
        'pinner': pinner
    }


__all__ = [
    "ssl",
    "hashlib",
    "socket",
    "requests",
    "datetime",
    "timedelta",
    "urlparse",
    "Fore",
    "Style",
    "logger",
    "CertificatePinner",
    "SecureHTTPClient",
    "main",
]
