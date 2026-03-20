import os
from dotenv import load_dotenv
from app import app, db

# Load environment variables
load_dotenv()

# Create database tables
with app.app_context():
    # Import all models to register with SQLAlchemy
    from models import ProjectDecision, UnstructuredData, SharedContext, InvitationToken, OrgProfile, Resource
    from api_keys import ApiKey, ApiRequestLog
    
    # Create all tables
    db.create_all()
    print("PostgreSQL database tables created successfully")

    # Add new columns to agent_directory if they don't exist yet (safe migration)
    try:
        with db.engine.connect() as conn:
            migrations = [
                "ALTER TABLE agent_directory ADD COLUMN IF NOT EXISTS skills JSONB",
                "ALTER TABLE agent_directory ADD COLUMN IF NOT EXISTS usual_model VARCHAR(100)",
                "ALTER TABLE agent_directory ADD COLUMN IF NOT EXISTS join_date TIMESTAMP",
                "ALTER TABLE agent_directory ADD COLUMN IF NOT EXISTS birth_date TIMESTAMP",
            ]
            for sql in migrations:
                conn.execute(db.text(sql))
            conn.commit()
        print("Agent directory columns migrated successfully")
    except Exception as e:
        print(f"Column migration note: {e}")

    # Add extended profile columns to users table (safe migration)
    try:
        with db.engine.connect() as conn:
            user_migrations = [
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS first_name VARCHAR(64)",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_name VARCHAR(64)",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS company_name VARCHAR(128)",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR(32)",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS whatsapp VARCHAR(32)",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS signal VARCHAR(32)",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram VARCHAR(64)",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS website VARCHAR(255)",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS profile_image VARCHAR(255)",
            ]
            for sql in user_migrations:
                conn.execute(db.text(sql))
            conn.commit()
        print("User profile columns migrated successfully")
    except Exception as e:
        print(f"User column migration note: {e}")
    
    # Ensure resources table columns exist (safe migration)
    try:
        with db.engine.connect() as conn:
            resource_migrations = [
                "ALTER TABLE resources ADD COLUMN IF NOT EXISTS name VARCHAR(255)",
                "ALTER TABLE resources ADD COLUMN IF NOT EXISTS type VARCHAR(32)",
                "ALTER TABLE resources ADD COLUMN IF NOT EXISTS purpose TEXT",
                "ALTER TABLE resources ADD COLUMN IF NOT EXISTS url VARCHAR(512)",
                "ALTER TABLE resources ADD COLUMN IF NOT EXISTS poc_type VARCHAR(32)",
                "ALTER TABLE resources ADD COLUMN IF NOT EXISTS related_skills TEXT",
                "ALTER TABLE resources ADD COLUMN IF NOT EXISTS description TEXT",
                "ALTER TABLE resources ADD COLUMN IF NOT EXISTS created_by VARCHAR(36)",
                "ALTER TABLE resources ADD COLUMN IF NOT EXISTS created_at TIMESTAMP",
                "ALTER TABLE resources ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP",
            ]
            for sql in resource_migrations:
                conn.execute(db.text(sql))
            conn.commit()
        print("Resources table columns migrated successfully")
    except Exception as e:
        print(f"Resources column migration note: {e}")

    # Initialize a default API key if none exists
    default_api_key = ApiKey.query.filter_by(name="Default API Key").first()
    if not default_api_key and os.environ.get("API_KEY"):
        # Create a default API key using the API_KEY from environment
        default_api_key = ApiKey(
            api_key=os.environ.get("API_KEY"),
            name="Default API Key",
            description="Default API key for backward compatibility",
            rate_limit=200,
            is_active=True
        )
        db.session.add(default_api_key)
        db.session.commit()
        print("Default API key initialized")

# Import routes after models are registered
import routes

# Import admin routes for settings and security management
import admin_routes

# Import security modules to ensure they are available
import csrf
import validation
import xss_protection
import secure_api

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
