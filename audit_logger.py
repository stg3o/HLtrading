"""
audit_logger.py — Comprehensive audit logging system with correlation IDs
Provides security auditing, compliance logging, and operational monitoring
"""
import json
import logging
import threading
import time
import uuid
from datetime import datetime
from typing import Dict, List, Any, Optional, Union
from pathlib import Path
from dataclasses import dataclass, asdict
from enum import Enum
import hashlib
import socket
import getpass
import platform
from colorama import Fore, Style

# Configure structured logging
class AuditLogLevel(Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"
    SECURITY = "SECURITY"
    COMPLIANCE = "COMPLIANCE"


@dataclass
class AuditEvent:
    """Audit event data structure."""
    event_id: str
    timestamp: str
    level: str
    event_type: str
    source: str
    user_id: Optional[str]
    session_id: Optional[str]
    correlation_id: Optional[str]
    action: str
    resource: str
    details: Dict[str, Any]
    ip_address: Optional[str]
    user_agent: Optional[str]
    success: bool
    error_message: Optional[str]
    duration_ms: Optional[float]
    risk_score: Optional[int]
    compliance_tags: List[str]


class AuditLogger:
    """Comprehensive audit logging system with correlation IDs."""
    
    def __init__(self, log_file: str = "audit.log", max_file_size: int = 10*1024*1024):
        self.log_file = log_file
        self.max_file_size = max_file_size
        self.correlation_id = None
        self.session_id = None
        self.user_id = None
        
        # Thread-local storage for context
        self.local = threading.local()
        
        # Initialize logging
        self._setup_logging()
        
        # System information
        self.system_info = self._get_system_info()
        
        # Risk scoring thresholds
        self.risk_thresholds = {
            'LOW': 1-3,
            'MEDIUM': 4-6,
            'HIGH': 7-8,
            'CRITICAL': 9-10
        }
    
    def _setup_logging(self):
        """Set up structured logging configuration."""
        # Create log directory if it doesn't exist
        log_path = Path(self.log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Configure root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        
        # Remove existing handlers
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        
        # Create formatters
        json_formatter = logging.Formatter(
            '%(message)s'  # JSON format
        )
        
        console_formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(name)s - %(message)s'
        )
        
        # File handler with rotation
        from logging.handlers import RotatingFileHandler
        file_handler = RotatingFileHandler(
            self.log_file,
            maxBytes=self.max_file_size,
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(json_formatter)
        
        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(console_formatter)
        
        # Add handlers
        root_logger.addHandler(file_handler)
        root_logger.addHandler(console_handler)
        
        # Create audit logger
        self.logger = logging.getLogger('audit')
        self.logger.propagate = False  # Don't propagate to root logger
    
    def _get_system_info(self) -> Dict[str, str]:
        """Get system information for audit events."""
        return {
            'hostname': socket.gethostname(),
            'ip_address': self._get_external_ip(),
            'platform': platform.platform(),
            'python_version': platform.python_version(),
            'user': getpass.getuser(),
            'process_id': str(os.getpid()) if 'os' in globals() else 'unknown'
        }
    
    def _get_external_ip(self) -> str:
        """Get external IP address."""
        try:
            import requests
            response = requests.get('https://api.ipify.org', timeout=5)
            return response.text
        except:
            return 'unknown'
    
    def set_correlation_id(self, correlation_id: Optional[str] = None) -> str:
        """Set or generate a correlation ID for the current context."""
        if correlation_id:
            self.correlation_id = correlation_id
        else:
            self.correlation_id = str(uuid.uuid4())
        
        # Store in thread-local storage
        self.local.correlation_id = self.correlation_id
        return self.correlation_id
    
    def set_session_id(self, session_id: Optional[str] = None) -> str:
        """Set or generate a session ID for the current context."""
        if session_id:
            self.session_id = session_id
        else:
            self.session_id = str(uuid.uuid4())
        
        # Store in thread-local storage
        self.local.session_id = self.session_id
        return self.session_id
    
    def set_user_id(self, user_id: str) -> None:
        """Set user ID for the current context."""
        self.user_id = user_id
        self.local.user_id = user_id
    
    def _get_context(self) -> Dict[str, Any]:
        """Get current context information."""
        return {
            'correlation_id': getattr(self.local, 'correlation_id', self.correlation_id),
            'session_id': getattr(self.local, 'session_id', self.session_id),
            'user_id': getattr(self.local, 'user_id', self.user_id)
        }
    
    def _calculate_risk_score(self, event_type: str, action: str, success: bool) -> int:
        """Calculate risk score for an event."""
        risk_factors = {
            'authentication': 3,
            'authorization': 4,
            'data_access': 5,
            'data_modification': 6,
            'system_configuration': 7,
            'financial_transaction': 8,
            'security_breach': 10
        }
        
        base_score = risk_factors.get(event_type, 1)
        
        # Adjust based on action and success
        if not success:
            base_score += 2
        
        if 'admin' in action.lower() or 'privileged' in action.lower():
            base_score += 2
        
        return min(max(base_score, 1), 10)
    
    def _generate_compliance_tags(self, event_type: str, action: str) -> List[str]:
        """Generate compliance tags for the event."""
        tags = ['trading_system']
        
        if event_type in ['authentication', 'authorization']:
            tags.extend(['SOX', 'PCI_DSS', 'GDPR'])
        
        if 'trade' in action.lower() or 'order' in action.lower():
            tags.extend(['SOX', 'FINRA'])
        
        if 'config' in action.lower() or 'system' in action.lower():
            tags.extend(['SOX', 'NIST'])
        
        return tags
    
    def log_event(self, 
                  event_type: str,
                  action: str,
                  resource: str,
                  details: Dict[str, Any] = None,
                  level: AuditLogLevel = AuditLogLevel.INFO,
                  success: bool = True,
                  error_message: Optional[str] = None,
                  duration_ms: Optional[float] = None,
                  risk_score: Optional[int] = None) -> str:
        """Log an audit event."""
        
        # Get context
        context = self._get_context()
        
        # Calculate risk score if not provided
        if risk_score is None:
            risk_score = self._calculate_risk_score(event_type, action, success)
        
        # Generate compliance tags
        compliance_tags = self._generate_compliance_tags(event_type, action)
        
        # Create audit event
        audit_event = AuditEvent(
            event_id=str(uuid.uuid4()),
            timestamp=datetime.utcnow().isoformat() + 'Z',
            level=level.value,
            event_type=event_type,
            source='trading_bot',
            user_id=context['user_id'],
            session_id=context['session_id'],
            correlation_id=context['correlation_id'],
            action=action,
            resource=resource,
            details=details or {},
            ip_address=self.system_info['ip_address'],
            user_agent=f"TradingBot/{self.system_info['platform']}",
            success=success,
            error_message=error_message,
            duration_ms=duration_ms,
            risk_score=risk_score,
            compliance_tags=compliance_tags
        )
        
        # Log as JSON
        self.logger.log(
            getattr(logging, level.value),
            json.dumps(asdict(audit_event), default=str)
        )
        
        # Console output for high-risk events
        if risk_score and risk_score >= 7:
            risk_color = Fore.RED if risk_score >= 9 else Fore.YELLOW
            print(f"{risk_color}[AUDIT] High risk event: {action} on {resource} (Risk: {risk_score}){Style.RESET_ALL}")
        
        return audit_event.event_id
    
    # Convenience methods for common event types
    
    def log_authentication(self, username: str, success: bool, 
                          ip_address: str = None, user_agent: str = None) -> str:
        """Log authentication events."""
        details = {
            'username': username,
            'ip_address': ip_address,
            'user_agent': user_agent
        }
        
        level = AuditLogLevel.SECURITY if success else AuditLogLevel.CRITICAL
        action = "login_success" if success else "login_failed"
        
        return self.log_event(
            event_type="authentication",
            action=action,
            resource="user_session",
            details=details,
            level=level,
            success=success,
            risk_score=5 if success else 8
        )
    
    def log_authorization(self, username: str, permission: str, 
                         resource: str, success: bool) -> str:
        """Log authorization events."""
        details = {
            'username': username,
            'permission': permission,
            'resource': resource
        }
        
        level = AuditLogLevel.SECURITY if success else AuditLogLevel.CRITICAL
        action = "access_granted" if success else "access_denied"
        
        return self.log_event(
            event_type="authorization",
            action=action,
            resource=resource,
            details=details,
            level=level,
            success=success,
            risk_score=4 if success else 7
        )
    
    def log_trade_execution(self, trade_details: Dict[str, Any], 
                           success: bool, error_message: str = None) -> str:
        """Log trade execution events."""
        level = AuditLogLevel.COMPLIANCE if success else AuditLogLevel.CRITICAL
        action = "trade_executed" if success else "trade_failed"
        
        return self.log_event(
            event_type="financial_transaction",
            action=action,
            resource="trading_account",
            details=trade_details,
            level=level,
            success=success,
            error_message=error_message,
            risk_score=8 if success else 10
        )
    
    def log_data_access(self, data_type: str, user: str, 
                       success: bool, details: Dict[str, Any] = None) -> str:
        """Log data access events."""
        details = details or {}
        details.update({
            'data_type': data_type,
            'user': user
        })
        
        level = AuditLogLevel.COMPLIANCE if success else AuditLogLevel.WARNING
        action = "data_accessed" if success else "data_access_failed"
        
        return self.log_event(
            event_type="data_access",
            action=action,
            resource=data_type,
            details=details,
            level=level,
            success=success,
            risk_score=3 if success else 5
        )
    
    def log_system_event(self, event_name: str, severity: str, 
                        details: Dict[str, Any] = None) -> str:
        """Log system events."""
        level_map = {
            'info': AuditLogLevel.INFO,
            'warning': AuditLogLevel.WARNING,
            'error': AuditLogLevel.ERROR,
            'critical': AuditLogLevel.CRITICAL
        }
        
        level = level_map.get(severity.lower(), AuditLogLevel.INFO)
        success = severity.lower() != 'critical'
        
        return self.log_event(
            event_type="system_event",
            action=event_name,
            resource="system",
            details=details,
            level=level,
            success=success,
            risk_score=2 if success else 9
        )
    
    def log_security_event(self, event_type: str, description: str, 
                          severity: str = "medium", details: Dict[str, Any] = None) -> str:
        """Log security events."""
        level_map = {
            'low': AuditLogLevel.WARNING,
            'medium': AuditLogLevel.ERROR,
            'high': AuditLogLevel.CRITICAL,
            'critical': AuditLogLevel.CRITICAL
        }
        
        level = level_map.get(severity.lower(), AuditLogLevel.WARNING)
        
        return self.log_event(
            event_type="security_breach",
            action=event_type,
            resource="security",
            details=details or {'description': description},
            level=level,
            success=False,
            risk_score=6 if severity.lower() in ['low', 'medium'] else 9
        )
    
    def log_compliance_event(self, regulation: str, action: str, 
                           details: Dict[str, Any] = None) -> str:
        """Log compliance events."""
        details = details or {}
        details['regulation'] = regulation
        
        return self.log_event(
            event_type="compliance",
            action=action,
            resource="compliance_framework",
            details=details,
            level=AuditLogLevel.COMPLIANCE,
            success=True,
            risk_score=2
        )
    
    def get_audit_summary(self, hours: int = 24) -> Dict[str, Any]:
        """Get audit log summary for the specified time period."""
        try:
            with open(self.log_file, 'r') as f:
                lines = f.readlines()
            
            events = []
            cutoff_time = datetime.utcnow() - timedelta(hours=hours)
            
            for line in lines:
                try:
                    event_data = json.loads(line.strip())
                    event_time = datetime.fromisoformat(event_data['timestamp'].replace('Z', '+00:00'))
                    
                    if event_time >= cutoff_time:
                        events.append(event_data)
                except:
                    continue
            
            # Analyze events
            summary = {
                'total_events': len(events),
                'events_by_level': {},
                'events_by_type': {},
                'high_risk_events': [],
                'failed_events': [],
                'unique_users': set(),
                'unique_correlations': set(),
                'time_range': {
                    'start': cutoff_time.isoformat(),
                    'end': datetime.utcnow().isoformat()
                }
            }
            
            for event in events:
                # Count by level
                level = event['level']
                summary['events_by_level'][level] = summary['events_by_level'].get(level, 0) + 1
                
                # Count by type
                event_type = event['event_type']
                summary['events_by_type'][event_type] = summary['events_by_type'].get(event_type, 0) + 1
                
                # Track users and correlations
                if event.get('user_id'):
                    summary['unique_users'].add(event['user_id'])
                if event.get('correlation_id'):
                    summary['unique_correlations'].add(event['correlation_id'])
                
                # High risk events
                if event.get('risk_score', 0) >= 7:
                    summary['high_risk_events'].append(event)
                
                # Failed events
                if not event.get('success', True):
                    summary['failed_events'].append(event)
            
            summary['unique_users'] = list(summary['unique_users'])
            summary['unique_correlations'] = list(summary['unique_correlations'])
            
            return summary
            
        except Exception as e:
            return {'error': f"Failed to generate audit summary: {e}"}
    
    def export_audit_log(self, output_file: str, hours: int = 24) -> bool:
        """Export audit log for the specified time period."""
        try:
            summary = self.get_audit_summary(hours)
            
            if 'error' in summary:
                return False
            
            export_data = {
                'export_timestamp': datetime.utcnow().isoformat() + 'Z',
                'time_period_hours': hours,
                'summary': summary,
                'events': []
            }
            
            # Read and filter events
            with open(self.log_file, 'r') as f:
                for line in f:
                    try:
                        event_data = json.loads(line.strip())
                        event_time = datetime.fromisoformat(event_data['timestamp'].replace('Z', '+00:00'))
                        cutoff_time = datetime.utcnow() - timedelta(hours=hours)
                        
                        if event_time >= cutoff_time:
                            export_data['events'].append(event_data)
                    except:
                        continue
            
            # Save export
            with open(output_file, 'w') as f:
                json.dump(export_data, f, indent=2, default=str)
            
            print(f"{Fore.GREEN}Audit log exported to {output_file}{Style.RESET_ALL}")
            return True
            
        except Exception as e:
            print(f"{Fore.RED}Failed to export audit log: {e}{Style.RESET_ALL}")
            return False


# Global audit logger instance
audit_logger = AuditLogger()


def get_audit_logger() -> AuditLogger:
    """Get the global audit logger instance."""
    return audit_logger


# Context manager for correlation IDs
class AuditContext:
    """Context manager for audit logging with correlation IDs."""
    
    def __init__(self, correlation_id: str = None, session_id: str = None, user_id: str = None):
        self.correlation_id = correlation_id
        self.session_id = session_id
        self.user_id = user_id
        self.original_context = {}
    
    def __enter__(self):
        # Save original context
        self.original_context = {
            'correlation_id': audit_logger.correlation_id,
            'session_id': audit_logger.session_id,
            'user_id': audit_logger.user_id
        }
        
        # Set new context
        if self.correlation_id:
            audit_logger.set_correlation_id(self.correlation_id)
        if self.session_id:
            audit_logger.set_session_id(self.session_id)
        if self.user_id:
            audit_logger.set_user_id(self.user_id)
        
        return audit_logger
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        # Restore original context
        audit_logger.correlation_id = self.original_context['correlation_id']
        audit_logger.session_id = self.original_context['session_id']
        audit_logger.user_id = self.original_context['user_id']


def main():
    """Demonstrate audit logging functionality."""
    print(f"{Fore.CYAN}Starting Audit Logging System...{Style.RESET_ALL}")
    
    # Set up initial context
    audit_logger.set_correlation_id()
    audit_logger.set_session_id()
    audit_logger.set_user_id("trading_bot")
    
    # Log various events
    print("Logging sample events...")
    
    # Authentication events
    audit_logger.log_authentication("user123", True, "192.168.1.100")
    audit_logger.log_authentication("hacker", False, "10.0.0.1")
    
    # Authorization events
    audit_logger.log_authorization("user123", "read", "trading_data", True)
    audit_logger.log_authorization("user456", "write", "config", False)
    
    # Trade execution
    trade_details = {
        'symbol': 'BTC/USD',
        'amount': 0.1,
        'price': 50000.0,
        'side': 'buy'
    }
    audit_logger.log_trade_execution(trade_details, True)
    
    # System events
    audit_logger.log_system_event("system_start", "info", {"version": "1.0.0"})
    audit_logger.log_system_event("database_error", "error", {"error": "Connection timeout"})
    
    # Security events
    audit_logger.log_security_event("brute_force_attack", "Multiple failed login attempts", "high")
    
    # Data access
    audit_logger.log_data_access("trade_history", "user123", True, {"records_accessed": 1000})
    
    # Compliance events
    audit_logger.log_compliance_event("SOX", "audit_trail_generated")
    
    # Get summary
    print(f"\n{Fore.CYAN}Generating audit summary...{Style.RESET_ALL}")
    summary = audit_logger.get_audit_summary(hours=1)
    
    print(f"Total events: {summary['total_events']}")
    print(f"Events by level: {summary['events_by_level']}")
    print(f"Events by type: {summary['events_by_type']}")
    print(f"High risk events: {len(summary['high_risk_events'])}")
    print(f"Failed events: {len(summary['failed_events'])}")
    
    # Export audit log
    audit_logger.export_audit_log("audit_export.json", hours=1)
    
    print(f"{Fore.GREEN}Audit logging demonstration completed!{Style.RESET_ALL}")
    
    return summary


if __name__ == "__main__":
    import os
    from datetime import timedelta
    
    try:
        results = main()
    except Exception as e:
        print(f"{Fore.RED}Error during audit logging demonstration: {e}{Style.RESET_ALL}")
        import traceback
        traceback.print_exc()