import os
from dotenv import load_dotenv
from app import app, db

# Load environment variables
load_dotenv()

# Create database tables
with app.app_context():
    # Import all models to register with SQLAlchemy
    from models import ProjectDecision, UnstructuredData, SharedContext
    from api_keys import ApiKey, ApiRequestLog
    
    # Create all tables
    db.create_all()
    print("PostgreSQL database tables created successfully")
    
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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
