"""
Migration script to create security-related database tables.
This script ensures all security-related tables are created in the database.
"""
import os
import logging
from app import app, db
from api_keys import ApiKey, ApiRequestLog

def run_migration():
    """Run the security database migration."""
    with app.app_context():
        try:
            # Create API key tables if they don't exist
            db.create_all()
            
            # Check if default API key exists
            default_api_key = ApiKey.query.filter_by(name="Default API Key").first()
            
            # Create default API key if it doesn't exist and API_KEY is set
            if not default_api_key and os.environ.get("API_KEY"):
                default_api_key = ApiKey(
                    api_key=os.environ.get("API_KEY"),
                    name="Default API Key",
                    description="Default API key for backward compatibility",
                    rate_limit=200,
                    is_active=True
                )
                db.session.add(default_api_key)
                db.session.commit()
                print("Default API key created successfully.")
            
            print("Security migration completed successfully.")
            return True
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error during security migration: {e}")
            print(f"Error during security migration: {e}")
            return False

if __name__ == "__main__":
    run_migration()