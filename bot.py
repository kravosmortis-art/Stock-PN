import os
import sqlite3
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import discord
from discord.ext import commands
from discord.ui import Button, View, Modal, TextInput, Select

# --- Web Server เพื่อให้ Render และ UptimeRobot เช็ก Health Check ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b"Bot is live!")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=run_web_server, daemon=True).start()

# --- 1. รายชื่อไอเทมเริ่มต้น ---
DEFAULT_ITEMS = [
    "ทองแดง", "หยก", "เปลือกหอย", "แร่ภูเขาไฟ", "น็อต",
    "โครงปืน", "ไกปืน", "แกนไม้แข็ง", "แกนไม้อ่อน", "ท่อนไม้",
    "พานท้ายปืนรีพีทเตอร์", "ปลายกระบอกปืนรีพีทเตอร์", "ลำกล้องลูกซอง", "พานท้ายลูกซอง", "แบบแปลนดับเบิลบาเรลช็อตกัน",
    "ปากกระบอกปืน", "ด้ามปีนรีพีทเตอร์", "สปริง", "แบบแปลนปืนเฮนรี่", "แบบแปลนสกอฟิลด์",
    "ด้ามปืน", "อลูมิเนียม", "เหล็ก"
]

# --- 2. ตั้งค่า Bot และ Database ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

def get_db_connection():
    return sqlite3.connect("inventory.db", timeout=10)

# สร้างตารางเริ่มต้น
conn = get_db_connection()
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS inventory (
    item_name TEXT PRIMARY KEY,
    amount INTEGER DEFAULT 0
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_name TEXT,
    action TEXT,
    item_name TEXT,
    amount INTEGER,
    remaining_amount INTEGER,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
)
""")
for item in DEFAULT_ITEMS:
    cursor.execute("INSERT OR IGNORE INTO inventory (item_name, amount) VALUES (?, 0)", (item,))
conn.commit()
conn.close()


# --- 3. หน้าต่างกรอกข้อมูล (Modals) ---

class CreateNewItemModal(Modal, title="➕ เพิ่มประเภทไอเทมใหม่"):
    item_name = TextInput(label="ชื่อไอเทมใหม่", placeholder="เช่น ปืนไรเฟิล, แร่นกยูง", required=True)
    initial_amount = TextInput(label="จำนวนเริ่มต้น", placeholder="เช่น 0 หรือ 100", default="0", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        name = self.item_name.value.strip()
        try:
            qty = int(self.initial_amount.value)
            if qty < 0:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("❌ กรุณากรอกจำนวนเป็นตัวเลขเต็มบวกหรือ 0 เท่านั้น", ephemeral=True)
            return

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT amount FROM inventory WHERE item_name = ?", (name,))
        if cursor.fetchone():
            conn.close()
            await interaction.response.send_message(f"❌ มีไอเทมชื่อ **{name}** อยู่ในคลังแล้ว!", ephemeral=True)
            return

        cursor.execute("INSERT INTO inventory (item_name, amount) VALUES (?, ?)", (name, qty))
        cursor.execute(
            "INSERT INTO logs (user_name, action, item_name, amount, remaining_amount) VALUES (?, 'CREATE', ?, ?, ?)",
            (interaction.user.display_name, name, qty, qty)
        )
        conn.commit()
        conn.close()

        await interaction.response.send_message(f"✅ **{interaction.user.display_name}** เพิ่มไอเทมใหม่ **{name}** (จำนวน: {qty:,} ชิ้น) เข้าคลังเรียบร้อย!", ephemeral=False)


class AddItemModal(Modal, title="📥 ฝาก/เพิ่มไอเทมเข้าคลัง"):
    def __init__(self, item_name: str):
        super().__init__()
        self.selected_item = item_name
        self.amount = TextInput(label=f"จำนวนที่ต้องการเพิ่ม: {item_name[:20]}", placeholder="เช่น 10", required=True)
        self.add_item(self.amount)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            qty = int(self.amount.value)
            if qty <= 0:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("❌ กรุณากรอกจำนวนเป็นตัวเลขเต็มบวกมากกว่า 0", ephemeral=True)
            return

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT amount FROM inventory WHERE item_name = ?", (self.selected_item,))
        row = cursor.fetchone()
        new_qty = (row[0] if row else 0) + qty

        cursor.execute("UPDATE inventory SET amount = ? WHERE item_name = ?", (new_qty, self.selected_item))
        cursor.execute(
            "INSERT INTO logs (user_name, action, item_name, amount, remaining_amount) VALUES (?, 'ADD', ?, ?, ?)",
            (interaction.user.display_name, self.selected_item, qty, new_qty)
        )
        conn.commit()
        conn.close()

        await interaction.response.send_message(f"📥 **{interaction.user.display_name}** ฝาก **{self.selected_item}** +{qty:,} ชิ้น (คงเหลือในคลังกลาง: `{new_qty:,}` ชิ้น)", ephemeral=False)


class RemoveItemModal(Modal, title="📤 ถอน/เบิกไอเทมออกจากคลัง"):
    def __init__(self, item_name: str):
        super().__init__()
        self.selected_item = item_name
        self.amount = TextInput(label=f"จำนวนที่ต้องการถอน: {item_name[:20]}", placeholder="เช่น 5", required=True)
        self.add_item(self.amount)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            qty = int(self.amount.value)
            if qty <= 0:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("❌ กรุณากรอกจำนวนเป็นตัวเลขเต็มบวกมากกว่า 0", ephemeral=True)
            return

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT amount FROM inventory WHERE item_name = ?", (self.selected_item,))
        row = cursor.fetchone()
        current_qty = row[0] if row else 0

        if current_qty < qty:
            conn.close()
            await interaction.response.send_message(f"❌ ไอเทม **{self.selected_item}** มีไม่เพียงพอ (คงเหลือปัจจุบัน: `{current_qty:,}` ชิ้น)", ephemeral=True)
            return

        new_qty = current_qty - qty
        cursor.execute("UPDATE inventory SET amount = ? WHERE item_name = ?", (new_qty, self.selected_item))
        cursor.execute(
            "INSERT INTO logs (user_name, action, item_name, amount, remaining_amount) VALUES (?, 'REMOVE', ?, ?, ?)",
            (interaction.user.display_name, self.selected_item, qty, new_qty)
        )
        conn.commit()
        conn.close()

        await interaction.response.send_message(f"📤 **{interaction.user.display_name}** เบิก **{self.selected_item}** -{qty:,} ชิ้น (คงเหลือในคลังกลาง: `{new_qty:,}` ชิ้น)", ephemeral=False)


# --- 4. เมนู Dropdown เลือกไอเทม ---

class ItemSelectDropdown(Select):
    def __init__(self, action_type: str, items_page: list, page_num: int = 1):
        self.action_type = action_type
        
        options = [
            discord.SelectOption(
                label=name[:100], 
                description=f"คงเหลือในคลัง: {qty:,} ชิ้น", 
                value=name
            )
            for name, qty in items_page
        ]

        placeholder = f"📥 เลือกไอเทมนำเข้า (หน้า {page_num})..." if action_type == "add" else f"📤 เลือกไอเทมถอน (หน้า {page_num})..."
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        selected_item = self.values[0]
        if self.action_type == "add":
            await interaction.response.send_modal(AddItemModal(selected_item))
        elif self.action_type == "remove":
            await interaction.response.send_modal(RemoveItemModal(selected_item))


class ItemSelectView(View):
    def __init__(self, action_type: str):
        super().__init__(timeout=180)
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT item_name, amount FROM inventory ORDER BY item_name ASC")
        items = cursor.fetchall()
        conn.close()

        chunk_size = 25
        pages = [items[i:i + chunk_size] for i in range(0, len(items), chunk_size)]

        for idx, page in enumerate(pages, start=1):
            if page:
                self.add_item(ItemSelectDropdown(action_type, page, idx))


# --- 5. ปุ่มกดหลัก (Main Control Panel) ---

class MainControlView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="เพิ่มไอเทมเข้าคลัง", style=discord.ButtonStyle.green, custom_id="btn_add_item", emoji="📥")
    async def add_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message("เลือกไอเทมที่ต้องการนำเข้าจากเมนูด้านล่าง:", view=ItemSelectView("add"), ephemeral=True)

    @discord.ui.button(label="ถอนไอเทมออกจากคลัง", style=discord.ButtonStyle.red, custom_id="btn_remove_item", emoji="📤")
    async def remove_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message("เลือกไอเทมที่ต้องการถอนออกจากเมนูด้านล่าง:", view=ItemSelectView("remove"), ephemeral=True)

    @discord.ui.button(label="เพิ่มประเภทไอเทมใหม่", style=discord.ButtonStyle.secondary, custom_id="btn_create_item", emoji="➕")
    async def create_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(CreateNewItemModal())

    @discord.ui.button(label="เช็กสต็อกคลังกลาง", style=discord.ButtonStyle.primary, custom_id="btn_check_stock", emoji="📦")
    async def stock_button(self, interaction: discord.Interaction, button: Button):
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT item_name, amount FROM inventory ORDER BY item_name ASC")
        rows = cursor.fetchall()
        conn.close()

        total_all_items = sum(qty for _, qty in rows)

        embed = discord.Embed(
            title="📦 รายการสต็อกคลังสินค้าส่วนกลาง", 
            description=f"📊 **ยอดรวมไอเทมทุกชนิดในคลัง:** `{total_all_items:,}` ชิ้น\n" + "─"*30,
            color=discord.Color.gold()
        )
        
        stock_list = [f"• **{item}**: `{qty:,}` ชิ้น" for item, qty in rows]
        formatted_text = "\n".join(stock_list)

        if len(formatted_text) > 1024:
            embed.add_field(name="รายการไอเทมคงเหลือ (1)", value="\n".join(stock_list[:15]), inline=False)
            embed.add_field(name="รายการไอเทมคงเหลือ (2)", value="\n".join(stock_list[15:]), inline=False)
        else:
            embed.add_field(name="รายการไอเทมคงเหลือ", value=formatted_text, inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="ดูประวัติเพิ่ม-ถอน", style=discord.ButtonStyle.secondary, custom_id="btn_check_history", emoji="📜")
    async def history_button(self, interaction: discord.Interaction, button: Button):
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_name, action, item_name, amount, remaining_amount, timestamp FROM logs ORDER BY id DESC LIMIT 10")
        logs = cursor.fetchall()
        conn.close()

        embed = discord.Embed(
            title="📜 ประวัติการทำรายการล่าสุด (10 รายการ)",
            color=discord.Color.blue()
        )

        if not logs:
            embed.description = "ยังไม่มีประวัติการทำรายการในระบบ"
        else:
            log_entries = []
            for user, action, item, qty, remain, ts in logs:
                if action == "ADD":
                    act_str = f"📥 **ฝาก/เพิ่ม** `{item}` (+{qty:,})"
                elif action == "REMOVE":
                    act_str = f"📤 **ถอน/เบิก** `{item}` (-{qty:,})"
                elif action == "CREATE":
                    act_str = f"✨ **สร้างไอเทมใหม่** `{item}` ({qty:,})"
                else:
                    act_str = f"⚙️ {action} `{item}`"

                log_entries.append(f"• {act_str}\n  └ โดย: **{user}** | คงเหลือ: `{remain:,}` ชิ้น | เวลา: `{ts[:19]}`")

            embed.description = "\n\n".join(log_entries)

        await interaction.response.send_message(embed=embed, ephemeral=True)


# --- 6. คำสั่งเริ่มต้นระบบ ---

@bot.command(name="setup")
async def setup_panel(ctx):
    embed = discord.Embed(
        title="🎒 ระบบจัดการคลังสินค้าส่วนกลาง (Centralized Inventory)",
        description="สมาชิกทุกคนใช้คลังเดียวกัน สามารถกดเพิ่ม ถอน เช็กสต็อก หรือดูประวัติย้อนหลังได้เลยครับ",
        color=discord.Color.blue()
    )
    embed.add_field(name="📥 Add Quantity", value="เพิ่มจำนวนไอเทมที่มีอยู่ในคลัง", inline=False)
    embed.add_field(name="📤 Withdraw Item", value="เบิกหรือหักจำนวนไอเทมออกจากคลัง", inline=False)
    embed.add_field(name="➕ Add New Item", value="สร้างรายการไอเทมชนิดใหม่เข้าสู่คลัง", inline=False)
    embed.add_field(name="📦 Check Stock", value="ดูรายการไอเทมและยอดรวมคงเหลือทั้งหมด", inline=False)
    embed.add_field(name="📜 History Log", value="ดูรายการประวัติฝาก/เบิกย้อนหลัง 10 รายการล่าสุด", inline=False)

    await ctx.send(embed=embed, view=MainControlView())


@bot.event
async def on_ready():
    bot.add_view(MainControlView())
    print(f"Logged in as {bot.user}")


# บรรทัดรันบอท ดึง Token จาก Environment Variables ของ Render
bot.run(os.environ.get("DISCORD_TOKEN") or os.environ.get("DISCORD_BOT_TOKEN"))
