import os
import json
import time
import urllib.parse
from datetime import datetime
import pytz
import requests
import pandas as pd
import yfinance as yf
import plotly.express as px
import feedparser
from google.oauth2.service_account import Credentials
import gspread

print("啟動【全自動化】法人戰情機器人...")

# 1. 讀取 GitHub Secrets 保險箱裡的鑰匙
LINE_ACCESS_TOKEN = os.getenv('LINE_ACCESS_TOKEN')
LINE_USER_ID = os.getenv('LINE_USER_ID')
gcp_sa_key_json = os.getenv('GCP_SA_KEY')

# 2. 登入 Google Sheets 資料庫
creds_dict = json.loads(gcp_sa_key_json)
scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
gc = gspread.authorize(creds)

sheet_name = "全市場聲量動能資料庫"
try:
    sh = gc.open(sheet_name)
    worksheet = sh.sheet1
except Exception as e:
    print(f"找不到資料庫或權限錯誤: {e}")
    exit()

df_history = pd.DataFrame(worksheet.get_all_records())

# 3. 爬蟲函數
def get_dcard_volume(keyword):
    encoded_keyword = urllib.parse.quote(keyword)
    url = f"https://www.dcard.tw/service/api/v2/search/posts?query={encoded_keyword}&forum=stock&limit=30"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        return len(requests.get(url, headers=headers, timeout=5).json())
    except:
        return 0

def get_news_volume(keyword):
    query = f'"{keyword}" (site:money.udn.com OR site:ctee.com.tw)'
    encoded_keyword = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={encoded_keyword}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    try:
        return len(feedparser.parse(url).entries) 
    except:
        return 0

# 4. 抓取最新數據並比對歷史
stock_pool = [
    {"ticker": "NVDA", "name": "輝達", "market": "US", "keywords": ["NVDA"]},
    {"ticker": "TSLA", "name": "特斯拉", "market": "US", "keywords": ["TSLA"]},
    {"ticker": "VRT", "name": "Vertiv", "market": "US", "keywords": ["VRT"]},
    {"ticker": "2330.TW", "name": "台積電", "market": "TW", "keywords": ["台積電"]},
    {"ticker": "2317.TW", "name": "鴻海", "market": "TW", "keywords": ["鴻海"]},
    {"ticker": "3037.TW", "name": "欣興", "market": "TW", "keywords": ["欣興"]},
    {"ticker": "7203.T", "name": "豐田", "market": "JP", "keywords": ["豐田"]}
]

tw_tz = pytz.timezone('Asia/Taipei')
today_str = datetime.now(tw_tz).strftime('%Y-%m-%d')
current_time = datetime.now(tw_tz).strftime('%Y-%m-%d %H:%M:%S')

today_results = []
new_rows_for_db = []

for info in stock_pool:
    ticker, name, market, kw = info["ticker"], info["name"], info["market"], info["keywords"][0]
    rate = {"US": 1.0, "TW": 1/31.5, "JP": 1/150.0}[market]
    
    try:
        stock = yf.Ticker(ticker)
        fast_info = stock.fast_info
        current_price = fast_info.last_price
        trading_value_m = round((fast_info.last_volume * current_price * rate) / 1000000, 2)
    except:
        current_price, trading_value_m = 0, 0

    total_hype = max((get_dcard_volume(kw) if market == "TW" else 0) + get_news_volume(kw), 1)
    new_rows_for_db.append([today_str, ticker, name, market, current_price, trading_value_m, total_hype])

    money_mom, hype_mom = 0, 0
    insight, emoji = "🆕 首次建檔", "⚪"

    if not df_history.empty:
        past_records = df_history[(df_history['代號'] == ticker) & (df_history['日期'] != today_str)]
        if not past_records.empty:
            last_record = past_records.iloc[-1]
            past_val = last_record['成交金額_百萬美元']
            past_hype = max(last_record['總聲量'], 1)
            
            if past_val > 0: money_mom = ((trading_value_m - past_val) / past_val) * 100
            hype_mom = ((total_hype - past_hype) / past_hype) * 100

            if money_mom > 0 and hype_mom > 0: insight, emoji = "🔥 右上：價量齊揚", "🔥"
            elif money_mom > 0 and hype_mom <= 0: insight, emoji = "🤫 右下：低調吸金", "🤫"
            elif money_mom <= 0 and hype_mom > 0: insight, emoji = "⚠️ 左上：聲量背離", "⚠️"
            else: insight, emoji = "❄️ 左下：冷門打底", "❄️"

    today_results.append({
        "圖表標籤": f"{emoji} {name}", "名稱": name,
        "資金動能變化 (%)": round(money_mom, 2), "聲量動能變化 (%)": round(hype_mom, 2),
        "當前總聲量": total_hype, "象限洞察": insight
    })

worksheet.append_rows(new_rows_for_db)

# 5. 繪製並匯出圖表
df_plot = pd.DataFrame(today_results)
fig = px.scatter(
    df_plot, x="資金動能變化 (%)", y="聲量動能變化 (%)", size="當前總聲量", color="象限洞察",
    text="圖表標籤", title=f"【VIP晨會戰情】動能四象限圖<br>更新時間: {current_time}",
    size_max=60, template="plotly_dark",
    color_discrete_map={"🔥 右上：價量齊揚": "#EF553B", "🤫 右下：低調吸金": "#00CC96",
                        "⚠️ 左上：聲量背離": "#AB63FA", "❄️ 左下：冷門打底": "#636EFA", "🆕 首次建檔": "#808080"}
)
fig.add_hline(y=0, line_dash="solid", line_color="white", opacity=0.3)
fig.add_vline(x=0, line_dash="solid", line_color="white", opacity=0.3)
fig.update_traces(textposition='top center')

img_path = "radar.jpg"
fig.write_image(img_path, scale=2)
print("圖表已生成，準備上傳圖床...")

# 6. 上傳圖片至免費圖床取得公開網址 (加入備援機制與超時保護)
def upload_image(file_path):
    # 方案 A: 嘗試使用 Catbox (設定 15 秒超時)
    try:
        print("正在嘗試上傳至 Catbox...")
        url = "https://catbox.moe/user/api.php"
        data = {"reqtype": "fileupload"}
        with open(file_path, "rb") as f:
            res = requests.post(url, data=data, files={"fileToUpload": f}, timeout=15)
        if res.status_code == 200:
            return res.text
    except Exception as e:
        print(f"⚠️ Catbox 上傳超時或失敗，啟動備用圖床...")

    # 方案 B: 嘗試使用 Freeimage.host 備用圖床
    try:
        print("正在嘗試上傳至 Freeimage.host...")
        import base64
        with open(file_path, "rb") as f:
            img_data = base64.b64encode(f.read()).decode('utf-8')
        
        api_url = "https://freeimage.host/api/1/upload"
        payload = {
            "key": "6d207e02198a847aa98d0a2a901485a5", 
            "action": "upload", 
            "source": img_data, 
            "format": "json"
        }
        res = requests.post(api_url, data=payload, timeout=15)
        if res.status_code == 200:
            return res.json()['image']['url']
    except Exception as e:
        print(f"❌ 備用圖床也失敗: {e}")
        
    return None

img_url = upload_image(img_path)

# 7. 透過 LINE Messaging API 發送給自己
if img_url:
    print(f"✅ 圖片上傳成功: {img_url}")
    line_api = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_ACCESS_TOKEN}"}
    
    smart_money = [row['名稱'] for row in today_results if "低調吸金" in row['象限洞察']]
    alert_msg = f"🟢 今日主力悄悄吃貨標的：{', '.join(smart_money)}" if smart_money else "無特別低調吸金標的"
    
    payload = {
        "to": LINE_USER_ID,
        "messages": [
            {"type": "text", "text": f"早安！這是今天的全市場動能與情緒雷達圖。\n\n{alert_msg}"},
            {"type": "image", "originalContentUrl": img_url, "previewImageUrl": img_url}
        ]
    }
    try:
        res = requests.post(line_api, headers=headers, json=payload, timeout=10)
        print("LINE 發送狀態:", res.status_code, res.text)
    except Exception as e:
        print(f"發送 LINE 失敗: {e}")
else:
    print("圖片上傳失敗，無法發送 LINE。請稍後再試。")
