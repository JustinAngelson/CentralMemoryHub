import os
import logging
from flask import Flask
from flask_cors import CORS
from dotenv import load_dotenv
from database import init_db

# Configure logging
logging.basicConfig(level=logging.DEBUG)

# Load environment variables
load_dotenv()

# Create the Flask app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET")

# Enable CORS for all routes - necessary for Custom GPT API access
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

# Initialize the database
init_db()

# Import routes at the end to avoid circular imports
