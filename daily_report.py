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
import plotly.graph_objects as go
import feedparser
from google.oauth2.service_account import Credentials
import gspread
import google.generativeai as genai
import praw

print("啟動【跨國巨頭 38 檔：AI 賦能 + Reddit 雙引擎版】法人戰情機器人...")

# 1. 讀取金鑰
LINE_ACCESS_TOKEN = os.getenv('LINE_ACCESS_TOKEN')
LINE_USER_ID = os.getenv('LINE_USER_ID')
gcp_sa_key_json = os.getenv('GCP_SA_KEY')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
REDDIT_CLIENT_ID = os.getenv('REDDIT_CLIENT_ID')
REDDIT_CLIENT_SECRET = os.getenv('REDDIT_CLIENT_SECRET')

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# 初始化 Reddit API
reddit = None
if REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET:
    try:
        reddit = praw.Reddit(
            client_id=REDDIT_CLIENT_ID,
            client_secret=REDDIT_CLIENT_SECRET,
            user_agent="python:market-radar-bot:v1.0 (by /u/investor)"
        )
    except Exception as e:
        print(f"Reddit 初始化失敗: {e}")

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

# 3. 爬蟲函數群
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

def get_reddit_volume(keyword):
    if not reddit: return 0
    try:
        subreddits = reddit.subreddit("wallstreetbets+stocks+investing")
        search_results = subreddits.search(keyword, sort='new', time_filter='day', limit=30)
        return len(list(search_results))
    except Exception as e:
        return 0

def check_upcoming_earnings(ticker_list):
    upcoming = []
    today = datetime.now(pytz.timezone('US/Eastern')).date()
    for tk in ticker_list:
        try:
            stock = yf.Ticker(tk)
            dates = stock.get_earnings_dates()
            if dates is not None and not dates.empty:
                next_date = dates.index[0].date()
                delta = (next_date - today).days
                if 0 <= delta <= 7:
                    upcoming.append(f"{tk} ({next_date.strftime('%m/%d')})")
        except:
            pass
    return upcoming

# ==========================================
# 4. 抓取數據 (38檔 跨洲際法人名單)
# ==========================================
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
    {"ticker": "MU", "name": "美光", "market": "US", "keywords": ["MU"]},
    
    # === [AI 基礎設施、散熱與能源] ===
    {"ticker": "VRT", "name": "Vertiv", "market": "US", "keywords": ["VRT"]},
    {"ticker": "SMR", "name": "NuScale", "market": "US", "keywords": ["SMR"]},
    {"ticker": "CEG", "name": "Constellation", "market": "US", "keywords": ["CEG"]},
    
    # === [光通訊與矽光子] ===
    {"ticker": "AAOI", "name": "應用光電", "market": "US", "keywords": ["AAOI"]},
    {"ticker": "LITE", "name": "Lumentum", "market": "US", "keywords": ["LITE"]},
    {"ticker": "COHR", "name": "Coherent", "market": "US", "keywords": ["COHR"]},
    
    # === [全球金融與加密資產] ===
    {"ticker": "JPM", "name": "摩根大通", "market": "US", "keywords": ["JPM"]},
    {"ticker": "BRK-B", "name": "波克夏", "market": "US", "keywords": ["BRK-B"]},
    {"ticker": "COIN", "name": "Coinbase", "market": "US", "keywords": ["COIN"]},
    
    # === [台股對應關鍵供應鏈] ===
    {"ticker": "2330.TW", "name": "台積電", "market": "TW", "keywords": ["台積電"]},
    {"ticker": "2317.TW", "name": "鴻海", "market": "TW", "keywords": ["鴻海"]},
    {"ticker": "2382.TW", "name": "廣達", "market": "TW", "keywords": ["廣達"]},
    {"ticker": "3231.TW", "name": "緯創", "market": "TW", "keywords": ["緯創"]},
    {"ticker": "3037.TW", "name": "欣興", "market": "TW", "keywords": ["欣興"]},
    {"ticker": "2308.TW", "name": "台達電", "market": "TW", "keywords": ["台達電"]},
    {"ticker": "3017.TW", "name": "奇鋐", "market": "TW", "keywords": ["奇鋐"]},
    {"ticker": "8213.TW", "name": "志超", "market": "TW", "keywords": ["志超"]},
    {"ticker": "2383.TW", "name": "台光電", "market": "TW", "keywords": ["台光電"]},
    {"ticker": "2408.TW", "name": "南亞科", "market": "TW", "keywords": ["南亞科"]},
    {"ticker": "6223.TW", "name": "旺矽", "market": "TW", "keywords": ["旺矽"]},
    {"ticker": "6446.TW", "name": "藥華藥", "market": "TW", "keywords": ["藥華藥"]},
    
    # === [日韓亞洲重點指標股] ===
    {"ticker": "005930.KS", "name": "三星電子", "market": "KR", "keywords": ["三星", "005930"]},
    {"ticker": "5801.T", "name": "古河電工", "market": "JP", "keywords": ["古河電工", "5801"]},
    {"ticker": "5016.T", "name": "JX金屬", "market": "JP", "keywords": ["JX金屬", "5016"]},
    {"ticker": "3110.T", "name": "日東紡", "market": "JP", "keywords": ["日東紡", "3110"]},
    {"ticker": "6590.T", "name": "芝浦機電", "market": "JP", "keywords": ["芝浦", "6590"]}
]

tw_tz = pytz.timezone('Asia/Taipei')
today_str = datetime.now(tw_tz).strftime('%Y-%m-%d')
current_time = datetime.now(tw_tz).strftime('%Y-%m-%d %H:%M:%S')

# 💡 匯率轉換矩陣 (加入日圓與韓元換算美元基準)
exchange_rates = {"US": 1.0, "TW": 1/32.0, "JP": 1/150.0, "KR": 1/1350.0}

today_results = []
new_rows_for_db = []
hottest_stock = {"name": "", "hype": 0, "titles": []}
us_tickers_for_earnings = []

for info in stock_pool:
    ticker, name, market, kw = info["ticker"], info["name"], info["market"], info["keywords"][0]
    rate = exchange_rates.get(market, 1.0)
    if market == "US": us_tickers_for_earnings.append(ticker)
    
    try:
        stock = yf.Ticker(ticker)
        fast_info = stock.fast_info
        current_price = fast_info.last_price
        # 將成交金額統一轉換為百萬美元 (USD Millions)
        trading_value_m = round((fast_info.last_volume * current_price * rate) / 1000000, 2)
        
        yf_news = stock.news
        yf_titles = [n['title'] for n in yf_news[:5]] if yf_news else []
        yf_count = len(yf_news) if yf_news else 0
    except:
        current_price, trading_value_m = 0, 0
        yf_titles, yf_count = [], 0

    news_info = get_news_data(kw)
    combined_titles = yf_titles + news_info["titles"]
    combined_count = yf_count + news_info["count"]
    
    # 💡 聲量分流引擎
    if market == "TW":
        forum_count = get_dcard_volume(kw)
    elif market == "US":
        forum_count = get_reddit_volume(kw)
    else:
        # 日韓股主要依賴 Yahoo 新聞與 Google News，避免抓到無關論壇資訊
        forum_count = 0 

    total_hype = max(forum_count + combined_count, 1)
    
    if total_hype > hottest_stock["hype"] and len(combined_titles) > 0:
        hottest_stock = {"name": name, "hype": total_hype, "titles": combined_titles[:5]}

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

earnings_alerts = check_upcoming_earnings(us_tickers_for_earnings)
earnings_msg = f"📅 7日內財報預警：{', '.join(earnings_alerts)}" if earnings_alerts else "📅 7日內無重點美股財報。"

ai_insight_msg = "🤖 AI 分析：今日市場資訊量不足，無特別情緒波動。"
if GEMINI_API_KEY and hottest_stock["hype"] > 0 and len(hottest_stock["titles"]) > 0:
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        titles_text = "\n".join(hottest_stock["titles"])
        prompt = f"你是華爾街頂級證券分析師。請根據以下關於【{hottest_stock['name']}】的最新新聞標題，給出一段50字以內的極簡『市場情緒快評』，並標示整體情緒為(偏多/偏空/中立/震盪)：\n{titles_text}"
        response = model.generate_content(prompt)
        ai_insight_msg = f"🤖 AI 晨間快評【焦點：{hottest_stock['name']}】\n{response.text.strip()}"
    except Exception as e:
        pass

# ==========================================
# 5. 繪製 Page 1: 動能雷達圖 
# ==========================================
df_plot = pd.DataFrame(today_results)
q_lists = {"🔥 右上：價量齊揚": [], "🤫 右下：低調吸金": [], "⚠️ 左上：聲量背離": [], "❄️ 左下：冷門打底": [], "🆕 首次建檔": []}
for row in today_results: q_lists[row["象限洞察"]].append(row["名稱"])

def wrap_list(stock_list, n=8):
    chunks = [stock_list[i:i + n] for i in range(0, len(stock_list), n)]
    return '<br>　　　　　'.join([', '.join(c) for c in chunks])

list_text = "<br><br><b>【各象限標的清單】</b><br>"
if q_lists["🔥 右上：價量齊揚"]: list_text += f"🔥 價量齊揚：{wrap_list(q_lists['🔥 右上：價量齊揚'])}<br>"
if q_lists["🤫 右下：低調吸金"]: list_text += f"🤫 低調吸金：{wrap_list(q_lists['🤫 右下：低調吸金'])}<br>"
if q_lists["⚠️ 左上：聲量背離"]: list_text += f"⚠️ 聲量背離：{wrap_list(q_lists['⚠️ 左上：聲量背離'])}<br>"
if q_lists["❄️ 左下：冷門打底"]: list_text += f"❄️ 冷門打底：{wrap_list(q_lists['❄️ 左下：冷門打底'])}<br>"
if q_lists["🆕 首次建檔"]: list_text += f"🆕 首次建檔：{wrap_list(q_lists['🆕 首次建檔'])}"

fig1 = px.scatter(
    df_plot, x="資金動能變化 (%)", y="聲量動能變化 (%)", size="當前總聲量", color="象限洞察",
    text="圖表標籤", title=f"【Page 1】動能四象限與AI情緒解析<br>更新時間: {current_time}",
    size_max=60, template="plotly_dark",
    color_discrete_map={"🔥 右上：價量齊揚": "#EF553B", "🤫 右下：低調吸金": "#00CC96",
                        "⚠️ 左上：聲量背離": "#AB63FA", "❄️ 左下：冷門打底": "#636EFA", "🆕 首次建檔": "#808080"}
)
fig1.add_hline(y=0, line_dash="solid", line_color="white", opacity=0.3)
fig1.add_vline(x=0, line_dash="solid", line_color="white", opacity=0.3)
fig1.update_traces(textposition='top center', cliponaxis=False)

x_min, x_max = df_plot["資金動能變化 (%)"].min(), df_plot["資金動能變化 (%)"].max()
y_min, y_max = df_plot["聲量動能變化 (%)"].min(), df_plot["聲量動能變化 (%)"].max()
if x_min == x_max: x_min, x_max = -10, 10
if y_min == y_max: y_min, y_max = -10, 10
x_pad = abs(x_max - x_min) * 0.2 + 5
y_pad = abs(y_max - y_min) * 0.2 + 5
fig1.update_xaxes(range=[x_min - x_pad, x_max + x_pad])
fig1.update_yaxes(range=[y_min - y_pad, y_max + y_pad])

# 💡 畫布再擴大為 1200x1050，確保 38 檔名單絕對裝得下
fig1.update_layout(
    width=1200, 
    height=1050, 
    margin=dict(t=120, b=400, l=80, r=150)
)

footer_text = "<b>【象限定義】</b> 🔥 右上：價量齊揚 ｜ 🤫 右下：低調吸金 ｜ ⚠️ 左上：聲量背離 ｜ ❄️ 左下：冷門打底" + list_text
fig1.add_annotation(
    text=footer_text, xref="paper", yref="paper", 
    x=0, y=-0.35, 
    showarrow=False, font=dict(size=14, color="#A0A0A0"), 
    xanchor="left", yanchor="top", align="left"
)

img_path_1 = "radar_page1.jpg"
fig1.write_image(img_path_1, scale=2)

# ==========================================
# 6. 繪製 Page 2: 五日動能軌跡表 
# ==========================================
print("正在計算五日歷史軌跡...")
columns = ["日期", "代號", "名稱", "市場", "收盤價", "成交金額_百萬美元", "總聲量"]
df_today = pd.DataFrame(new_rows_for_db, columns=columns)
df_all = pd.concat([df_history, df_today], ignore_index=True)
df_all['日期'] = pd.to_datetime(df_all['日期'])
df_all = df_all.sort_values(by=['代號', '日期'])

table_data = []
for info in stock_pool:
    tk = info["ticker"]
    name = info["name"]
    df_sub = df_all[df_all['代號'] == tk].tail(6)
    
    quadrants = ["⚪", "⚪", "⚪", "⚪", "⚪"]
    
    if len(df_sub) >= 2:
        vals = df_sub['成交金額_百萬美元'].values
        hypes = df_sub['總聲量'].values
        for i in range(1, len(df_sub)):
            money_mom = ((vals[i] - vals[i-1]) / vals[i-1] * 100) if vals[i-1] > 0 else 0
            hype_mom = ((hypes[i] - hypes[i-1]) / hypes[i-1] * 100) if hypes[i-1] > 0 else 0
            
            q = "⚪"
            if money_mom > 0 and hype_mom > 0: q = "🔥"
            elif money_mom > 0 and hype_mom <= 0: q = "🤫"
            elif money_mom <= 0 and hype_mom > 0: q = "⚠️"
            else: q = "❄️"
            
            target_idx = 5 - (len(df_sub) - i)
            if 0 <= target_idx < 5:
                quadrants[target_idx] = q
                
    table_data.append([name] + quadrants)

headers = ['<b>標的名稱</b>', '<b>T-4 (天前)</b>', '<b>T-3 (天前)</b>', '<b>T-2 (前天)</b>', '<b>T-1 (昨天)</b>', '<b>Today (今日)</b>']
fig2 = go.Figure(data=[go.Table(
    columnwidth=[120, 80, 80, 80, 80, 80],
    header=dict(values=headers, fill_color='#2c2c2c', font=dict(color='white', size=14), align='center', height=40),
    cells=dict(values=list(zip(*table_data)), fill_color='#1e1e1e', font=dict(color='white', size=18), align='center', height=35)
)])

# 動態高度：確保 38 檔股票能一表看完
dynamic_height = 150 + len(stock_pool) * 40
fig2.update_layout(title="【Page 2】五日資金動能演變軌跡表", template="plotly_dark", margin=dict(l=20, r=20, t=60, b=20), height=dynamic_height)

img_path_2 = "trend_page2.jpg"
fig2.write_image(img_path_2, scale=2)

# ==========================================
# 7. 上傳圖床並發送 LINE 訊息
# ==========================================
def upload_image(file_path):
    try:
        res = requests.post("https://catbox.moe/user/api.php", data={"reqtype": "fileupload"}, files={"fileToUpload": open(file_path, "rb")}, timeout=15)
        if res.status_code == 200: return res.text
    except:
        pass
    
    try:
        import base64
        with open(file_path, "rb") as f:
            img_data = base64.b64encode(f.read()).decode('utf-8')
        res = requests.post("https://freeimage.host/api/1/upload", data={"key": "6d207e02198a847aa98d0a2a901485a5", "action": "upload", "source": img_data, "format": "json"}, timeout=15)
        if res.status_code == 200: return res.json()['image']['url']
    except:
        return None

print("正在上傳 Page 1...")
img_url_1 = upload_image(img_path_1)
print("正在上傳 Page 2...")
img_url_2 = upload_image(img_path_2)

if img_url_1 or img_url_2:
    print("準備發送終極戰情 LINE...")
    smart_money = [row['名稱'] for row in today_results if "低調吸金" in row['象限洞察']]
    money_msg = f"🟢 今日主力悄悄吃貨標的：{', '.join(smart_money)}" if smart_money else "無特別低調吸金標的"
    final_text = f"早安！為您送上今日全市場動能雷達。\n\n{money_msg}\n\n{earnings_msg}\n\n{ai_insight_msg}"
    
    messages = [{"type": "text", "text": final_text}]
    if img_url_1: messages.append({"type": "image", "originalContentUrl": img_url_1, "previewImageUrl": img_url_1})
    if img_url_2: messages.append({"type": "image", "originalContentUrl": img_url_2, "previewImageUrl": img_url_2})
    
    payload = {"to": LINE_USER_ID, "messages": messages}
    requests.post("https://api.line.me/v2/bot/message/push", headers={"Content-Type": "application/json", "Authorization": f"Bearer {LINE_ACCESS_TOKEN}"}, json=payload, timeout=10)
    print("✅ LINE 雙圖表訊息發送完畢！")
else:
    print("❌ 圖片上傳失敗，無法發送 LINE。")
