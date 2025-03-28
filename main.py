import asyncio
import threading
import websockets
import json
import gspread
import requests
import nest_asyncio
from oauth2client.service_account import ServiceAccountCredentials
from flask import Flask

# Khởi tạo Flask app
app = Flask(__name__)

# Biến lưu logs
log_data = []

# Thông tin bot Telegram
TELEGRAM_BOT_TOKEN = "1864590582:AAGSZFmEJzVkIHIThBsYk53iNatz5ChbLBk"
TELEGRAM_CHAT_ID = "-1002606173012"

def send_telegram_message(user_address, message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    reply_markup = json.dumps({
        "inline_keyboard": [[
            {"text": "Xem trên HypurrScan", "url": f"https://hypurrscan.io/address/{user_address}"}
        ]]
    })
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML", "reply_markup": reply_markup}
    requests.post(url, json=payload)

# Kết nối Google Sheets
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
client = gspread.authorize(creds)
sheet = client.open_by_url("https://docs.google.com/spreadsheets/d/1-TMLLSpJdyeciON-wx8kRRcabBZaqXd3nsc0iRuGUAo/edit").sheet1

async def check_positions(user_address):
    url = "wss://api.hyperliquid.xyz/ws"
    try:
        async with websockets.connect(url, ping_interval=30) as websocket:
            subscribe_message = {"method": "subscribe", "subscription": {"type": "webData2", "user": user_address}}
            await websocket.send(json.dumps(subscribe_message))
            
            while True:
                response = await websocket.recv()
                data = json.loads(response)

                if "channel" in data and data["channel"] == "subscriptionResponse":
                    continue

                current_positions = {}
                if "data" in data and "clearinghouseState" in data["data"]:
                    asset_positions = data["data"]["clearinghouseState"].get("assetPositions", [])
                    for asset in asset_positions:
                        position = asset.get("position", {})
                        if position:
                            coin = position.get("coin")
                            size = float(position.get("szi", 0))
                            position_type = "LONG" if size > 0 else "SHORT"
                            current_positions[coin] = position_type
                
                try:
                    cell = sheet.find(user_address)
                    row_data = sheet.row_values(cell.row)
                    old_coins = row_data[1].split(",") if len(row_data) > 1 else []
                    old_positions = row_data[2].split(",") if len(row_data) > 2 else []
                except:
                    old_coins, old_positions = [], []
                
                new_coins = list(current_positions.keys())
                new_positions = list(current_positions.values())
                
                opened_positions = [coin for coin in new_coins if coin not in old_coins]
                closed_positions = [(coin, old_positions[old_coins.index(coin)]) for coin in old_coins if coin not in new_coins]
                
                if old_coins == new_coins and old_positions == new_positions:
                    log_message = f"🔇 Không có thay đổi vị thế cho {user_address}."
                    print(log_message)
                    log_data.append(log_message)
                    return
                
                if old_coins != new_coins or old_positions != new_positions:
                    message = f"📌 <b>Thay đổi vị thế ({user_address})</b>\n-----------------------------\n"
                    for coin, position in current_positions.items():
                        symbol = "🔹" if position == "LONG" else "🔻"
                        status = "(🟢 Mở mới)" if coin in opened_positions else ""
                        message += f"{symbol} <b>{coin}USDT</b> {symbol} {status}\n   - Pos: {position}\n-----------------------------\n"
                    
                    for coin, old_position in closed_positions:
                        message += f"❌ <b>{coin}USDT</b> ({old_position}) đã đóng vị thế\n-----------------------------\n"
                    
                    send_telegram_message(user_address, message)

                    # Lưu log
                    log_data.append(message.replace("<b>", "").replace("</b>", ""))
                    
                    sheet.update(range_name=f"B{cell.row}:C{cell.row}", values=[[",".join(new_coins), ",".join(new_positions)]])
                
                await websocket.close()
                return
    except Exception as e:
        log_message = f"🚨 Lỗi với {user_address}: {e}"
        print(log_message)
        log_data.append(log_message)

async def main():
    while True:
        user_data = sheet.get_all_records()
        user_addresses = [user["User_address"] for user in user_data]
        
        for user_address in user_addresses:
            log_message = f"🔍 Kiểm tra vị thế: {user_address}"
            print(log_message)
            log_data.append(log_message)
            await check_positions(user_address)
            await asyncio.sleep(5)  
        
        log_message = "🔄 Hoàn thành vòng kiểm tra, bắt đầu lại sau 10 giây..."
        print(log_message)
        log_data.append(log_message)
        await asyncio.sleep(10)

# Route chính hiển thị logs
@app.route("/")
def home():
    return "<h2>Bot Logs</h2>" + "<br>".join(log_data[-50:])  # Chỉ hiển thị 50 logs gần nhất

# Chạy Flask trong một luồng riêng
def run_flask():
    app.run(host="0.0.0.0", port=10000)

if __name__ == "__main__":
    nest_asyncio.apply()
    
    # Chạy Flask server trong luồng riêng
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # Chạy bot Telegram
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main())
