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
import plotly.express as px
import plotly.graph_objects as go
import feedparser
from google.oauth2.service_account import Credentials
import gspread
from google import genai
import praw

print("啟動【跨國巨頭 38 檔：板塊熱點圖 & 雙軌資料源版】法人戰情機器人...")

# 1. 讀取金鑰
LINE_ACCESS_TOKEN = os.getenv('LINE_ACCESS_TOKEN')
LINE_USER_ID = os.getenv('LINE_USER_ID')
gcp_sa_key_json = os.getenv('GCP_SA_KEY')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
REDDIT_CLIENT_ID = os.getenv('REDDIT_CLIENT_ID')
REDDIT_CLIENT_SECRET = os.getenv('REDDIT_CLIENT_SECRET')

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
# 4. 抓取數據與建立雙軌資料庫 (38檔名單)
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

# 🌟 新增：獨立保存最乾淨的 YFinance 真實漲跌幅陣列
stock_real_price_history = {}

for info in stock_pool:
    ticker, name, market, kw = info["ticker"], info["name"], info["market"], info["keywords"][0]
    rate = exchange_rates.get(market, 1.0)
    if market == "US": us_tickers_for_earnings.append(ticker)
    
    try:
        stock = yf.Ticker(ticker)
        # 抓取近 10 日 K 線以確保有足夠的交易日計算漲跌幅
        hist = stock.history(period="10d")
        
        if not hist.empty:
            current_price = float(hist['Close'].iloc[-1])
            current_vol = float(hist['Volume'].iloc[-1])
            trading_value_m = round((current_vol * current_price * rate) / 1000000, 2)
            
            # 💡 核心解耦：直接在這裡計算過去 5 天的真實交易日漲跌幅，不再依賴 Google Sheets！
            if len(hist) >= 2:
                closes = hist['Close'].values
                pcts = np.diff(closes) / closes[:-1] * 100
                last_5_pcts = list(pcts[-5:])
                # 如果新上市資料不足 5 天，用 0.0 補齊前方
                while len(last_5_pcts) < 5: last_5_pcts.insert(0, 0.0)
                stock_real_price_history[ticker] = last_5_pcts
            else:
                stock_real_price_history[ticker] = [0.0] * 5
        else:
            current_price, trading_value_m = 0.0, 0.0
            stock_real_price_history[ticker] = [0.0] * 5
            
        yf_news = stock.news
        yf_titles = [n['title'] for n in yf_news[:5]] if yf_news else []
        yf_count = len(yf_news) if yf_news else 0
    except Exception as e:
        current_price, trading_value_m = 0.0, 0.0
        yf_titles, yf_count = [], 0
        stock_real_price_history[ticker] = [0.0] * 5

    news_info = get_news_data(kw)
    combined_titles = yf_titles + news_info["titles"]
    combined_count = yf_count + news_info["count"]
    
    if market == "TW":
        forum_count = get_dcard_volume(kw)
    elif market == "US":
        forum_count = get_reddit_volume(kw)
    else:
        forum_count = 0 

    total_hype = max(forum_count + combined_count, 1)
    
    if total_hype > hottest_stock["hype"] and len(combined_titles) > 0:
        hottest_stock = {"name": name, "hype": total_hype, "titles": combined_titles[:5]}

    new_rows_for_db.append([today_str, ticker, name, market, current_price, trading_value_m, total_hype])

    money_mom, hype_mom = 0, 0
    insight, emoji = "🆕 首次建檔", "⚪"

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
        client = genai.Client(api_key=GEMINI_API_KEY)
        titles_text = "\n".join(hottest_stock["titles"])
        prompt = f"你是華爾街頂級證券分析師。請根據以下關於【{hottest_stock['name']}】的最新新聞標題，給出一段50字以內的極簡『市場情緒快評』，並標示整體情緒為(偏多/偏空/中立/震盪)：\n{titles_text}"
        
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        ai_insight_msg = f"🤖 AI 晨間快評【焦點：{hottest_stock['name']}】\n{response.text.strip()}"
    except Exception as e:
        pass

# ==========================================
# 5. 繪製 Page 1: 板塊熱點圖 (Treemap)
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

# 🌟 重構為板塊熱點圖 (Treemap)，面積=總聲量，顏色=象限洞察
fig1 = px.treemap(
    df_plot,
    path=[px.Constant("全市場動能板塊"), '象限洞察', '名稱'],
    values='當前總聲量',
    color='象限洞察',
    color_discrete_map={
        "🔥 右上：價量齊揚": "#EF553B", 
        "🤫 右下：低調吸金": "#00CC96", 
        "⚠️ 左上：聲量背離": "#AB63FA", 
        "❄️ 左下：冷門打底": "#636EFA", 
        "🆕 首次建檔": "#808080"
    },
    title=f"【Page 1】全市場聲量板塊熱點圖<br>更新時間: {current_time}",
    template="plotly_dark"
)

# 設定 Treemap 文字格式
fig1.update_traces(
    textinfo="label+value",
    texttemplate="<b>%{label}</b><br>聲量: %{value}",
    hovertemplate="<b>%{label}</b><br>總聲量: %{value}<br>所屬板塊: %{parent}"
)

fig1.update_layout(width=1200, height=1100, margin=dict(t=100, b=350, l=40, r=40))

footer_text = "<b>【象限定義】</b> 🔥 價量齊揚(強勢噴出) ｜ 🤫 低調吸金(潛伏買點) ｜ ⚠️ 聲量背離(出場警示) ｜ ❄️ 冷門打底" + list_text
fig1.add_annotation(
    text=footer_text, xref="paper", yref="paper", 
    x=0, y=-0.35, showarrow=False, font=dict(size=14, color="#A0A0A0"), 
    xanchor="left", yanchor="top", align="left"
)

img_path_1 = "radar_page1.jpg"
fig1.write_image(img_path_1, scale=2)

# ==========================================
# 6. 繪製 Page 2: 真實行情解耦矩陣版
# ==========================================
print("正在計算五日歷史軌跡與滾動漲跌幅...")
columns = ["日期", "代號", "名稱", "市場", "收盤價", "成交金額_百萬美元", "總聲量"]
df_today = pd.DataFrame(new_rows_for_db, columns=columns)
df_all = pd.concat([df_history, df_today], ignore_index=True)

df_all['日期_格式化'] = pd.to_datetime(df_all['日期']).dt.strftime('%Y-%m-%d')
# 我們只保留動能相關數據，股價已由上方 YFinance 直接計算
df_all['成交金額_百萬美元'] = pd.to_numeric(df_all['成交金額_百萬美元'].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
df_all['總聲量'] = pd.to_numeric(df_all['總聲量'].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
df_all = df_all.drop_duplicates(subset=['代號', '日期_格式化'], keep='last')
df_all = df_all.sort_values(by=['代號', '日期_格式化'])

table_data = []      
table_colors = []    

for info in stock_pool:
    tk = info["ticker"]
    name = info["name"]
    df_sub = df_all[df_all['代號'] == tk].tail(6)
    
    row_texts = [name, "⚪ -", "⚪ -", "⚪ -", "⚪ -", "⚪ -"]
    row_colors = ["#ffffff"] * 6 
    
    # 步驟 1：從資料庫萃取「動能象限符號 (Emoji)」
    qs = ["⚪"] * 5
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
                qs[target_idx] = q

    # 步驟 2：從 YFinance 獨立矩陣取出「最真實的 5 日漲跌幅」
    recent_pcts = stock_real_price_history.get(tk, [0.0] * 5)

    # 步驟 3：完美拼裝 Emoji 與真實漲跌幅！
    for idx in range(5):
        q = qs[idx]
        pct = recent_pcts[idx]
        
        p_str = "-"
        cell_color = "#ffffff"  
        
        # 只要 YFinance 有抓到行情，就絕對會顯示顏色！
        if pct > 0:
            p_str = f"+{pct:.1f}%"
            cell_color = "#ff4d4d"
        elif pct < 0:
            p_str = f"{pct:.1f}%"
            cell_color = "#00cc96"
        elif pct == 0.0 and q != "⚪":
            p_str = "0.0%"
            cell_color = "#888888"
            
        row_texts[idx+1] = f"{q} {p_str}"  
        row_colors[idx+1] = cell_color     
                
    table_data.append(row_texts)
    table_colors.append(row_colors)

col_data = list(zip(*table_data))
col_colors = list(zip(*table_colors))

headers = ['<b>標的名稱</b>', '<b>T-4</b>', '<b>T-3</b>', '<b>T-2</b>', '<b>T-1</b>', '<b>Today</b>']
fig2 = go.Figure(data=[go.Table(
    columnwidth=[100, 100, 100, 100, 100, 100],
    header=dict(values=headers, fill_color='#2c2c2c', font=dict(color='white', size=14), align='center', height=40),
    cells=dict(values=col_data, fill_color='#1e1e1e', font=dict(color=col_colors, size=14), align='center', height=35)
)])

dynamic_height = 150 + len(stock_pool) * 35
fig2.update_layout(title="【Page 2】五日動能與漲跌幅矩陣 (真實行情版)", template="plotly_dark", margin=dict(l=20, r=20, t=60, b=20), height=dynamic_height)

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
