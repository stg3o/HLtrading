"""
network_security.py — Network security measures for trading system
Implements VPN support, DNS security, network monitoring, and secure networking
"""
import socket
import ssl
import requests
import subprocess
import threading
import time
import ipaddress
import dns.resolver
import dns.reversename
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Set
from dataclasses import dataclass
from enum import Enum
from colorama import Fore, Style
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class NetworkSecurityLevel(Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass
class NetworkThreat:
    """Network threat detection data structure."""
    timestamp: str
    threat_type: str
    source_ip: str
    destination_ip: str
    port: int
    protocol: str
    severity: NetworkSecurityLevel
    description: str
    blocked: bool


class VPNManager:
    """VPN connection management and monitoring."""
    
    def __init__(self):
        self.vpn_status = False
        self.vpn_config = {}
        self.allowed_vpn_providers = [
            'nordvpn', 'expressvpn', 'surfshark', 'protonvpn', 
            'cyberghost', 'privateinternetaccess'
        ]
        
    def check_vpn_status(self) -> Dict[str, Any]:
        """Check current VPN connection status."""
        result = {
            'vpn_connected': False,
            'public_ip': None,
            'vpn_provider': None,
            'country': None,
            'timestamp': datetime.now().isoformat()
        }
        
        try:
            # Get public IP
            response = requests.get('https://api.ipify.org', timeout=5)
            public_ip = response.text
            
            # Check if IP belongs to known VPN providers
            vpn_info = self._check_vpn_provider(public_ip)
            
            result.update({
                'public_ip': public_ip,
                'vpn_connected': vpn_info['is_vpn'],
                'vpn_provider': vpn_info['provider'],
                'country': vpn_info['country']
            })
            
        except Exception as e:
            logger.error(f"Failed to check VPN status: {e}")
        
        return result
    
    def _check_vpn_provider(self, ip: str) -> Dict[str, Any]:
        """Check if IP belongs to a VPN provider."""
        try:
            # Reverse DNS lookup
            try:
                reverse_dns = socket.gethostbyaddr(ip)[0]
                provider = self._identify_vpn_provider(reverse_dns)
                if provider:
                    return {'is_vpn': True, 'provider': provider, 'country': self._get_country_from_ip(ip)}
            except:
                pass
            
            # Check against known VPN IP ranges (simplified check)
            vpn_ranges = self._get_vpn_ip_ranges()
            ip_obj = ipaddress.ip_address(ip)
            
            for network, provider in vpn_ranges.items():
                if ip_obj in network:
                    return {'is_vpn': True, 'provider': provider, 'country': self._get_country_from_ip(ip)}
            
            return {'is_vpn': False, 'provider': None, 'country': self._get_country_from_ip(ip)}
            
        except Exception as e:
            logger.error(f"Error checking VPN provider for {ip}: {e}")
            return {'is_vpn': False, 'provider': None, 'country': 'unknown'}
    
    def _identify_vpn_provider(self, hostname: str) -> Optional[str]:
        """Identify VPN provider from hostname."""
        hostname_lower = hostname.lower()
        for provider in self.allowed_vpn_providers:
            if provider in hostname_lower:
                return provider
        return None
    
    def _get_vpn_ip_ranges(self) -> Dict[ipaddress.IPv4Network, str]:
        """Get known VPN IP ranges (simplified for demo)."""
        # In production, this would be a comprehensive database
        return {
            ipaddress.IPv4Network('10.8.0.0/16'): 'OpenVPN',
            ipaddress.IPv4Network('10.9.0.0/16'): 'WireGuard',
        }
    
    def _get_country_from_ip(self, ip: str) -> str:
        """Get country from IP address."""
        try:
            # Use a free IP geolocation service
            response = requests.get(f'https://ipapi.co/{ip}/country_name/', timeout=5)
            return response.text.strip()
        except:
            return 'unknown'
    
    def enforce_vpn_requirement(self, required: bool = True) -> bool:
        """Enforce VPN requirement for trading operations."""
        vpn_status = self.check_vpn_status()
        
        if required and not vpn_status['vpn_connected']:
            logger.critical(f"VPN required but not connected! Public IP: {vpn_status['public_ip']}")
            return False
        
        if vpn_status['vpn_connected']:
            logger.info(f"VPN connected: {vpn_status['vpn_provider']} ({vpn_status['country']})")
        
        return True


class DNSSecurityManager:
    """DNS security and monitoring."""
    
    def __init__(self):
        self.allowed_dns_servers = [
            '1.1.1.1',    # Cloudflare
            '1.0.0.1',
            '8.8.8.8',    # Google
            '8.8.4.4',
            '208.67.222.222',  # OpenDNS
            '208.67.220.220'
        ]
        self.blocked_domains = set()
        self.dns_cache = {}
        
    def check_dns_security(self) -> Dict[str, Any]:
        """Check DNS configuration security."""
        result = {
            'secure_dns': False,
            'current_servers': [],
            'blocked_domains_count': len(self.blocked_domains),
            'timestamp': datetime.now().isoformat()
        }
        
        try:
            # Get current DNS servers
            current_servers = self._get_dns_servers()
            result['current_servers'] = current_servers
            
            # Check if using secure DNS servers
            secure_servers = [server for server in current_servers if server in self.allowed_dns_servers]
            result['secure_dns'] = len(secure_servers) > 0
            
            if not result['secure_dns']:
                logger.warning(f"Using non-secure DNS servers: {current_servers}")
            
        except Exception as e:
            logger.error(f"Failed to check DNS security: {e}")
        
        return result
    
    def _get_dns_servers(self) -> List[str]:
        """Get current DNS servers."""
        try:
            # Cross-platform DNS server detection
            if subprocess.run(['which', 'systemd-resolve'], capture_output=True).returncode == 0:
                # Linux with systemd
                result = subprocess.run(['systemd-resolve', '--status'], 
                                      capture_output=True, text=True)
                lines = result.stdout.split('\n')
                servers = []
                for line in lines:
                    if 'DNS Servers:' in line:
                        servers.append(line.split(':')[1].strip())
                return servers
            elif subprocess.run(['which', 'scutil'], capture_output=True).returncode == 0:
                # macOS
                result = subprocess.run(['scutil', '--dns'], capture_output=True, text=True)
                lines = result.stdout.split('\n')
                servers = []
                for line in lines:
                    if 'nameserver' in line.lower():
                        servers.append(line.split(' ')[-1])
                return servers
            else:
                # Fallback - try to resolve a domain
                import socket
                return [socket.gethostbyname('dns.google')]
                
        except Exception as e:
            logger.error(f"Error getting DNS servers: {e}")
            return []
    
    def block_malicious_domain(self, domain: str) -> bool:
        """Block a malicious domain."""
        try:
            self.blocked_domains.add(domain.lower())
            logger.info(f"Blocked malicious domain: {domain}")
            return True
        except Exception as e:
            logger.error(f"Failed to block domain {domain}: {e}")
            return False
    
    def is_domain_allowed(self, domain: str) -> bool:
        """Check if domain is allowed."""
        domain_lower = domain.lower()
        
        # Check blocked domains
        if domain_lower in self.blocked_domains:
            return False
        
        # Check for suspicious patterns
        if self._is_suspicious_domain(domain_lower):
            logger.warning(f"Suspicious domain detected: {domain}")
            return False
        
        return True
    
    def _is_suspicious_domain(self, domain: str) -> bool:
        """Check if domain is suspicious."""
        suspicious_patterns = [
            'bitcoin', 'crypto', 'investment', 'trading' in domain,
            domain.count('.') > 3,  # Too many subdomains
            len(domain) > 50,       # Too long
            any(char.isdigit() for char in domain.split('.')[0])  # Numbers in subdomain
        ]
        return any(suspicious_patterns)
    
    def secure_dns_resolution(self, hostname: str) -> Optional[str]:
        """Perform secure DNS resolution."""
        if not self.is_domain_allowed(hostname):
            logger.error(f"Domain blocked: {hostname}")
            return None
        
        try:
            # Use secure DNS servers for resolution
            resolver = dns.resolver.Resolver()
            resolver.nameservers = [dns.resolver.resolve('1.1.1.1', 'A')[0].to_text()]
            
            answers = resolver.resolve(hostname, 'A')
            ip = str(answers[0])
            
            # Cache the result
            self.dns_cache[hostname] = ip
            
            return ip
            
        except Exception as e:
            logger.error(f"DNS resolution failed for {hostname}: {e}")
            return None


class NetworkMonitor:
    """Network traffic monitoring and threat detection."""
    
    def __init__(self):
        self.threats = []
        self.monitored_ports = {443, 80, 22, 21, 25, 53, 3306, 5432}
        self.blocked_ips = set()
        self.suspicious_activity = []
        
    def start_monitoring(self, duration_minutes: int = 60):
        """Start network monitoring in background."""
        def monitor():
            end_time = datetime.now() + timedelta(minutes=duration_minutes)
            
            while datetime.now() < end_time:
                self._check_network_activity()
                time.sleep(30)  # Check every 30 seconds
        
        monitor_thread = threading.Thread(target=monitor, daemon=True)
        monitor_thread.start()
        logger.info(f"Network monitoring started for {duration_minutes} minutes")
    
    def _check_network_activity(self):
        """Check for suspicious network activity."""
        try:
            # Get network connections
            connections = self._get_network_connections()
            
            for conn in connections:
                self._analyze_connection(conn)
                
        except Exception as e:
            logger.error(f"Error checking network activity: {e}")
    
    def _get_network_connections(self) -> List[Dict[str, Any]]:
        """Get current network connections."""
        connections = []
        
        try:
            # Use netstat to get connections
            result = subprocess.run(['netstat', '-an'], capture_output=True, text=True)
            lines = result.stdout.split('\n')
            
            for line in lines:
                if 'ESTABLISHED' in line or 'LISTEN' in line:
                    parts = line.split()
                    if len(parts) >= 4:
                        connections.append({
                            'protocol': parts[0],
                            'local_address': parts[1],
                            'foreign_address': parts[2],
                            'state': parts[3]
                        })
                        
        except Exception as e:
            logger.error(f"Error getting network connections: {e}")
        
        return connections
    
    def _analyze_connection(self, conn: Dict[str, Any]):
        """Analyze a network connection for threats."""
        try:
            # Check for suspicious ports
            foreign_port = self._extract_port(conn['foreign_address'])
            if foreign_port and foreign_port not in self.monitored_ports:
                threat = NetworkThreat(
                    timestamp=datetime.now().isoformat(),
                    threat_type='Suspicious Port Connection',
                    source_ip=self._extract_ip(conn['local_address']),
                    destination_ip=self._extract_ip(conn['foreign_address']),
                    port=foreign_port,
                    protocol=conn['protocol'],
                    severity=NetworkSecurityLevel.MEDIUM,
                    description=f"Connection to non-standard port {foreign_port}",
                    blocked=False
                )
                self.threats.append(threat)
                logger.warning(f"Suspicious connection detected: {conn}")
            
            # Check for connections to blocked IPs
            dest_ip = self._extract_ip(conn['foreign_address'])
            if dest_ip in self.blocked_ips:
                threat = NetworkThreat(
                    timestamp=datetime.now().isoformat(),
                    threat_type='Blocked IP Connection',
                    source_ip=self._extract_ip(conn['local_address']),
                    destination_ip=dest_ip,
                    port=self._extract_port(conn['foreign_address']),
                    protocol=conn['protocol'],
                    severity=NetworkSecurityLevel.HIGH,
                    description=f"Connection attempt to blocked IP {dest_ip}",
                    blocked=True
                )
                self.threats.append(threat)
                logger.critical(f"Blocked connection to {dest_ip}")
                
        except Exception as e:
            logger.error(f"Error analyzing connection {conn}: {e}")
    
    def _extract_ip(self, address: str) -> Optional[str]:
        """Extract IP address from address string."""
        try:
            return address.split(':')[0]
        except:
            return None
    
    def _extract_port(self, address: str) -> Optional[int]:
        """Extract port from address string."""
        try:
            return int(address.split(':')[-1])
        except:
            return None
    
    def block_ip(self, ip: str) -> bool:
        """Block an IP address."""
        try:
            self.blocked_ips.add(ip)
            # Add to firewall rules (simplified)
            subprocess.run(['iptables', '-A', 'INPUT', '-s', ip, '-j', 'DROP'], 
                          capture_output=True)
            logger.info(f"Blocked IP address: {ip}")
            return True
        except Exception as e:
            logger.error(f"Failed to block IP {ip}: {e}")
            return False
    
    def get_threat_summary(self) -> Dict[str, Any]:
        """Get threat detection summary."""
        return {
            'total_threats': len(self.threats),
            'high_severity_threats': len([t for t in self.threats if t.severity == NetworkSecurityLevel.HIGH]),
            'medium_severity_threats': len([t for t in self.threats if t.severity == NetworkSecurityLevel.MEDIUM]),
            'blocked_ips_count': len(self.blocked_ips),
            'recent_threats': self.threats[-10:],  # Last 10 threats
            'timestamp': datetime.now().isoformat()
        }


class SecureNetworkClient:
    """Secure HTTP client with network security measures."""
    
    def __init__(self):
        self.vpn_manager = VPNManager()
        self.dns_manager = DNSSecurityManager()
        self.network_monitor = NetworkMonitor()
        
        # Configure secure session
        self.session = requests.Session()
        self.session.verify = True  # Enable SSL verification
        self.session.headers.update({
            'User-Agent': 'SecureTradingBot/1.0',
            'Accept': 'application/json',
            'Cache-Control': 'no-cache'
        })
    
    def make_secure_request(self, url: str, method: str = 'GET', **kwargs) -> requests.Response:
        """Make a secure HTTP request with network security checks."""
        
        # Check VPN requirement
        if not self.vpn_manager.enforce_vpn_requirement(required=True):
            raise Exception("VPN connection required but not available")
        
        # Check DNS security
        dns_status = self.dns_manager.check_dns_security()
        if not dns_status['secure_dns']:
            logger.warning("DNS security check failed, proceeding with caution")
        
        # Parse URL and check domain
        from urllib.parse import urlparse
        parsed_url = urlparse(url)
        if not self.dns_manager.is_domain_allowed(parsed_url.hostname):
            raise Exception(f"Domain {parsed_url.hostname} is blocked")
        
        # Perform the request
        if method.upper() == 'GET':
            response = self.session.get(url, **kwargs)
        elif method.upper() == 'POST':
            response = self.session.post(url, **kwargs)
        else:
            response = self.session.request(method, url, **kwargs)
        
        # Log the request for monitoring
        logger.info(f"Secure request made to {parsed_url.hostname}: {response.status_code}")
        
        return response


def main():
    """Demonstrate network security measures."""
    print(f"{Fore.CYAN}Starting Network Security System...{Style.RESET_ALL}")
    
    # Initialize security managers
    vpn_manager = VPNManager()
    dns_manager = DNSSecurityManager()
    network_monitor = NetworkMonitor()
    secure_client = SecureNetworkClient()
    
    # Check VPN status
    print("Checking VPN status...")
    vpn_status = vpn_manager.check_vpn_status()
    print(f"  VPN Connected: {vpn_status['vpn_connected']}")
    print(f"  Provider: {vpn_status['vpn_provider']}")
    print(f"  Country: {vpn_status['country']}")
    print(f"  Public IP: {vpn_status['public_ip']}")
    
    # Check DNS security
    print("\nChecking DNS security...")
    dns_status = dns_manager.check_dns_security()
    print(f"  Secure DNS: {dns_status['secure_dns']}")
    print(f"  Current Servers: {dns_status['current_servers']}")
    
    # Block some malicious domains
    print("\nBlocking malicious domains...")
    dns_manager.block_malicious_domain("malicious-trading-site.com")
    dns_manager.block_malicious_domain("fake-exchange.net")
    
    # Start network monitoring
    print("\nStarting network monitoring...")
    network_monitor.start_monitoring(duration_minutes=2)  # Short demo
    
    # Test secure connection
    print("\nTesting secure connection...")
    try:
        response = secure_client.make_secure_request('https://api.ipify.org')
        print(f"  ✅ Secure connection successful: {response.text}")
    except Exception as e:
        print(f"  ❌ Secure connection failed: {e}")
    
    # Get threat summary
    print("\nGetting threat summary...")
    time.sleep(3)  # Give monitoring time to detect threats
    threat_summary = network_monitor.get_threat_summary()
    print(f"  Total threats detected: {threat_summary['total_threats']}")
    print(f"  High severity: {threat_summary['high_severity_threats']}")
    print(f"  Blocked IPs: {threat_summary['blocked_ips_count']}")
    
    print(f"\n{Fore.GREEN}Network security demonstration completed!{Style.RESET_ALL}")
    
    return {
        'vpn_status': vpn_status,
        'dns_status': dns_status,
        'threat_summary': threat_summary
    }


if __name__ == "__main__":
    try:
        results = main()
    except Exception as e:
        print(f"{Fore.RED}Error during network security demonstration: {e}{Style.RESET_ALL}")
        logger.error(f"Network security failed: {e}")
        import traceback
        traceback.print_exc()