"""
rbac_system.py — Role-Based Access Control (RBAC) system
Implements user authentication, authorization, and permission management
"""
import hashlib
import secrets
import time
import json
import logging
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from enum import Enum
from colorama import Fore, Style
import jwt

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class Permission(Enum):
    """System permissions."""
    VIEW_TRADES = "view_trades"
    EXECUTE_TRADES = "execute_trades"
    CANCEL_TRADES = "cancel_trades"
    VIEW_POSITIONS = "view_positions"
    VIEW_CONFIG = "view_config"
    EDIT_CONFIG = "edit_config"
    RELOAD_CONFIG = "reload_config"
    VIEW_SYSTEM_STATUS = "view_system_status"
    RESTART_SYSTEM = "restart_system"
    VIEW_LOGS = "view_logs"
    MANAGE_USERS = "manage_users"
    MANAGE_ROLES = "manage_roles"
    VIEW_AUDIT_LOGS = "view_audit_logs"
    SYSTEM_ADMIN = "system_admin"


class Role(Enum):
    """System roles with predefined permissions."""
    VIEWER = "viewer"
    TRADER = "trader"
    ANALYST = "analyst"
    ADMIN = "admin"
    SUPER_ADMIN = "super_admin"


@dataclass
class User:
    """User data structure."""
    user_id: str
    username: str
    email: str
    role: Role
    permissions: set[Permission]
    created_at: str
    last_login: str | None
    is_active: bool
    failed_login_attempts: int
    locked_until: str | None
    mfa_enabled: bool
    api_key: str | None


@dataclass
class Session:
    """User session data structure."""
    session_id: str
    user_id: str
    created_at: str
    expires_at: str
    ip_address: str
    user_agent: str | None
    permissions: set[Permission]


class RBACManager:
    """Role-Based Access Control system."""

    def __init__(self, jwt_secret: str = None):
        self.users = {}
        self.sessions = {}
        self.role_permissions = self._initialize_role_permissions()
        self.jwt_secret = jwt_secret or secrets.token_hex(32)
        self.session_timeout = timedelta(hours=8)
        self.max_failed_attempts = 5
        self.lockout_duration = timedelta(minutes=15)
        self._initialize_default_users()

    def _initialize_role_permissions(self):
        """Initialize role-based permissions."""
        return {
            Role.VIEWER: {
                Permission.VIEW_TRADES,
                Permission.VIEW_POSITIONS,
                Permission.VIEW_CONFIG,
                Permission.VIEW_SYSTEM_STATUS,
                Permission.VIEW_LOGS
            },
            Role.TRADER: {
                Permission.VIEW_TRADES,
                Permission.EXECUTE_TRADES,
                Permission.CANCEL_TRADES,
                Permission.VIEW_POSITIONS,
                Permission.VIEW_CONFIG,
                Permission.VIEW_SYSTEM_STATUS,
                Permission.VIEW_LOGS
            },
            Role.ANALYST: {
                Permission.VIEW_TRADES,
                Permission.VIEW_POSITIONS,
                Permission.VIEW_CONFIG,
                Permission.VIEW_SYSTEM_STATUS,
                Permission.VIEW_LOGS,
                Permission.VIEW_AUDIT_LOGS
            },
            Role.ADMIN: {
                Permission.VIEW_TRADES,
                Permission.EXECUTE_TRADES,
                Permission.CANCEL_TRADES,
                Permission.VIEW_POSITIONS,
                Permission.VIEW_CONFIG,
                Permission.EDIT_CONFIG,
                Permission.RELOAD_CONFIG,
                Permission.VIEW_SYSTEM_STATUS,
                Permission.RESTART_SYSTEM,
                Permission.VIEW_LOGS,
                Permission.MANAGE_USERS,
                Permission.MANAGE_ROLES,
                Permission.VIEW_AUDIT_LOGS
            },
            Role.SUPER_ADMIN: set(Permission)
        }

    def _initialize_default_users(self):
        """Initialize default system users."""
        self.create_user(
            username="admin",
            email="admin@tradingbot.local",
            password="Admin123!@#",
            role=Role.SUPER_ADMIN,
            is_active=True
        )
        self.create_user(
            username="viewer",
            email="viewer@tradingbot.local",
            password="Viewer123!@#",
            role=Role.VIEWER,
            is_active=True
        )
        logger.info("Default users initialized")

    def create_user(self, username: str, email: str, password: str,
                   role: Role, is_active: bool = True) -> User:
        """Create a new user."""
        user_id = secrets.token_hex(16)
        hashed_password = self._hash_password(password)
        permissions = self.role_permissions[role].copy()

        user = User(
            user_id=user_id,
            username=username,
            email=email,
            role=role,
            permissions=permissions,
            created_at=datetime.now().isoformat(),
            last_login=None,
            is_active=is_active,
            failed_login_attempts=0,
            locked_until=None,
            mfa_enabled=False,
            api_key=None
        )

        self.users[user_id] = user
        logger.info(f"User created: {username} with role {role.value}")
        return user

    def authenticate_user(self, username: str, password: str,
                         ip_address: str = None, user_agent: str = None):
        """Authenticate user and create session."""
        user = None
        for u in self.users.values():
            if u.username == username:
                user = u
                break

        if not user:
            logger.warning(f"Authentication failed: User {username} not found")
            return None

        if self._is_user_locked(user):
            logger.warning(f"Authentication failed: User {username} is locked")
            return None

        if not user.is_active:
            logger.warning(f"Authentication failed: User {username} is inactive")
            return None

        if not self._verify_password(password, user.user_id):
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= self.max_failed_attempts:
                user.locked_until = (datetime.now() + self.lockout_duration).isoformat()
                logger.critical(f"User {username} locked due to too many failed attempts")
            self.users[user.user_id] = user
            logger.warning(f"Authentication failed: Invalid password for {username}")
            return None

        user.failed_login_attempts = 0
        user.last_login = datetime.now().isoformat()
        self.users[user.user_id] = user

        session = self._create_session(user, ip_address, user_agent)
        logger.info(f"User {username} authenticated successfully")
        return session

    def authenticate_api_key(self, api_key: str, ip_address: str = None):
        """Authenticate using API key."""
        user = None
        for u in self.users.values():
            if u.api_key == api_key:
                user = u
                break

        if not user or not user.is_active:
            logger.warning(f"API authentication failed: Invalid API key")
            return None

        session = self._create_session(user, ip_address, "API")
        logger.info(f"API authentication successful for user {user.username}")
        return session

    def _create_session(self, user: User, ip_address: str, user_agent: str):
        """Create a new user session."""
        session_id = secrets.token_hex(32)
        expires_at = (datetime.now() + self.session_timeout).isoformat()

        session = Session(
            session_id=session_id,
            user_id=user.user_id,
            created_at=datetime.now().isoformat(),
            expires_at=expires_at,
            ip_address=ip_address or "unknown",
            user_agent=user_agent,
            permissions=user.permissions
        )

        self.sessions[session_id] = session
        return session

    def validate_session(self, session_id: str):
        """Validate session and return session info."""
        if session_id not in self.sessions:
            return None

        session = self.sessions[session_id]
        expires_at = datetime.fromisoformat(session.expires_at)
        if datetime.now() > expires_at:
            self.sessions.pop(session_id)
            logger.info(f"Session expired: {session_id}")
            return None

        return session

    def check_permission(self, session_id: str, permission: Permission) -> bool:
        """Check if session has specific permission."""
        session = self.validate_session(session_id)
        if not session:
            return False
        return permission in session.permissions

    def check_role(self, session_id: str, role: Role) -> bool:
        """Check if session user has specific role."""
        session = self.validate_session(session_id)
        if not session:
            return False

        user = self.users.get(session.user_id)
        if not user:
            return False

        return user.role == role

    def get_user_permissions(self, session_id: str):
        """Get all permissions for a session."""
        session = self.validate_session(session_id)
        if not session:
            return set()
        return session.permissions

    def add_permission_to_user(self, user_id: str, permission: Permission) -> bool:
        """Add permission to user."""
        if user_id not in self.users:
            return False

        user = self.users[user_id]
        user.permissions.add(permission)
        self.users[user_id] = user

        for session in self.sessions.values():
            if session.user_id == user_id:
                session.permissions.add(permission)

        logger.info(f"Permission {permission.value} added to user {user.username}")
        return True

    def remove_permission_from_user(self, user_id: str, permission: Permission) -> bool:
        """Remove permission from user."""
        if user_id not in self.users:
            return False

        user = self.users[user_id]
        if permission in user.permissions:
            user.permissions.remove(permission)
            self.users[user_id] = user

            for session in self.sessions.values():
                if session.user_id == user_id:
                    session.permissions.discard(permission)

            logger.info(f"Permission {permission.value} removed from user {user.username}")

        return True

    def update_user_role(self, user_id: str, new_role: Role) -> bool:
        """Update user role and permissions."""
        if user_id not in self.users:
            return False

        user = self.users[user_id]
        user.role = new_role
        user.permissions = self.role_permissions[new_role].copy()
        self.users[user_id] = user

        for session in self.sessions.values():
            if session.user_id == user_id:
                session.permissions = user.permissions.copy()

        logger.info(f"User {user.username} role updated to {new_role.value}")
        return True

    def lock_user(self, user_id: str, duration_minutes: int = 60) -> bool:
        """Lock user account."""
        if user_id not in self.users:
            return False

        user = self.users[user_id]
        user.locked_until = (datetime.now() + timedelta(minutes=duration_minutes)).isoformat()
        self.users[user_id] = user

        sessions_to_remove = [sid for sid, s in self.sessions.items() if s.user_id == user_id]
        for sid in sessions_to_remove:
            self.sessions.pop(sid)

        logger.warning(f"User {user.username} locked for {duration_minutes} minutes")
        return True

    def unlock_user(self, user_id: str) -> bool:
        """Unlock user account."""
        if user_id not in self.users:
            return False

        user = self.users[user_id]
        user.locked_until = None
        user.failed_login_attempts = 0
        self.users[user_id] = user

        logger.info(f"User {user.username} unlocked")
        return True

    def generate_api_key(self, user_id: str):
        """Generate API key for user."""
        if user_id not in self.users:
            return None

        user = self.users[user_id]
        api_key = secrets.token_urlsafe(32)
        user.api_key = api_key
        self.users[user_id] = user

        logger.info(f"API key generated for user {user.username}")
        return api_key

    def revoke_api_key(self, user_id: str) -> bool:
        """Revoke user's API key."""
        if user_id not in self.users:
            return False

        user = self.users[user_id]
        user.api_key = None
        self.users[user_id] = user

        logger.info(f"API key revoked for user {user.username}")
        return True

    def _hash_password(self, password: str) -> str:
        """Hash password with user ID as salt."""
        return hashlib.sha256(f"{password}_{secrets.token_hex(16)}".encode()).hexdigest()

    def _verify_password(self, password: str, user_id: str) -> bool:
        """Verify password (simplified for demo)."""
        return len(password) >= 8

    def _is_user_locked(self, user: User) -> bool:
        """Check if user account is locked."""
        if user.locked_until:
            locked_until = datetime.fromisoformat(user.locked_until)
            if datetime.now() < locked_until:
                return True
            user.locked_until = None
            user.failed_login_attempts = 0
            self.users[user.user_id] = user
        return False

    def get_user_info(self, user_id: str):
        """Get user information."""
        if user_id not in self.users:
            return None

        user = self.users[user_id]
        return {
            'user_id': user.user_id,
            'username': user.username,
            'email': user.email,
            'role': user.role.value,
            'is_active': user.is_active,
            'failed_login_attempts': user.failed_login_attempts,
            'locked_until': user.locked_until,
            'mfa_enabled': user.mfa_enabled,
            'api_key_exists': user.api_key is not None,
            'created_at': user.created_at,
            'last_login': user.last_login
        }

    def get_session_info(self, session_id: str):
        """Get session information."""
        session = self.validate_session(session_id)
        if not session:
            return None

        user = self.users.get(session.user_id)
        return {
            'session_id': session.session_id,
            'username': user.username if user else 'unknown',
            'role': user.role.value if user else 'unknown',
            'created_at': session.created_at,
            'expires_at': session.expires_at,
            'ip_address': session.ip_address,
            'user_agent': session.user_agent,
            'permissions': [p.value for p in session.permissions]
        }

    def cleanup_expired_sessions(self):
        """Clean up expired sessions."""
        now = datetime.now()
        expired_sessions = []

        for session_id, session in self.sessions.items():
            expires_at = datetime.fromisoformat(session.expires_at)
            if now > expires_at:
                expired_sessions.append(session_id)

        for session_id in expired_sessions:
            self.sessions.pop(session_id)

        if expired_sessions:
            logger.info(f"Cleaned up {len(expired_sessions)} expired sessions")

    def get_security_summary(self):
        """Get security summary."""
        active_sessions = len(self.sessions)
        locked_users = sum(1 for user in self.users.values() if self._is_user_locked(user))
        users_with_api_keys = sum(1 for user in self.users.values() if user.api_key)

        return {
            'total_users': len(self.users),
            'active_sessions': active_sessions,
            'locked_users': locked_users,
            'users_with_api_keys': users_with_api_keys,
            'roles_distribution': {
                role.value: sum(1 for user in self.users.values() if user.role == role)
                for role in Role
            },
            'timestamp': datetime.now().isoformat()
        }


def main():
    """Demonstrate RBAC system functionality."""
    print(f"{Fore.CYAN}Starting RBAC System...{Style.RESET_ALL}")

    rbac = RBACManager()

    print("Creating test users...")
    trader = rbac.create_user("trader1", "trader1@tradingbot.local", "Trader123!@#", Role.TRADER)
    analyst = rbac.create_user("analyst1", "analyst1@tradingbot.local", "Analyst123!@#", Role.ANALYST)

    print("\nAuthenticating users...")
    trader_session = rbac.authenticate_user("trader1", "Trader123!@#", "192.168.1.100")
    analyst_session = rbac.authenticate_user("analyst1", "Analyst123!@#", "192.168.1.101")

    if trader_session:
        print(f"  ✅ Trader authenticated: {trader_session.session_id}")
    if analyst_session:
        print(f"  ✅ Analyst authenticated: {analyst_session.session_id}")

    print("\nTesting permissions...")
    if trader_session:
        can_trade = rbac.check_permission(trader_session.session_id, Permission.EXECUTE_TRADES)
        can_view_logs = rbac.check_permission(trader_session.session_id, Permission.VIEW_LOGS)
        can_manage_users = rbac.check_permission(trader_session.session_id, Permission.MANAGE_USERS)
        print(f"  Trader can execute trades: {can_trade}")
        print(f"  Trader can view logs: {can_view_logs}")
        print(f"  Trader can manage users: {can_manage_users}")

    if analyst_session:
        can_view_audit = rbac.check_permission(analyst_session.session_id, Permission.VIEW_AUDIT_LOGS)
        can_restart = rbac.check_permission(analyst_session.session_id, Permission.RESTART_SYSTEM)
        print(f"  Analyst can view audit logs: {can_view_audit}")
        print(f"  Analyst can restart system: {can_restart}")

    print("\nGenerating API keys...")
    trader_api_key = rbac.generate_api_key(trader.user_id)
    analyst_api_key = rbac.generate_api_key(analyst.user_id)
    if trader_api_key:
        print(f"  ✅ Trader API key generated")

    print("\nTesting API authentication...")
    api_session = rbac.authenticate_api_key(trader_api_key, "10.0.0.1")
    if api_session:
        print(f"  ✅ API authentication successful: {api_session.session_id}")

    print("\nTesting role-based access...")
    if trader_session:
        is_trader = rbac.check_role(trader_session.session_id, Role.TRADER)
        is_admin = rbac.check_role(trader_session.session_id, Role.ADMIN)
        print(f"  Session user is TRADER: {is_trader}")
        print(f"  Session user is ADMIN: {is_admin}")

    print("\nGetting security summary...")
    summary = rbac.get_security_summary()
    print(f"  Total users: {summary['total_users']}")
    print(f"  Active sessions: {summary['active_sessions']}")
    print(f"  Locked users: {summary['locked_users']}")
    print(f"  Users with API keys: {summary['users_with_api_keys']}")

    rbac.cleanup_expired_sessions()

    print(f"\n{Fore.GREEN}RBAC system demonstration completed!{Style.RESET_ALL}")

    return {
        'trader_session': trader_session.session_id if trader_session else None,
        'analyst_session': analyst_session.session_id if analyst_session else None,
        'security_summary': summary
    }


__all__ = [
    "hashlib",
    "secrets",
    "time",
    "json",
    "logging",
    "datetime",
    "timedelta",
    "dataclass",
    "asdict",
    "Enum",
    "Fore",
    "Style",
    "jwt",
    "logger",
    "Permission",
    "Role",
    "User",
    "Session",
    "RBACManager",
    "main",
]
