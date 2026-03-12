"""
advanced_monitoring.py — Advanced monitoring and real-time alerting system
Provides comprehensive system monitoring, performance tracking, and real-time alerts
"""
import time
import threading
import psutil
import requests
import smtplib
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, asdict
from enum import Enum
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from colorama import Fore, Style
import socket

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class AlertSeverity(Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    EMERGENCY = "EMERGENCY"


class MetricType(Enum):
    CPU = "CPU"
    MEMORY = "MEMORY"
    DISK = "DISK"
    NETWORK = "NETWORK"
    TRADING = "TRADING"
    SYSTEM = "SYSTEM"
    SECURITY = "SECURITY"


@dataclass
class SystemMetric:
    """System metric data structure."""
    timestamp: str
    metric_type: MetricType
    value: float
    unit: str
    threshold: Optional[float]
    alert_triggered: bool
    details: Dict[str, Any]


@dataclass
class Alert:
    """Alert data structure."""
    alert_id: str
    timestamp: str
    severity: AlertSeverity
    metric_type: MetricType
    message: str
    details: Dict[str, Any]
    acknowledged: bool
    resolved: bool


class SystemMonitor:
    """Advanced system monitoring with real-time metrics collection."""
    
    def __init__(self, collection_interval: int = 30):
        self.collection_interval = collection_interval
        self.metrics_history: List[SystemMetric] = []
        self.alerts: List[Alert] = []
        self.monitoring_active = False
        self.monitor_thread = None
        
        # Thresholds configuration
        self.thresholds = {
            MetricType.CPU: 80.0,      # CPU usage percentage
            MetricType.MEMORY: 85.0,   # Memory usage percentage
            MetricType.DISK: 90.0,     # Disk usage percentage
            MetricType.NETWORK: 1000,  # Network throughput MB/s
        }
        
        # Trading-specific thresholds
        self.trading_thresholds = {
            'max_drawdown': 5.0,       # Maximum drawdown percentage
            'min_pnl': -1000.0,        # Minimum P&L threshold
            'max_trade_frequency': 100, # Maximum trades per hour
            'min_liquidity': 100000,   # Minimum liquidity threshold
        }
    
    def start_monitoring(self):
        """Start system monitoring in background."""
        if self.monitoring_active:
            logger.warning("Monitoring already active")
            return
        
        self.monitoring_active = True
        self.monitor_thread = threading.Thread(target=self._monitoring_loop, daemon=True)
        self.monitor_thread.start()
        logger.info(f"System monitoring started with {self.collection_interval}s interval")
    
    def stop_monitoring(self):
        """Stop system monitoring."""
        self.monitoring_active = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
        logger.info("System monitoring stopped")
    
    def _monitoring_loop(self):
        """Main monitoring loop."""
        while self.monitoring_active:
            try:
                # Collect system metrics
                self._collect_system_metrics()
                
                # Collect trading metrics (simulated)
                self._collect_trading_metrics()
                
                # Check for alerts
                self._check_alerts()
                
                time.sleep(self.collection_interval)
                
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                time.sleep(5)  # Wait before retrying
    
    def _collect_system_metrics(self):
        """Collect system performance metrics."""
        timestamp = datetime.now().isoformat()
        
        # CPU metrics
        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_metric = SystemMetric(
            timestamp=timestamp,
            metric_type=MetricType.CPU,
            value=cpu_percent,
            unit="%",
            threshold=self.thresholds[MetricType.CPU],
            alert_triggered=cpu_percent > self.thresholds[MetricType.CPU],
            details={'cores': psutil.cpu_count()}
        )
        self.metrics_history.append(cpu_metric)
        
        # Memory metrics
        memory = psutil.virtual_memory()
        memory_metric = SystemMetric(
            timestamp=timestamp,
            metric_type=MetricType.MEMORY,
            value=memory.percent,
            unit="%",
            threshold=self.thresholds[MetricType.MEMORY],
            alert_triggered=memory.percent > self.thresholds[MetricType.MEMORY],
            details={'total_gb': round(memory.total / (1024**3), 2),
                    'available_gb': round(memory.available / (1024**3), 2)}
        )
        self.metrics_history.append(memory_metric)
        
        # Disk metrics
        disk = psutil.disk_usage('/')
        disk_percent = (disk.used / disk.total) * 100
        disk_metric = SystemMetric(
            timestamp=timestamp,
            metric_type=MetricType.DISK,
            value=disk_percent,
            unit="%",
            threshold=self.thresholds[MetricType.DISK],
            alert_triggered=disk_percent > self.thresholds[MetricType.DISK],
            details={'total_gb': round(disk.total / (1024**3), 2),
                    'free_gb': round(disk.free / (1024**3), 2)}
        )
        self.metrics_history.append(disk_metric)
        
        # Network metrics
        network = psutil.net_io_counters()
        network_metric = SystemMetric(
            timestamp=timestamp,
            metric_type=MetricType.NETWORK,
            value=network.bytes_sent + network.bytes_recv,
            unit="bytes",
            threshold=self.thresholds[MetricType.NETWORK],
            alert_triggered=False,  # Network monitoring is more complex
            details={'bytes_sent': network.bytes_sent,
                    'bytes_recv': network.bytes_recv,
                    'packets_sent': network.packets_sent,
                    'packets_recv': network.packets_recv}
        )
        self.metrics_history.append(network_metric)
    
    def _collect_trading_metrics(self):
        """Collect trading-specific metrics."""
        timestamp = datetime.now().isoformat()
        
        # Simulate trading metrics (in real system, these would come from trading engine)
        import random
        
        # P&L metric
        pnl = random.uniform(-5000, 10000)  # Simulated P&L
        pnl_metric = SystemMetric(
            timestamp=timestamp,
            metric_type=MetricType.TRADING,
            value=pnl,
            unit="USD",
            threshold=self.trading_thresholds['min_pnl'],
            alert_triggered=pnl < self.trading_thresholds['min_pnl'],
            details={'trading_session': 'live', 'strategy': 'arbitrage'}
        )
        self.metrics_history.append(pnl_metric)
        
        # Drawdown metric
        drawdown = random.uniform(0, 10)  # Simulated drawdown percentage
        drawdown_metric = SystemMetric(
            timestamp=timestamp,
            metric_type=MetricType.TRADING,
            value=drawdown,
            unit="%",
            threshold=self.trading_thresholds['max_drawdown'],
            alert_triggered=drawdown > self.trading_thresholds['max_drawdown'],
            details={'peak_value': 50000, 'current_value': 45000}
        )
        self.metrics_history.append(drawdown_metric)
    
    def _check_alerts(self):
        """Check for alert conditions and generate alerts."""
        current_time = datetime.now()
        
        # Check recent metrics for alert conditions
        recent_metrics = [
            m for m in self.metrics_history 
            if datetime.fromisoformat(m.timestamp) > current_time - timedelta(minutes=5)
        ]
        
        for metric in recent_metrics:
            if metric.alert_triggered:
                self._generate_alert(metric)
    
    def _generate_alert(self, metric: SystemMetric):
        """Generate an alert for a metric."""
        severity = self._determine_severity(metric)
        
        alert = Alert(
            alert_id=f"alert_{int(time.time())}_{metric.metric_type.value}",
            timestamp=datetime.now().isoformat(),
            severity=severity,
            metric_type=metric.metric_type,
            message=self._generate_alert_message(metric),
            details={
                'metric_value': metric.value,
                'threshold': metric.threshold,
                'unit': metric.unit,
                'details': metric.details
            },
            acknowledged=False,
            resolved=False
        )
        
        self.alerts.append(alert)
        logger.warning(f"Alert generated: {alert.message}")
        
        # Send notification
        self._send_notification(alert)
    
    def _determine_severity(self, metric: SystemMetric) -> AlertSeverity:
        """Determine alert severity based on metric value."""
        if metric.metric_type in [MetricType.CPU, MetricType.MEMORY, MetricType.DISK]:
            if metric.value > 95:
                return AlertSeverity.EMERGENCY
            elif metric.value > 85:
                return AlertSeverity.CRITICAL
            elif metric.value > 75:
                return AlertSeverity.WARNING
            else:
                return AlertSeverity.INFO
        elif metric.metric_type == MetricType.TRADING:
            if metric.value < -5000:  # Large loss
                return AlertSeverity.EMERGENCY
            elif metric.value < -1000:  # Moderate loss
                return AlertSeverity.CRITICAL
            else:
                return AlertSeverity.WARNING
        
        return AlertSeverity.INFO
    
    def _generate_alert_message(self, metric: SystemMetric) -> str:
        """Generate human-readable alert message."""
        if metric.metric_type == MetricType.CPU:
            return f"High CPU usage: {metric.value:.1f}% (threshold: {metric.threshold}%)"
        elif metric.metric_type == MetricType.MEMORY:
            return f"High memory usage: {metric.value:.1f}% (threshold: {metric.threshold}%)"
        elif metric.metric_type == MetricType.DISK:
            return f"High disk usage: {metric.value:.1f}% (threshold: {metric.threshold}%)"
        elif metric.metric_type == MetricType.TRADING:
            if 'P&L' in str(metric.details):
                return f"Trading loss detected: ${metric.value:.2f}"
            else:
                return f"High drawdown detected: {metric.value:.1f}%"
        
        return f"Alert for {metric.metric_type.value}: {metric.value} {metric.unit}"
    
    def get_metrics_summary(self, hours: int = 1) -> Dict[str, Any]:
        """Get metrics summary for the specified time period."""
        cutoff_time = datetime.now() - timedelta(hours=hours)
        recent_metrics = [
            m for m in self.metrics_history 
            if datetime.fromisoformat(m.timestamp) > cutoff_time
        ]
        
        summary = {
            'time_period_hours': hours,
            'total_metrics': len(recent_metrics),
            'metrics_by_type': {},
            'avg_values': {},
            'max_values': {},
            'alert_count': len([a for a in self.alerts if not a.acknowledged]),
            'timestamp': datetime.now().isoformat()
        }
        
        for metric_type in MetricType:
            type_metrics = [m for m in recent_metrics if m.metric_type == metric_type]
            summary['metrics_by_type'][metric_type.value] = len(type_metrics)
            
            if type_metrics:
                values = [m.value for m in type_metrics]
                summary['avg_values'][metric_type.value] = sum(values) / len(values)
                summary['max_values'][metric_type.value] = max(values)
        
        return summary
    
    def get_active_alerts(self) -> List[Alert]:
        """Get all active (unacknowledged) alerts."""
        return [alert for alert in self.alerts if not alert.acknowledged and not alert.resolved]
    
    def acknowledge_alert(self, alert_id: str) -> bool:
        """Acknowledge an alert."""
        for alert in self.alerts:
            if alert.alert_id == alert_id:
                alert.acknowledged = True
                logger.info(f"Alert acknowledged: {alert_id}")
                return True
        return False
    
    def resolve_alert(self, alert_id: str) -> bool:
        """Resolve an alert."""
        for alert in self.alerts:
            if alert.alert_id == alert_id:
                alert.resolved = True
                alert.acknowledged = True
                logger.info(f"Alert resolved: {alert_id}")
                return True
        return False


class NotificationManager:
    """Advanced notification system with multiple channels."""
    
    def __init__(self):
        self.notification_channels = {
            'email': self._send_email_notification,
            'webhook': self._send_webhook_notification,
            'console': self._send_console_notification,
        }
        
        # Notification configuration
        self.email_config = {
            'smtp_server': 'smtp.gmail.com',
            'smtp_port': 587,
            'sender_email': 'alerts@tradingbot.local',
            'sender_password': 'your_app_password',
            'recipients': ['admin@tradingbot.local']
        }
        
        self.webhook_config = {
            'url': 'https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK',
            'headers': {'Content-Type': 'application/json'}
        }
    
    def send_notification(self, alert: Alert, channels: List[str] = None):
        """Send notification through specified channels."""
        if channels is None:
            channels = ['console', 'email']  # Default channels
        
        for channel in channels:
            if channel in self.notification_channels:
                try:
                    self.notification_channels[channel](alert)
                except Exception as e:
                    logger.error(f"Failed to send {channel} notification: {e}")
    
    def _send_email_notification(self, alert: Alert):
        """Send email notification."""
        try:
            msg = MIMEMultipart()
            msg['From'] = self.email_config['sender_email']
            msg['To'] = ', '.join(self.email_config['recipients'])
            msg['Subject'] = f"[{alert.severity.value}] Trading System Alert - {alert.metric_type.value}"
            
            body = self._format_email_body(alert)
            msg.attach(MIMEText(body, 'html'))
            
            server = smtplib.SMTP(self.email_config['smtp_server'], self.email_config['smtp_port'])
            server.starttls()
            server.login(self.email_config['sender_email'], self.email_config['sender_password'])
            server.send_message(msg)
            server.quit()
            
            logger.info(f"Email notification sent for alert {alert.alert_id}")
            
        except Exception as e:
            logger.error(f"Failed to send email notification: {e}")
    
    def _send_webhook_notification(self, alert: Alert):
        """Send webhook notification (e.g., to Slack)."""
        try:
            payload = {
                'text': f"🚨 [{alert.severity.value}] {alert.message}",
                'attachments': [{
                    'color': self._get_severity_color(alert.severity),
                    'fields': [
                        {'title': 'Metric Type', 'value': alert.metric_type.value, 'short': True},
                        {'title': 'Severity', 'value': alert.severity.value, 'short': True},
                        {'title': 'Time', 'value': alert.timestamp, 'short': True},
                        {'title': 'Details', 'value': str(alert.details), 'short': False}
                    ]
                }]
            }
            
            response = requests.post(
                self.webhook_config['url'],
                headers=self.webhook_config['headers'],
                json=payload,
                timeout=10
            )
            
            if response.status_code == 200:
                logger.info(f"Webhook notification sent for alert {alert.alert_id}")
            else:
                logger.error(f"Webhook notification failed: {response.status_code}")
                
        except Exception as e:
            logger.error(f"Failed to send webhook notification: {e}")
    
    def _send_console_notification(self, alert: Alert):
        """Send console notification."""
        severity_colors = {
            AlertSeverity.INFO: Fore.BLUE,
            AlertSeverity.WARNING: Fore.YELLOW,
            AlertSeverity.CRITICAL: Fore.RED,
            AlertSeverity.EMERGENCY: Fore.MAGENTA
        }
        
        color = severity_colors.get(alert.severity, Fore.WHITE)
        print(f"{color}[{alert.severity.value}] {alert.message}{Style.RESET_ALL}")
        print(f"  Metric: {alert.metric_type.value}")
        print(f"  Time: {alert.timestamp}")
        print(f"  Details: {alert.details}")
        print("-" * 50)
    
    def _format_email_body(self, alert: Alert) -> str:
        """Format email body with HTML."""
        severity_colors = {
            AlertSeverity.INFO: '#007bff',
            AlertSeverity.WARNING: '#ffc107',
            AlertSeverity.CRITICAL: '#dc3545',
            AlertSeverity.EMERGENCY: '#6f42c1'
        }
        
        color = severity_colors.get(alert.severity, '#6c757d')
        
        html = f"""
        <html>
        <head></head>
        <body>
            <div style="border-left: 4px solid {color}; padding-left: 15px;">
                <h2 style="color: {color}; margin-top: 0;">Trading System Alert</h2>
                <p><strong>Severity:</strong> <span style="color: {color};">{alert.severity.value}</span></p>
                <p><strong>Metric Type:</strong> {alert.metric_type.value}</p>
                <p><strong>Message:</strong> {alert.message}</p>
                <p><strong>Time:</strong> {alert.timestamp}</p>
                <p><strong>Details:</strong></p>
                <pre>{json.dumps(alert.details, indent=2)}</pre>
            </div>
        </body>
        </html>
        """
        return html
    
    def _get_severity_color(self, severity: AlertSeverity) -> str:
        """Get color code for severity level."""
        colors = {
            AlertSeverity.INFO: 'good',
            AlertSeverity.WARNING: 'warning', 
            AlertSeverity.CRITICAL: 'danger',
            AlertSeverity.EMERGENCY: 'danger'
        }
        return colors.get(severity, 'warning')


class HealthChecker:
    """System health checker for critical components."""
    
    def __init__(self):
        self.health_checks = {
            'network_connectivity': self._check_network_connectivity,
            'api_endpoints': self._check_api_endpoints,
            'disk_space': self._check_disk_space,
            'memory_usage': self._check_memory_usage,
            'trading_engine': self._check_trading_engine,
        }
        
        self.api_endpoints = [
            'https://api.hyperliquid.xyz'
        ]
    
    def run_health_checks(self) -> Dict[str, Any]:
        """Run all health checks and return results."""
        results = {
            'timestamp': datetime.now().isoformat(),
            'overall_status': 'HEALTHY',
            'checks': {},
            'failed_checks': []
        }
        
        for check_name, check_func in self.health_checks.items():
            try:
                result = check_func()
                results['checks'][check_name] = result
                
                if not result['healthy']:
                    results['failed_checks'].append(check_name)
                    if results['overall_status'] == 'HEALTHY':
                        results['overall_status'] = 'UNHEALTHY'
                        
            except Exception as e:
                results['checks'][check_name] = {
                    'healthy': False,
                    'error': str(e),
                    'timestamp': datetime.now().isoformat()
                }
                results['failed_checks'].append(check_name)
                results['overall_status'] = 'CRITICAL'
        
        return results
    
    def _check_network_connectivity(self) -> Dict[str, Any]:
        """Check network connectivity."""
        try:
            socket.create_connection(("8.8.8.8", 53), timeout=3)
            return {'healthy': True, 'message': 'Network connectivity OK'}
        except OSError:
            return {'healthy': False, 'message': 'Network connectivity failed'}
    
    def _check_api_endpoints(self) -> Dict[str, Any]:
        """Check critical API endpoints."""
        failed_endpoints = []
        
        for endpoint in self.api_endpoints:
            try:
                response = requests.get(endpoint, timeout=5)
                if response.status_code != 200:
                    failed_endpoints.append(endpoint)
            except:
                failed_endpoints.append(endpoint)
        
        if failed_endpoints:
            return {
                'healthy': False, 
                'failed_endpoints': failed_endpoints,
                'message': f'API endpoints failed: {", ".join(failed_endpoints)}'
            }
        else:
            return {'healthy': True, 'message': 'All API endpoints responding'}
    
    def _check_disk_space(self) -> Dict[str, Any]:
        """Check disk space."""
        disk = psutil.disk_usage('/')
        disk_percent = (disk.used / disk.total) * 100
        
        if disk_percent > 90:
            return {'healthy': False, 'usage_percent': disk_percent, 'message': 'Disk space critical'}
        elif disk_percent > 80:
            return {'healthy': False, 'usage_percent': disk_percent, 'message': 'Disk space warning'}
        else:
            return {'healthy': True, 'usage_percent': disk_percent, 'message': 'Disk space OK'}
    
    def _check_memory_usage(self) -> Dict[str, Any]:
        """Check memory usage."""
        memory = psutil.virtual_memory()
        
        if memory.percent > 90:
            return {'healthy': False, 'usage_percent': memory.percent, 'message': 'Memory usage critical'}
        elif memory.percent > 80:
            return {'healthy': False, 'usage_percent': memory.percent, 'message': 'Memory usage warning'}
        else:
            return {'healthy': True, 'usage_percent': memory.percent, 'message': 'Memory usage OK'}
    
    def _check_trading_engine(self) -> Dict[str, Any]:
        """Check trading engine status."""
        # In a real system, this would check if the trading engine is running
        # For demo, we'll simulate it
        import random
        engine_healthy = random.choice([True, True, True, False])  # 75% chance of being healthy
        
        if engine_healthy:
            return {'healthy': True, 'message': 'Trading engine running'}
        else:
            return {'healthy': False, 'message': 'Trading engine not responding'}


def main():
    """Demonstrate advanced monitoring system."""
    print(f"{Fore.CYAN}Starting Advanced Monitoring System...{Style.RESET_ALL}")
    
    # Initialize monitoring components
    monitor = SystemMonitor(collection_interval=10)  # Short interval for demo
    notifier = NotificationManager()
    health_checker = HealthChecker()
    
    # Start monitoring
    print("Starting system monitoring...")
    monitor.start_monitoring()
    
    # Run health checks
    print("\nRunning health checks...")
    health_results = health_checker.run_health_checks()
    print(f"Overall status: {health_results['overall_status']}")
    print(f"Failed checks: {len(health_results['failed_checks'])}")
    
    # Collect some metrics
    print("\nCollecting metrics for 30 seconds...")
    time.sleep(30)
    
    # Get metrics summary
    print("\nGetting metrics summary...")
    metrics_summary = monitor.get_metrics_summary(hours=1)
    print(f"Total metrics collected: {metrics_summary['total_metrics']}")
    print(f"Active alerts: {metrics_summary['alert_count']}")
    
    # Show recent alerts
    active_alerts = monitor.get_active_alerts()
    print(f"\nActive alerts: {len(active_alerts)}")
    for alert in active_alerts[:3]:  # Show first 3
        print(f"  - {alert.severity.value}: {alert.message}")
    
    # Test notifications
    print("\nTesting notifications...")
    if active_alerts:
        test_alert = active_alerts[0]
        notifier.send_notification(test_alert, ['console'])
    
    # Stop monitoring
    monitor.stop_monitoring()
    
    print(f"\n{Fore.GREEN}Advanced monitoring demonstration completed!{Style.RESET_ALL}")
    
    return {
        'health_results': health_results,
        'metrics_summary': metrics_summary,
        'active_alerts_count': len(active_alerts)
    }


if __name__ == "__main__":
    try:
        results = main()
    except Exception as e:
        print(f"{Fore.RED}Error during monitoring demonstration: {e}{Style.RESET_ALL}")
        logger.error(f"Monitoring system failed: {e}")
        import traceback
        traceback.print_exc()