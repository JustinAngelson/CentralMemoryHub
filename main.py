import os
from dotenv import load_dotenv
from app import app, db
import routes

# Load environment variables
load_dotenv()

# Create database tables
with app.app_context():
    # Import models to register them with SQLAlchemy
    from models import ProjectDecision, UnstructuredData, SharedContext
    db.create_all()
    print("PostgreSQL database tables created successfully")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
