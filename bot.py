import os
import discord
from discord.ext import commands
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler

# --- ส่วน Web Server สำหรับตอบรับ Render และ UptimeRobot ---
class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Stock Bot is Live!")

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), SimpleHTTPRequestHandler)
    server.serve_forever()

Thread(target=run_web_server, daemon=True).start()

# --- ส่วนการรัน Discord Bot ---
TOKEN = os.environ.get("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

if TOKEN:
    bot.run(TOKEN)
else:
    print("Error: DISCORD_TOKEN is missing!")
