
# Setup Instructions for Voices Bot

## Step 1: Clone the Repository
```sh
git clone https://github.com/your-username/voices.git
cd voices
```

## Step 2: Set Up a Virtual Environment
```sh
python3 -m venv venv
source venv/bin/activate

# On Windows use 
venv\ScriptsActivate
```

## Step 3: Install Dependencies
```sh
pip install -r requirements.txt
```

## Step 4: Configure MongoDB
```sh
mkdir -p ~/data/db
mongod --dbpath ~/data/db --bind_ip 127.0.0.1
```

## Step 5: Create a .env File
Create a `.env` file in the project root directory with the following content:
```env
DISCORD_TOKEN=your_discord_token
MONGO_URI=mongodb://127.0.0.1:27017
```

## Step 6: Run the Bot
```sh
python voices.py
```

## Troubleshooting
If you encounter any issues, ensure MongoDB is running and accessible, and that all environment variables are correctly set. For further assistance, visit our [Discord](http://stagwood.ink).
