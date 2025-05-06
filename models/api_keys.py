"""
API Key management models for the Central Memory Hub.
"""
import os
import uuid
import json
import secrets
from datetime import datetime, timedelta

from app import db
from sqlalchemy import Column, String, DateTime, Integer, Boolean, func, Text


class ApiKey(db.Model):
    """Store API keys with metadata."""
    __tablename__ = 'api_keys'

    key_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    api_key = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now())
    last_used_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    
    # Rate limiting data
    rate_limit = Column(Integer, default=100)  # Requests per minute
    
    # Usage statistics
    total_requests = Column(Integer, default=0)
    
    @classmethod
    def create(cls, name, description=None, expires_in_days=None, rate_limit=100):
        """Create a new API key.
        
        Args:
            name: Name for this API key
            description: Optional description
            expires_in_days: Days until this key expires (None = no expiration)
            rate_limit: Maximum requests per minute
            
        Returns:
            ApiKey: The newly created API key
        """
        # Generate a secure random API key
        api_key = secrets.token_urlsafe(32)
        
        # Calculate expiration date if provided
        expires_at = None
        if expires_in_days is not None:
            expires_at = datetime.now() + timedelta(days=expires_in_days)
            
        # Create the new key
        key = cls(
            api_key=api_key,
            name=name,
            description=description,
            expires_at=expires_at,
            rate_limit=rate_limit
        )
        
        db.session.add(key)
        db.session.commit()
        return key
    
    def update_last_used(self):
        """Update the last used timestamp and increment request count."""
        self.last_used_at = datetime.now()
        self.total_requests += 1
        db.session.commit()
    
    def is_valid(self):
        """Check if this API key is valid."""
        if not self.is_active:
            return False
            
        if self.expires_at and datetime.now() > self.expires_at:
            return False
            
        return True
    
    def revoke(self):
        """Revoke this API key."""
        self.is_active = False
        db.session.commit()
    
    def to_dict(self, include_key=False):
        """Convert the API key to a dictionary."""
        result = {
            "key_id": self.key_id,
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "is_active": self.is_active,
            "rate_limit": self.rate_limit,
            "total_requests": self.total_requests
        }
        
        # Include the actual API key only when explicitly requested
        # (typically only shown once when first created)
        if include_key:
            result["api_key"] = self.api_key
            
        return result


class ApiRequestLog(db.Model):
    """Log of API requests for auditing purposes."""
    __tablename__ = 'api_request_logs'
    
    log_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    api_key_id = Column(String(36), nullable=True, index=True)
    timestamp = Column(DateTime, default=func.now(), index=True)
    ip_address = Column(String(45), nullable=True)  # IPv6 can be up to 45 chars
    endpoint = Column(String(255), nullable=False)
    method = Column(String(10), nullable=False)
    status_code = Column(Integer, nullable=True)
    user_agent = Column(String(255), nullable=True)
    request_data = Column(Text, nullable=True)  # Store sanitized request data
    
    @classmethod
    def log_request(cls, api_key_id, request, status_code, include_data=False):
        """Log an API request.
        
        Args:
            api_key_id: ID of the API key used, or None
            request: Flask request object
            status_code: HTTP status code of the response
            include_data: Whether to include request data in the log
        """
        request_data = None
        if include_data and request.is_json:
            # Sanitize sensitive data before logging
            data = request.get_json()
            if isinstance(data, dict):
                # Remove any sensitive fields (passwords, tokens, etc.)
                data_copy = data.copy()
                for k in data_copy.keys():
                    if any(sensitive in k.lower() for sensitive in ['password', 'token', 'secret', 'key']):
                        data_copy[k] = '[REDACTED]'
                request_data = json.dumps(data_copy)
        
        log = cls(
            api_key_id=api_key_id,
            ip_address=request.remote_addr,
            endpoint=request.path,
            method=request.method,
            status_code=status_code,
            user_agent=request.user_agent.string if request.user_agent else None,
            request_data=request_data
        )
        
        db.session.add(log)
        db.session.commit()
        return log