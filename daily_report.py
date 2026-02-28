import os
import json
import time
import urllib.parse
from datetime import datetime, timedelta
import pytz
import requests
import pandas as pd
import yfinance as yf
import plotly.express as px
import feedparser
from google.oauth2.service_account import Credentials
import gspread
import google.generativeai as genai

print("啟動【AI 賦能版】法人戰情機器人...")

# 1. 讀取金鑰
LINE_ACCESS_TOKEN = os.getenv('LINE_ACCESS_TOKEN')
LINE_USER_ID = os.getenv('LINE_USER_ID')
gcp_sa_key_json = os.getenv('GCP_SA_KEY')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

# 設定 Google AI
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# 2. 登入 Google Sheets
creds_dict = json.loads(gcp_sa_key_json)
scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
gc = gspread.authorize(creds)

sheet_name = "全市場聲量動能資料庫"
try:
    sh = gc.open(sheet_name)
    worksheet = sh.sheet1
except Exception as e:
    print(f"找不到資料庫: {e}")
    exit()

df_history = pd.DataFrame(worksheet.get_all_records())

# 3. 爬蟲與 AI 輔助函數
def get_news_data(keyword, limit=5):
    query = f'"{keyword}"'
    encoded_keyword = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={encoded_keyword}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    try:
        feed = feedparser.parse(url)
        return {"count": len(feed.entries), "titles": [entry.title for entry in feed.entries[:limit]]}
    except:
        return {"count": 0, "titles": []}

def get_dcard_volume(keyword):
    encoded_keyword = urllib.parse.quote(keyword)
    url = f"https://www.dcard.tw/service/api/v2/search/posts?query={encoded_keyword}&forum=stock&limit=30"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        return len(requests.get(url, headers=headers, timeout=5).json())
    except:
        return 0

# --- 模組四：財報日曆預警功能 ---
def check_upcoming_earnings(ticker_list):
    print("掃描美股財報日曆中...")
    upcoming = []
    today = datetime.now(pytz.timezone('US/Eastern')).date()
    for tk in ticker_list:
        try:
            stock = yf.Ticker(tk)
            dates = stock.get_earnings_dates()
            if dates is not None and not dates.empty:
                next_date = dates.index[0].date()
                delta = (next_date - today).days
                if 0 <= delta <= 7:  # 7天內發布財報
                    upcoming.append(f"{tk} ({next_date.strftime('%m/%d')})")
        except:
            pass
    return upcoming

# 4. 抓取數據
stock_pool = [
    # === [核心 AI 與七巨頭] ===
    {"ticker": "NVDA", "name": "輝達", "market": "US", "keywords": ["NVDA"]},
    {"ticker": "AAPL", "name": "蘋果", "market": "US", "keywords": ["AAPL"]},
    {"ticker": "MSFT", "name": "微軟", "market": "US", "keywords": ["MSFT"]},
    {"ticker": "GOOGL", "name": "Google", "market": "US", "keywords": ["GOOGL"]},
    {"ticker": "META", "name": "Meta", "market": "US", "keywords": ["META"]},
    {"ticker": "AMZN", "name": "亞馬遜", "market": "US", "keywords": ["AMZN"]},
    {"ticker": "TSLA", "name": "特斯拉", "market": "US", "keywords": ["TSLA"]},
    
    # === [關鍵半導體與矽智財] ===
    {"ticker": "TSM", "name": "台積電ADR", "market": "US", "keywords": ["TSM"]},
    {"ticker": "AVGO", "name": "博通", "market": "US", "keywords": ["AVGO"]},
    {"ticker": "AMD", "name": "超微", "market": "US", "keywords": ["AMD"]},
    {"ticker": "ARM", "name": "安謀", "market": "US", "keywords": ["ARM"]},
    
    # === [AI 基礎設施、散熱與能源] ===
    {"ticker": "VRT", "name": "Vertiv", "market": "US", "keywords": ["VRT"]},
    {"ticker": "SMR", "name": "NuScale", "market": "US", "keywords": ["SMR"]},
    {"ticker": "CEG", "name": "Constellation", "market": "US", "keywords": ["CEG"]},
    
    # === [光通訊與矽光子] ===
    {"ticker": "AAOI", "name": "應用光電", "market": "US", "keywords": ["AAOI"]},
    {"ticker": "LITE", "name": "Lumentum", "market": "US", "keywords": ["LITE"]},
    {"ticker": "COHR", "name": "Coherent", "market": "US", "keywords": ["COHR"]},
    
    # === [全球金融與價值型] ===
    {"ticker": "JPM", "name": "摩根大通", "market": "US", "keywords": ["JPM"]},
    {"ticker": "BRK-B", "name": "波克夏", "market": "US", "keywords": ["BRK-B"]},
    
    # === [台股對應關鍵供應鏈] ===
    {"ticker": "2330.TW", "name": "台積電", "market": "TW", "keywords": ["台積電"]},
    {"ticker": "2317.TW", "name": "鴻海", "market": "TW", "keywords": ["鴻海"]},
    {"ticker": "2382.TW", "name": "廣達", "market": "TW", "keywords": ["廣達"]},
    {"ticker": "3231.TW", "name": "緯創", "market": "TW", "keywords": ["緯創"]},
    {"ticker": "3037.TW", "name": "欣興", "market": "TW", "keywords": ["欣興"]},
    {"ticker": "3321.TW", "name": "同泰", "market": "TW", "keywords": ["同泰"]},
    {"ticker": "2308.TW", "name": "台達電", "market": "TW", "keywords": ["台達電"]},
    {"ticker": "3017.TW", "name": "奇鋐", "market": "TW", "keywords": ["奇鋐"]},
    {"ticker": "3324.TW", "name": "雙鴻", "market": "TW", "keywords": ["雙鴻"]}
]

tw_tz = pytz.timezone('Asia/Taipei')
today_str = datetime.now(tw_tz).strftime('%Y-%m-%d')
current_time = datetime.now(tw_tz).strftime('%Y-%m-%d %H:%M:%S')

today_results = []
new_rows_for_db = []
hottest_stock = {"name": "", "hype": 0, "titles": []}
us_tickers_for_earnings = []

for info in stock_pool:
    ticker, name, market, kw = info["ticker"], info["name"], info["market"], info["keywords"][0]
    rate = {"US": 1.0, "TW": 1/31.5}[market]
    if market == "US": us_tickers_for_earnings.append(ticker)
    
    try:
        stock = yf.Ticker(ticker)
        fast_info = stock.fast_info
        current_price = fast_info.last_price
        trading_value_m = round((fast_info.last_volume * current_price * rate) / 1000000, 2)
    except:
        current_price, trading_value_m = 0, 0

    news_info = get_news_data(kw)
    total_hype = max((get_dcard_volume(kw) if market == "TW" else 0) + news_info["count"], 1)
    
    # 紀錄今日最熱門標的，留給 AI 分析
    if total_hype > hottest_stock["hype"] and len(news_info["titles"]) > 0:
        hottest_stock = {"name": name, "hype": total_hype, "titles": news_info["titles"]}

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

# 執行財報預警
earnings_alerts = check_upcoming_earnings(us_tickers_for_earnings)
earnings_msg = f"📅 7日內財報預警：{', '.join(earnings_alerts)}" if earnings_alerts else "📅 7日內無重點巨頭財報。"

# --- 模組一：AI 語意情緒分析 ---
ai_insight_msg = "🤖 AI 分析：今日市場資訊量不足，無特別情緒波動。"
if GEMINI_API_KEY and hottest_stock["hype"] > 0:
    print(f"呼叫 AI 分析今日焦點: {hottest_stock['name']}")
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        titles_text = "\n".join(hottest_stock["titles"])
        prompt = f"你是華爾街頂級證券分析師。請根據以下關於【{hottest_stock['name']}】的最新新聞標題，給出一段50字以內的極簡『市場情緒快評』，並明確標示整體情緒為(偏多/偏空/中立/震盪)：\n{titles_text}"
        response = model.generate_content(prompt)
        ai_insight_msg = f"🤖 AI 晨間快評【焦點：{hottest_stock['name']}】\n{response.text.strip()}"
    except Exception as e:
        print(f"AI 呼叫失敗: {e}")

# 5. 繪圖
df_plot = pd.DataFrame(today_results)
fig = px.scatter(
    df_plot, x="資金動能變化 (%)", y="聲量動能變化 (%)", size="當前總聲量", color="象限洞察",
    text="圖表標籤", title=f"【VIP晨會戰情】動能四象限與AI情緒解析<br>更新時間: {current_time}",
    size_max=60, template="plotly_dark",
    color_discrete_map={"🔥 右上：價量齊揚": "#EF553B", "🤫 右下：低調吸金": "#00CC96",
                        "⚠️ 左上：聲量背離": "#AB63FA", "❄️ 左下：冷門打底": "#636EFA", "🆕 首次建檔": "#808080"}
)
fig.add_hline(y=0, line_dash="solid", line_color="white", opacity=0.3)
fig.add_vline(x=0, line_dash="solid", line_color="white", opacity=0.3)
fig.update_traces(textposition='top center')
fig.update_layout(margin=dict(b=80))
fig.add_annotation(
    text="<b>【象限定義】</b> 🔥 右上：價量齊揚 ｜ 🤫 右下：低調吸金 ｜ ⚠️ 左上：聲量背離 ｜ ❄️ 左下：冷門打底",
    xref="paper", yref="paper", x=0.5, y=-0.18, showarrow=False, font=dict(size=12, color="#A0A0A0"), xanchor="center", yanchor="top"
)

img_path = "radar.jpg"
fig.write_image(img_path, scale=2)

# 6. 上傳圖床
def upload_image(file_path):
    try:
        res = requests.post("https://catbox.moe/user/api.php", data={"reqtype": "fileupload"}, files={"fileToUpload": open(file_path, "rb")}, timeout=15)
        return res.text if res.status_code == 200 else None
    except:
        return None
img_url = upload_image(img_path)

# 7. 發送 LINE
if img_url:
    print("準備發送終極戰情 LINE...")
    smart_money = [row['名稱'] for row in today_results if "低調吸金" in row['象限洞察']]
    money_msg = f"🟢 今日主力悄悄吃貨標的：{', '.join(smart_money)}" if smart_money else "無特別低調吸金標的"
    
    # 將 AI 快評與財報預警組合進 LINE 訊息
    final_text = f"早安！為您送上今日全市場動能雷達。\n\n{money_msg}\n\n{earnings_msg}\n\n{ai_insight_msg}"
    
    payload = {
        "to": LINE_USER_ID,
        "messages": [
            {"type": "text", "text": final_text},
            {"type": "image", "originalContentUrl": img_url, "previewImageUrl": img_url}
        ]
    }
    requests.post("https://api.line.me/v2/bot/message/push", headers={"Content-Type": "application/json", "Authorization": f"Bearer {LINE_ACCESS_TOKEN}"}, json=payload, timeout=10)
    print("LINE 訊息發送完畢！")
