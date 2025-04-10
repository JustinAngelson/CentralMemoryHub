import os
from dotenv import load_dotenv
from app import app
import routes

# Load environment variables
load_dotenv()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
