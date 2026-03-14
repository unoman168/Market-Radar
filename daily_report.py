import os
import json
import time
import urllib.parse
from datetime import datetime, timedelta
import pytz
import requests
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
import feedparser
from google.oauth2.service_account import Credentials
import gspread
from google import genai
import praw
import platform
import subprocess
from scipy.interpolate import splprep, splev

print("啟動【跨國巨頭 38 檔：完美蜂巢 & 暴力K線防禦版】法人戰情機器人...")

# ==========================================
# 1. 系統級安裝中文字型 (防禦亂碼方塊)
# ==========================================
if platform.system() == "Linux":
    print("正在為 GitHub 虛擬主機安裝 Linux 系統原生中文字型 (fonts-noto-cjk)...")
    subprocess.run(["sudo", "apt-get", "update"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["sudo", "apt-get", "install", "-y", "fonts-noto-cjk"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("✅ 系統中文字型包安裝完畢！")

# ==========================================
# 2. 讀取金鑰與初始化
# ==========================================
LINE_ACCESS_TOKEN = os.getenv('LINE_ACCESS_TOKEN')
LINE_USER_ID = os.getenv('LINE_USER_ID')
gcp_sa_key_json = os.getenv('GCP_SA_KEY')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
REDDIT_CLIENT_ID = os.getenv('REDDIT_CLIENT_ID')
REDDIT_CLIENT_SECRET = os.getenv('REDDIT_CLIENT_SECRET')

reddit = None
if REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET:
    try: reddit = praw.Reddit(client_id=REDDIT_CLIENT_ID, client_secret=REDDIT_CLIENT_SECRET, user_agent="market-bot")
    except: pass

creds_dict = json.loads(gcp_sa_key_json)
scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
gc = gspread.authorize(creds)

try:
    sh = gc.open("全市場聲量動能資料庫")
    worksheet = sh.sheet1
except Exception as e:
    print(f"找不到資料庫: {e}")
    exit()

df_history = pd.DataFrame(worksheet.get_all_records())

# ==========================================
# 3. 爬蟲函數群
# ==========================================
def get_news_data(keyword, limit=5):
    encoded = urllib.parse.quote(f'"{keyword}"')
    url = f"https://news.google.com/rss/search?q={encoded}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    try:
        feed = feedparser.parse(url)
        titles = [f"《{e.source.title if hasattr(e, 'source') else '新聞'}》{e.title}" for e in feed.entries[:limit]]
        return {"count": len(feed.entries), "titles": titles}
    except: return {"count": 0, "titles": []}

def get_dcard_volume(keyword):
    try: return len(requests.get(f"https://www.dcard.tw/service/api/v2/search/posts?query={urllib.parse.quote(keyword)}&forum=stock&limit=30", headers={"User-Agent": "Mozilla/5.0"}, timeout=5).json())
    except: return 0

def get_reddit_volume(keyword):
    if not reddit: return 0
    try: return len(list(reddit.subreddit("wallstreetbets+stocks+investing").search(keyword, sort='new', time_filter='day', limit=30)))
    except: return 0

def check_upcoming_earnings(ticker_list):
    upcoming = []
    today = datetime.now(pytz.timezone('US/Eastern')).date()
    for tk in ticker_list:
        try:
            dates = yf.Ticker(tk).get_earnings_dates()
            if dates is not None and not dates.empty:
                next_date = dates.index[0].date()
                if 0 <= (next_date - today).days <= 7: upcoming.append(f"{tk} ({next_date.strftime('%m/%d')})")
        except: pass
    return upcoming

# ==========================================
# 4. 抓取數據與暴力 K 線過濾 
# ==========================================
stock_pool = [
    {"ticker": "NVDA", "name": "輝達", "market": "US", "keywords": ["NVDA"]},
    {"ticker": "AAPL", "name": "蘋果", "market": "US", "keywords": ["AAPL"]},
    {"ticker": "MSFT", "name": "微軟", "market": "US", "keywords": ["MSFT"]},
    {"ticker": "GOOGL", "name": "Google", "market": "US", "keywords": ["GOOGL"]},
    {"ticker": "META", "name": "Meta", "market": "US", "keywords": ["META"]},
    {"ticker": "AMZN", "name": "亞馬遜", "market": "US", "keywords": ["AMZN"]},
    {"ticker": "TSLA", "name": "特斯拉", "market": "US", "keywords": ["TSLA"]},
    {"ticker": "TSM", "name": "台積電ADR", "market": "US", "keywords": ["TSM"]},
    {"ticker": "AVGO", "name": "博通", "market": "US", "keywords": ["AVGO"]},
    {"ticker": "AMD", "name": "超微", "market": "US", "keywords": ["AMD"]},
    {"ticker": "ARM", "name": "安謀", "market": "US", "keywords": ["ARM"]},
    {"ticker": "MU", "name": "美光", "market": "US", "keywords": ["MU"]},
    {"ticker": "VRT", "name": "Vertiv", "market": "US", "keywords": ["VRT"]},
    {"ticker": "SMR", "name": "NuScale", "market": "US", "keywords": ["SMR"]},
    {"ticker": "CEG", "name": "Constellation", "market": "US", "keywords": ["CEG"]},
    {"ticker": "AAOI", "name": "應用光電", "market": "US", "keywords": ["AAOI"]},
    {"ticker": "LITE", "name": "Lumentum", "market": "US", "keywords": ["LITE"]},
    {"ticker": "COHR", "name": "Coherent", "market": "US", "keywords": ["COHR"]},
    {"ticker": "JPM", "name": "摩根大通", "market": "US", "keywords": ["JPM"]},
    {"ticker": "BRK-B", "name": "波克夏", "market": "US", "keywords": ["BRK-B"]},
    {"ticker": "COIN", "name": "Coinbase", "market": "US", "keywords": ["COIN"]},
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
    {"ticker": "005930.KS", "name": "三星電子", "market": "KR", "keywords": ["三星", "005930"]},
    {"ticker": "5801.T", "name": "古河電工", "market": "JP", "keywords": ["古河電工", "5801"]},
    {"ticker": "5016.T", "name": "JX金屬", "market": "JP", "keywords": ["JX金屬", "5016"]},
    {"ticker": "3110.T", "name": "日東紡", "market": "JP", "keywords": ["日東紡", "3110"]},
    {"ticker": "6590.T", "name": "芝浦機電", "market": "JP", "keywords": ["芝浦", "6590"]}
]

tw_tz = pytz.timezone('Asia/Taipei')
today_str = datetime.now(tw_tz).strftime('%Y-%m-%d')
current_time = datetime.now(tw_tz).strftime('%Y-%m-%d %H:%M:%S')
exchange_rates = {"US": 1.0, "TW": 1/32.0, "JP": 1/150.0, "KR": 1/1350.0}

today_results = []
new_rows_for_db = []
hottest_stock = {"name": "", "hype": 0, "titles": []}
us_tickers_for_earnings = []
stock_real_price_history = {}

for info in stock_pool:
    ticker, name, market, kw = info["ticker"], info["name"], info["market"], info["keywords"][0]
    rate = exchange_rates.get(market, 1.0)
    
    yf_ticker = ticker
    if ticker in ["6223.TW", "6446.TW"]:
        yf_ticker = ticker.replace(".TW", ".TWO")
        
    if market == "US": us_tickers_for_earnings.append(yf_ticker)
    
    current_price, trading_value_m = 0.0, 0.0
    yf_titles, yf_count = [], 0
    stock_real_price_history[ticker] = [0.0] * 5
    
    try:
        stock = yf.Ticker(yf_ticker)
        hist = stock.history(period="15d") 
        if not hist.empty and 'Close' in hist.columns:
            df_valid = hist.dropna(subset=['Close', 'Volume'])
            if not df_valid.empty:
                closes = df_valid['Close'].tolist()
                vols = df_valid['Volume'].tolist()
                
                current_price = float(closes[-1])
                current_vol = float(vols[-1])
                trading_value_m = round((current_vol * current_price * rate) / 1000000, 2)
                
                if len(closes) >= 2:
                    pcts = [((closes[i] - closes[i-1]) / closes[i-1]) * 100 for i in range(1, len(closes))]
                    last_5 = pcts[-5:]
                    while len(last_5) < 5: last_5.insert(0, 0.0)
                    stock_real_price_history[ticker] = last_5
                    
        yf_news = stock.news
        yf_titles = [f"《{n.get('publisher', 'Yahoo財經')}》{n['title']}" for n in yf_news[:5]] if yf_news else []
        yf_count = len(yf_news) if yf_news else 0
    except Exception as e:
        pass

    news_info = get_news_data(kw)
    combined_titles = yf_titles + news_info["titles"]
    combined_count = yf_count + news_info["count"]
    
    if market == "TW": forum_count = get_dcard_volume(kw)
    elif market == "US": forum_count = get_reddit_volume(kw)
    else: forum_count = 0 

    total_hype = max(forum_count + combined_count, 1)
    
    if total_hype > hottest_stock["hype"] and len(combined_titles) > 0:
        hottest_stock = {"name": name, "hype": total_hype, "titles": combined_titles[:5]}

    new_rows_for_db.append([today_str, ticker, name, market, current_price, trading_value_m, total_hype])
    insight = "🆕 首次建檔"

    if not df_history.empty:
        df_history['日期_格式化'] = pd.to_datetime(df_history['日期']).dt.strftime('%Y-%m-%d')
        past_records = df_history[(df_history['代號'] == ticker) & (df_history['日期_格式化'] != today_str)]
        
        if not past_records.empty:
            last_record = past_records.iloc[-1]
            try:
                past_val = float(str(last_record['成交金額_百萬美元']).replace(',', ''))
                past_hype = float(str(last_record['總聲量']).replace(',', ''))
            except:
                past_val, past_hype = 0.0, 1.0
                
            past_hype = max(past_hype, 1)
            money_mom = ((trading_value_m - past_val) / past_val) * 100 if past_val > 0 else 0
            hype_mom = ((total_hype - past_hype) / past_hype) * 100

            if money_mom > 0 and hype_mom > 0: insight = "🔥 右上：價量齊揚"
            elif money_mom > 0 and hype_mom <= 0: insight = "🤫 右下：低調吸金"
            elif money_mom <= 0 and hype_mom > 0: insight = "⚠️ 左上：聲量背離"
            else: insight = "❄️ 左下：冷門打底"

    today_pct = 0.0
    if ticker in stock_real_price_history and len(stock_real_price_history[ticker]) > 0:
        today_pct = stock_real_price_history[ticker][-1]

    today_results.append({
        "代號": ticker, 
        "名稱": name,
        "當前總聲量": total_hype,
        "今日漲跌幅": today_pct,
        "象限洞察": insight
    })

worksheet.append_rows(new_rows_for_db)
earnings_alerts = check_upcoming_earnings(us_tickers_for_earnings)
earnings_msg = f"📅 財報預警：{', '.join(earnings_alerts)}" if earnings_alerts else "📅 財報預警：7日內無重點美股財報。"

ai_insight_msg = "🤖 AI 分析：今日市場資訊量不足，無特別情緒波動。"
if GEMINI_API_KEY and hottest_stock["hype"] > 0 and len(hottest_stock["titles"]) > 0:
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        titles_text = "\n".join(hottest_stock["titles"])
        prompt = f"你是華爾街證券分析師。請根據以下新聞，給出一段50字內極簡『市場情緒快評』，並標示整體情緒為(偏多/偏空/中立/震盪)：\n{titles_text}"
        response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
        ai_insight_msg = f"🤖 AI 晨間快評【焦點：{hottest_stock['name']}】\n{response.text.strip()}"
    except: pass

# ==========================================
# 5. 繪製 Page 1: 回歸 Plotly 完美蜂巢圖 
# ==========================================
print("正在繪製 Page 1...")
df_plot = pd.DataFrame(today_results)
df_plot = df_plot.sort_values(by='當前總聲量', ascending=False).reset_index(drop=True)

pattern = [5, 6, 7, 8, 7, 5] 
x_coords, y_coords = [], []
for row_idx, count in enumerate(pattern):
    x_offset = - (count * 3.0) / 2.0
    for i in range(count):
        x_coords.append(x_offset + i * 3.0 + 1.5)
        y_coords.append(- row_idx * 2.6)

coords = [{"x": x, "y": y, "dist": (x - 0)**2 + (y + 6.5)**2} for x, y in zip(x_coords, y_coords)]
coords = sorted(coords, key=lambda k: k["dist"])

limit = min(len(df_plot), 38)
df_plot = df_plot.iloc[:limit]
df_plot['X坐標'] = [c["x"] for c in coords[:limit]]
df_plot['Y坐標'] = [c["y"] for c in coords[:limit]]

sizes, line_widths, line_colors, text_labels, text_colors, text_sizes = [], [], [], [], [], []

for i, row in df_plot.iterrows():
    rank = i + 1
    # 控制尺寸 (完美比例)
    sizes.append(65 if rank <= 3 else (58 if rank <= 10 else 48))
    line_widths.append(6 if rank <= 3 else (5 if rank <= 10 else 3))
    
    # 控制漲跌顏色
    pct = row['今日漲跌幅']
    line_colors.append('#ff4d4d' if pct > 0 else ('#00cc96' if pct < 0 else '#888888'))
    
    # 🌟 加入漲跌幅顯示
    pct_str = f"+{pct:.1f}%" if pct > 0 else f"{pct:.1f}%"
    text_labels.append(f"{row['名稱']}<br>{row['代號']}<br>{pct_str}")
    
    text_colors.append("white" if rank <= 10 else "#A0A0A0")
    text_sizes.append(15 if rank <= 10 else 12)

df_plot['MarkerSize'] = sizes
df_plot['LineWidth'] = line_widths
df_plot['LineColor'] = line_colors
df_plot['圖表標籤'] = text_labels
df_plot['TextColor'] = text_colors
df_plot['TextSize'] = text_sizes

fig1 = go.Figure()

# 黃金流體結界 (scipy Spline)
pts = np.array([
    [0.0, -2.5], [3.5, -3.0], [4.8, -6.5], [3.5, -9.8], [1.5, -10.5], 
    [0.0, -10.2], [-2.5, -10.0], [-4.5, -8.0], [-4.8, -5.0], [-3.0, -3.0], [0.0, -2.5]
])
tck, u = splprep([pts[:,0], pts[:,1]], s=0, per=True)
unew = np.linspace(0, 1, 200)
out = splev(unew, tck)
path = f"M {out[0][0]},{out[1][0]}"
for px, py in zip(out[0][1:], out[1][1:]): path += f" L {px},{py}"
path += " Z"
fig1.add_shape(type="path", path=path, line=dict(color="#FFD700", width=4), layer="below")

fig1.add_trace(go.Scatter(
    x=df_plot['X坐標'], y=df_plot['Y坐標'], mode='markers+text',
    marker=dict(size=df_plot['MarkerSize'], color='#2C2C2C', line=dict(width=df_plot['LineWidth'], color=df_plot['LineColor'])),
    text=df_plot['圖表標籤'], textposition='middle center',
    textfont=dict(size=df_plot['TextSize'], color=df_plot['TextColor'], family="Noto Sans CJK TC, sans-serif"),
    hoverinfo='none'
))

fig1.update_xaxes(visible=False, range=[-14, 14]) 
fig1.update_yaxes(visible=False, range=[-15.5, 1.5]) 
fig1.update_layout(
    title=f"【Page 1】全市場聲量熱點蜂巢圖<br>更新時間: {current_time}",
    width=1200, height=1100, margin=dict(t=100, b=120, l=40, r=40),
    template="plotly_dark", showlegend=False, font=dict(family="Noto Sans CJK TC, sans-serif")
)

# 🌟 優化註解排版：完整還原圖例說明
annotation_html = """
<div style='text-align: left; line-height: 1.8;'>
    <span style='color: white;'>中心顏色 - 情緒（深灰色統一，邊框框線熱度顯示）：</span><br>
    <span style='color: #ff4d4d;'>🔴 偏多</span>　<span style='color: #00cc96;'>🟢 震盪</span>　<span style='color: #888888;'>⚪ 中立</span>　<span style='color: #AB63FA;'>🟣 偏空</span>
</div>
"""

annotation_html2 = """
<div style='text-align: left; line-height: 1.8;'>
    <span style='color: #FFD700;'>不規則金色流體框線：</span><span style='color: white;'>代表全市場前十名最熱門聲量討論核心集中區 (聲量越大越靠近中央上方)</span><br>
    <span style='color: white;'>泡泡邊框顏色：代表動能狀態</span>
</div>
"""

fig1.add_annotation(
    text=annotation_html, xref="paper", yref="paper", x=0.05, y=-0.1, 
    showarrow=False, font=dict(size=14), xanchor="left", yanchor="top"
)

fig1.add_annotation(
    text=annotation_html2, xref="paper", yref="paper", x=0.5, y=-0.1, 
    showarrow=False, font=dict(size=14), xanchor="left", yanchor="top"
)


fig1.write_image("radar_page1.jpg", scale=2)

# ==========================================
# 6. 繪製 Page 2: 乾淨 Plotly K 線矩陣
# ==========================================
print("正在計算五日歷史軌跡...")
columns = ["日期", "代號", "名稱", "市場", "收盤價", "成交金額_百萬美元", "總聲量"]
df_today = pd.DataFrame(new_rows_for_db, columns=columns)
df_all = pd.concat([df_history, df_today], ignore_index=True)
df_all['日期_格式化'] = pd.to_datetime(df_all['日期']).dt.strftime('%Y-%m-%d')
df_all['成交金額_百萬美元'] = pd.to_numeric(df_all['成交金額_百萬美元'].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
df_all['總聲量'] = pd.to_numeric(df_all['總聲量'].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
df_all = df_all.drop_duplicates(subset=['代號', '日期_格式化'], keep='last')
df_all = df_all.sort_values(by=['代號', '日期_格式化'])

table_data, table_colors = [], []

for info in stock_pool:
    tk, name = info["ticker"], info["name"]
    df_sub = df_all[df_all['代號'] == tk].tail(6)
    
    row_texts = [name, "⚪ 0.0%", "⚪ 0.0%", "⚪ 0.0%", "⚪ 0.0%", "⚪ 0.0%"]
    row_colors = ["white"] * 6 
    
    qs = ["⚪"] * 5
    if len(df_sub) >= 2:
        vals, hypes = df_sub['成交金額_百萬美元'].values, df_sub['總聲量'].values
        for i in range(1, len(df_sub)):
            money_mom = ((vals[i] - vals[i-1]) / vals[i-1] * 100) if vals[i-1] > 0 else 0
            hype_mom = ((hypes[i] - hypes[i-1]) / hypes[i-1] * 100) if hypes[i-1] > 0 else 0
            
            if money_mom > 0 and hype_mom > 0: q = "🔥"
            elif money_mom > 0 and hype_mom <= 0: q = "🤫"
            elif money_mom <= 0 and hype_mom > 0: q = "⚠️"
            else: q = "❄️"
            
            if 0 <= (5 - (len(df_sub) - i)) < 5: qs[5 - (len(df_sub) - i)] = q

    recent_pcts = stock_real_price_history.get(tk, [0.0] * 5)

    for idx in range(5):
        q, pct = qs[idx], recent_pcts[idx]
        
        if pct > 0: p_str, cell_color = f"+{pct:.1f}%", "#ff4d4d"
        elif pct < 0: p_str, cell_color = f"{pct:.1f}%", "#00cc96"
        else: p_str, cell_color = "0.0%", "#888888"
            
        row_texts[idx+1] = f"{q} {p_str}"  
        row_colors[idx+1] = cell_color     
                
    table_data.append(row_texts)
    table_colors.append(row_colors)

col_data = list(zip(*table_data))
col_colors = list(zip(*table_colors))

headers = ['標的名稱', 'T-4', 'T-3', 'T-2', 'T-1', 'Today']
fig2 = go.Figure(data=[go.Table(
    columnwidth=[100, 100, 100, 100, 100, 100],
    header=dict(values=headers, fill_color='#2c2c2c', font=dict(color='white', size=15), align='center', height=40),
    cells=dict(values=col_data, fill_color='#1e1e1e', font=dict(color=col_colors, size=14), align='center', height=40)
)])

fig2.update_layout(
    title="【Page 2】五日動能與真實漲跌幅矩陣", 
    template="plotly_dark", margin=dict(l=20, r=20, t=60, b=20), 
    height=150 + len(stock_pool) * 40, 
    font=dict(family="Noto Sans CJK TC, sans-serif")
)
fig2.write_image("trend_page2.jpg", scale=2)

# ==========================================
# 7. 上傳圖床並發送 LINE 訊息
# ==========================================
def upload_image(file_path):
    try:
        res = requests.post("https://catbox.moe/user/api.php", data={"reqtype": "fileupload"}, files={"fileToUpload": open(file_path, "rb")}, timeout=15)
        if res.status_code == 200: return res.text
    except: pass
    try:
        import base64
        with open(file_path, "rb") as f: img_data = base64.b64encode(f.read()).decode('utf-8')
        res = requests.post("https://freeimage.host/api/1/upload", data={"key": "6d207e02198a847aa98d0a2a901485a5", "action": "upload", "source": img_data, "format": "json"}, timeout=15)
        if res.status_code == 200: return res.json()['image']['url']
    except: return None

print("正在上傳圖片...")
img_url_1 = upload_image("radar_page1.jpg")
img_url_2 = upload_image("trend_page2.jpg")

if img_url_1 or img_url_2:
    smart_money = [row['名稱'] for row in today_results if "🤫 右下：低調吸金" in row['象限洞察']]
    money_msg = f"🤫 特別吸金：{', '.join(smart_money)}" if smart_money else "🤫 特別吸金：無特別低調吸金標的"
    
    final_text = f"🌞 早安！為您送上今日全市場動能雷達。\n\n{money_msg}\n\n{earnings_msg}\n\n{ai_insight_msg}\n\n🕒 資料產出時間：{current_time}\n🏷️ 檢索標籤：#市場動能 #法人籌碼 #量化交易 #台股 #美股 #日股"
    
    messages = [{"type": "text", "text": final_text}]
    if img_url_1: messages.append({"type": "image", "originalContentUrl": img_url_1, "previewImageUrl": img_url_1})
    if img_url_2: messages.append({"type": "image", "originalContentUrl": img_url_2, "previewImageUrl": img_url_2})
    
    requests.post("https://api.line.me/v2/bot/message/push", headers={"Content-Type": "application/json", "Authorization": f"Bearer {LINE_ACCESS_TOKEN}"}, json={"to": LINE_USER_ID, "messages": messages}, timeout=10)
    print("✅ LINE 雙圖表訊息發送完畢！")
else: print("❌ 圖片上傳失敗，無法發送 LINE。")
