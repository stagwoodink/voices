# Set Up a Virtual Environment
python3 -m venv venv
source venv/bin/activate  
# On Windows use 
venv\Scripts\activate

# Install Dependencies
pip install -r requirements.txt

# Create a .env File with your credentials
echo "DISCORD_TOKEN=your_discord_token" > .env
echo "MONGO_URI=mongodb://localhost:27017/logs" >> .env

# Run MongoDB using Docker
docker run -d -p 27017:27017 --name mongodb mongo:latest

# Run the Bot
python voices.py
