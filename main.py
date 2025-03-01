import os
import random
import sqlite3
import discord
from discord.ext import commands
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# Load configuration
config = {}
with open('config', 'r') as f:
    for line in f:
        if '=' in line:
            key, value = line.strip().split('=', 1)
            config[key] = value

# Set up the bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Database setup
def setup_database():
    conn = sqlite3.connect('messages.db')
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        server_id TEXT,
        channel_id TEXT,
        message_id TEXT,
        author_id TEXT,
        content TEXT,
        timestamp TEXT
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS last_processed (
        server_id TEXT PRIMARY KEY,
        last_message_id TEXT,
        timestamp TEXT
    )
    ''')
    
    conn.commit()
    return conn, cursor

conn, cursor = setup_database()

# Fetch messages since last processed
async def fetch_unprocessed_messages():
    for guild in bot.guilds:
        # Get the last processed message ID for this server
        cursor.execute('SELECT last_message_id FROM last_processed WHERE server_id = ?', (str(guild.id),))
        result = cursor.fetchone()
        last_message_id = result[0] if result else None
        
        # For new servers (no last_message_id), set a default limit
        default_history_limit = 0 # Adjust this number as needed for new servers
        
        print(f"Gathering historical messages for server {guild.name} (ID: {guild.id})")
        
        # Process each channel in the guild
        for channel in guild.text_channels:
            try:
                # Skip channels the bot can't read
                if not channel.permissions_for(guild.me).read_message_history:
                    continue
                
                print(f"Processing channel: {channel.name}")
                
                # For pagination
                last_message_batch = None
                total_processed = 0
                batch_size = 100  # Process in batches of 100
                
                # If this is a new server with no last processed message,
                # only collect up to the default limit
                remaining_to_process = default_history_limit if not last_message_id else float('inf')
                
                while remaining_to_process > 0:
                    messages = []
                    counter = 0
                    
                    # Get a batch of messages, using the last message of previous batch as before parameter
                    async for message in channel.history(limit=min(batch_size, remaining_to_process), before=last_message_batch):
                        # Stop if we hit the last processed message
                        if last_message_id and str(message.id) == last_message_id:
                            print(f"Reached last processed message in {channel.name}")
                            remaining_to_process = 0
                            break
                        
                        # Skip bot messages
                        if message.author.bot:
                            continue
                        
                        messages.append((
                            str(guild.id),
                            str(channel.id),
                            str(message.id),
                            str(message.author.id),
                            message.content,
                            message.created_at.isoformat()
                        ))
                        
                        counter += 1
                        last_message_batch = message
                    
                    # Batch insert messages
                    if messages:
                        cursor.executemany('''
                        INSERT INTO messages (server_id, channel_id, message_id, author_id, content, timestamp)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ''', messages)
                        conn.commit()
                        total_processed += len(messages)
                        print(f"Added {len(messages)} historical messages from {channel.name}")
                    
                    # If we got fewer messages than requested, we've reached the end
                    if counter < batch_size:
                        break
                    
                    # For new servers, count down from the limit
                    if not last_message_id:
                        remaining_to_process -= counter
                
                print(f"Finished processing {channel.name}, collected {total_processed} messages")
            
            except discord.Forbidden:
                print(f"No access to channel: {channel.name}")
            except Exception as e:
                print(f"Error processing channel {channel.name}: {e}")
        
        # If this is a first run on this server, set the most recent message as last_processed
        if not last_message_id:
            for channel in guild.text_channels:
                try:
                    if not channel.permissions_for(guild.me).read_message_history:
                        continue
                    
                    # Get the most recent message
                    async for message in channel.history(limit=1):
                        if not message.author.bot:
                            cursor.execute('''
                            INSERT OR REPLACE INTO last_processed (server_id, last_message_id, timestamp)
                            VALUES (?, ?, ?)
                            ''', (
                                str(guild.id),
                                str(message.id),
                                message.created_at.isoformat()
                            ))
                            conn.commit()
                            print(f"Set last processed message for new server {guild.name}")
                            break
                except:
                    continue

@bot.event
async def on_ready():
    print(f"{bot.user.name} has connected to Discord!")
    print(f"Connected to {len(bot.guilds)} servers")
    
    # Fetch and process unprocessed messages
    await fetch_unprocessed_messages()
    print("Finished gathering historical messages")

@bot.event
async def on_message(message):
    # Ignore messages from bots
    if message.author.bot:
        return
    
    # Store the message in the database
    cursor.execute('''
    INSERT INTO messages (server_id, channel_id, message_id, author_id, content, timestamp)
    VALUES (?, ?, ?, ?, ?, ?)
    ''', (
        str(message.guild.id),
        str(message.channel.id),
        str(message.id),
        str(message.author.id),
        message.content,
        message.created_at.isoformat()
    ))
    
    # Update the last processed message
    cursor.execute('''
    INSERT OR REPLACE INTO last_processed (server_id, last_message_id, timestamp)
    VALUES (?, ?, ?)
    ''', (
        str(message.guild.id),
        str(message.id),
        message.created_at.isoformat()
    ))
    
    conn.commit()
    
    # 1% chance to respond with a random message
    if random.random() < 0.01:  # 1% chance
        # Get a random message from this server
        cursor.execute('''
        SELECT content FROM messages
        WHERE server_id = ? AND content != ''
        ORDER BY RANDOM() LIMIT 1
        ''', (str(message.guild.id),))
        
        result = cursor.fetchone()
        if result:
            await message.channel.send(result[0])
    
    await bot.process_commands(message)

# Run the bot
bot.run(TOKEN)