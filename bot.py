import os
import sqlite3
import re
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import discord
from discord.ext import commands
from discord.ui import Button, View, Modal, TextInput

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


# --- ฟังก์ชัน Helper สำหรับแกะข้อความไอเทม + จำนวน ---
def parse_items_input(text: str):
    parsed = []
    lines = text.strip().split("\n")
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # แยกข้อความโดยจับกลุ่ม ชื่อไอเทม กับ จำนวนตัวเลขด้านหลัง
        match = re.search(r"^(.+?)[\s:=,]+(\d+)$", line)
        if match:
            item_name = match.group(1).strip()
            qty = int(match.group(2))
            if qty > 0:
                parsed.append((item_name, qty))
    return parsed


# --- 3. หน้าต่างกรอกข้อมูลแบบรองรับหลายรายการ (Modals) ---

class CreateNewItemModal(Modal, title="➕ เพิ่มประเภทไอเทมใหม่ (หลายรายการ)"):
    items_input = TextInput(
        label="รายชื่อไอเทมใหม่ (ใส่แยกบรรทัด)",
        style=discord.TextStyle.paragraph,
        placeholder="เช่น:\nกระสุนปืนไรเฟิล\nยาทำแผล\nเนื้อตากแห้ง",
        required=True,
        max_length=1000
    )
    initial_amount = TextInput(
        label="จำนวนเริ่มต้น (ตั้งเท่ากันทุกรายการ)",
        placeholder="เช่น 0 หรือ 100",
        default="0",
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            qty = int(self.initial_amount.value)
            if qty < 0:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("❌ กรุณากรอกจำนวนเริ่มต้นเป็นตัวเลขเต็มบวกหรือ 0", ephemeral=True)
            return

        raw_text = self.items_input.value.replace(",", "\n")
        raw_list = [item.strip() for item in raw_text.split("\n") if item.strip()]

        if not raw_list:
            await interaction.response.send_message("❌ กรุณากรอกชื่อไอเทมอย่างน้อย 1 รายการ", ephemeral=True)
            return

        conn = get_db_connection()
        cursor = conn.cursor()
        added_items, skipped_items = [], []

        for name in raw_list:
            cursor.execute("SELECT amount FROM inventory WHERE item_name = ?", (name,))
            if cursor.fetchone():
                skipped_items.append(name)
            else:
                cursor.execute("INSERT INTO inventory (item_name, amount) VALUES (?, ?)", (name, qty))
                cursor.execute(
                    "INSERT INTO logs (user_name, action, item_name, amount, remaining_amount) VALUES (?, 'CREATE', ?, ?, ?)",
                    (interaction.user.display_name, name, qty, qty)
                )
                added_items.append(name)

        conn.commit()
        conn.close()

        msg = []
        if added_items:
            msg.append(f"✅ **{interaction.user.display_name}** เพิ่มไอเทมใหม่ `{len(added_items)}` รายการ (จำนวน: {qty:,}):\n" + ", ".join([f"**{i}**" for i in added_items]))
        if skipped_items:
            msg.append(f"⚠️ ข้ามเนื่องจากมีอยู่แล้ว `{len(skipped_items)}` รายการ:\n" + ", ".join([f"**{i}**" for i in skipped_items]))

        await interaction.response.send_message("\n\n".join(msg), ephemeral=False)


class MultiAddItemModal(Modal, title="📥 ฝาก/เพิ่มไอเทมเข้าคลัง (หลายรายการ)"):
    items_input = TextInput(
        label="พิมพ์ ชื่อไอเทม ตามด้วย จำนวน (แยกบรรทัด)",
        style=discord.TextStyle.paragraph,
        placeholder="เช่น:\nทองแดง 50\nเหล็ก 100\nสปริง 20",
        required=True,
        max_length=1500
    )

    async def on_submit(self, interaction: discord.Interaction):
        parsed = parse_items_input(self.items_input.value)
        if not parsed:
            await interaction.response.send_message("❌ รูปแบบไม่ถูกต้อง! กรุณากรอกในรูปแบบ `ชื่อไอเทม จำนวน` เช่น `เหล็ก 50` (1 บรรทัดต่อ 1 รายการ)", ephemeral=True)
            return

        conn = get_db_connection()
        cursor = conn.cursor()
        success_logs, not_found_items = [], []

        for item_name, qty in parsed:
            cursor.execute("SELECT amount FROM inventory WHERE item_name = ?", (item_name,))
            row = cursor.fetchone()
            if row is None:
                not_found_items.append(item_name)
            else:
                new_qty = row[0] + qty
                cursor.execute("UPDATE inventory SET amount = ? WHERE item_name = ?", (new_qty, item_name))
                cursor.execute(
                    "INSERT INTO logs (user_name, action, item_name, amount, remaining_amount) VALUES (?, 'ADD', ?, ?, ?)",
                    (interaction.user.display_name, item_name, qty, new_qty)
                )
                success_logs.append(f"• **{item_name}**: +{qty:,} (คงเหลือ: `{new_qty:,}`)")

        conn.commit()
        conn.close()

        msg = []
        if success_logs:
            msg.append(f"📥 **{interaction.user.display_name}** ฝากไอเทมเข้าคลังสำเร็จ `{len(success_logs)}` รายการ:\n" + "\n".join(success_logs))
        if not_found_items:
            msg.append(f"❌ ไม่พบไอเทมในระบบ `{len(not_found_items)}` รายการ (ต้องกดสร้างไอเทมใหม่ก่อน):\n" + ", ".join([f"**{i}**" for i in not_found_items]))

        await interaction.response.send_message("\n\n".join(msg), ephemeral=False)


class MultiRemoveItemModal(Modal, title="📤 ถอน/เบิกไอเทมออกจากคลัง (หลายรายการ)"):
    items_input = TextInput(
        label="พิมพ์ ชื่อไอเทม ตามด้วย จำนวน (แยกบรรทัด)",
        style=discord.TextStyle.paragraph,
        placeholder="เช่น:\nทองแดง 10\nเหล็ก 5\nสปริง 2",
        required=True,
        max_length=1500
    )

    async def on_submit(self, interaction: discord.Interaction):
        parsed = parse_items_input(self.items_input.value)
        if not parsed:
            await interaction.response.send_message("❌ รูปแบบไม่ถูกต้อง! กรุณากรอกในรูปแบบ `ชื่อไอเทม จำนวน` เช่น `เหล็ก 10` (1 บรรทัดต่อ 1 รายการ)", ephemeral=True)
            return

        conn = get_db_connection()
        cursor = conn.cursor()
        success_logs, not_enough_items, not_found_items = [], [], []

        for item_name, qty in parsed:
            cursor.execute("SELECT amount FROM inventory WHERE item_name = ?", (item_name,))
            row = cursor.fetchone()
            if row is None:
                not_found_items.append(item_name)
            elif row[0] < qty:
                not_enough_items.append(f"• **{item_name}**: ต้องการถอน {qty:,} (คงเหลือมีแค่ `{row[0]:,}`)")
            else:
                new_qty = row[0] - qty
                cursor.execute("UPDATE inventory SET amount = ? WHERE item_name = ?", (new_qty, item_name))
                cursor.execute(
                    "INSERT INTO logs (user_name, action, item_name, amount, remaining_amount) VALUES (?, 'REMOVE', ?, ?, ?)",
                    (interaction.user.display_name, item_name, qty, new_qty)
                )
                success_logs.append(f"• **{item_name}**: -{qty:,} (คงเหลือ: `{new_qty:,}`)")

        conn.commit()
        conn.close()

        msg = []
        if success_logs:
            msg.append(f"📤 **{interaction.user.display_name}** เบิกไอเทมออกจากคลังสำเร็จ `{len(success_logs)}` รายการ:\n" + "\n".join(success_logs))
        if not_enough_items:
            msg.append("⚠️ ไอเทมไม่เพียงพอสำหรับการถอน:\n" + "\n".join(not_enough_items))
        if not_found_items:
            msg.append("❌ ไม่พบชื่อไอเทมในคลัง:\n" + ", ".join([f"**{i}**" for i in not_found_items]))

        await interaction.response.send_message("\n\n".join(msg), ephemeral=False)


# --- 4. ปุ่มกดหลัก (Main Control Panel) ---

class MainControlView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="เพิ่มไอเทมเข้าคลัง", style=discord.ButtonStyle.green, custom_id="btn_add_item", emoji="📥")
    async def add_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(MultiAddItemModal())

    @discord.ui.button(label="ถอนไอเทมออกจากคลัง", style=discord.ButtonStyle.red, custom_id="btn_remove_item", emoji="📤")
    async def remove_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(MultiRemoveItemModal())

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
            embed.add_field(name="รายการไอเทมคงเหลือ (1)", value="\n".join(stock_list[:20]), inline=False)
            embed.add_field(name="รายการไอเทมคงเหลือ (2)", value="\n".join(stock_list[20:]), inline=False)
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


# --- 5. คำสั่งเริ่มต้นระบบ ---

@bot.command(name="setup")
async def setup_panel(ctx):
    embed = discord.Embed(
        title="🎒 ระบบจัดการคลังสินค้าส่วนกลาง (Centralized Inventory)",
        description="รองรับการพิมพ์ฝาก-ถอนครั้งละหลายๆ รายการพร้อมกันครับ",
        color=discord.Color.blue()
    )
    embed.add_field(name="📥 เพิ่มไอเทมเข้าคลัง", value="พิมพ์ฝากหลายรายการ เช่น `ทองแดง 50` ขึ้นบรรทัดใหม่", inline=False)
    embed.add_field(name="📤 ถอนไอเทมออกจากคลัง", value="พิมพ์เบิกหลายรายการ เช่น `เหล็ก 10` ขึ้นบรรทัดใหม่", inline=False)
    embed.add_field(name="➕ เพิ่มประเภทไอเทมใหม่", value="สร้างชื่อไอเทมใหม่ลงคลังได้หลายรายการพร้อมกัน", inline=False)
    embed.add_field(name="📦 เช็กสต็อกคลังกลาง", value="ดูรายการไอเทมและยอดรวมคงเหลือทั้งหมด", inline=False)
    embed.add_field(name="📜 ดูประวัติเพิ่ม-ถอน", value="ดูรายการประวัติฝาก/เบิกย้อนหลัง 10 รายการล่าสุด", inline=False)

    await ctx.send(embed=embed, view=MainControlView())


@bot.event
async def on_ready():
    bot.add_view(MainControlView())
    print(f"Logged in as {bot.user}")


bot.run(os.environ.get("DISCORD_TOKEN") or os.environ.get("DISCORD_BOT_TOKEN"))
