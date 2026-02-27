import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.express as px
import requests
import urllib.parse
import feedparser
from datetime import datetime
import pytz

# ==========================================
# 1. 網頁基本設定 (必須在最上方)
# ==========================================
st.set_page_config(
    page_title="法人戰情室 | 動能與輿情雷達",
    page_icon="📊",
    layout="wide"
)

st.title("📊 全市場資金動能與情緒背離四象限圖")
st.markdown("提供跨市場 (美、台、日) 資金流入與社群聲量對比，捕捉法人低調建倉與散戶過熱訊號。")

# ==========================================
# 2. 爬蟲函數定義 (加入快取機制)
# ==========================================
@st.cache_data(ttl=3600)
def get_dcard_volume(keyword):
    encoded_keyword = urllib.parse.quote(keyword)
    url = f"https://www.dcard.tw/service/api/v2/search/posts?query={encoded_keyword}&forum=stock&limit=30"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, headers=headers, timeout=5)
        return len(res.json()) if res.status_code == 200 else 0
    except:
        return 0

@st.cache_data(ttl=3600)
def get_news_volume(keyword):
    query = f'"{keyword}" (site:money.udn.com OR site:ctee.com.tw)'
    encoded_query = urllib.parse.quote(query)
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    try:
        feed = feedparser.parse(rss_url)
        return len(feed.entries) 
    except:
        return 0

# ==========================================
# 3. 核心資料處理函數
# ==========================================
@st.cache_data(ttl=3600)
def fetch_market_data():
    stock_pool = [
        {"ticker": "NVDA", "name": "輝達", "market": "US (美股)", "keywords": ["NVDA", "輝達"]},
        {"ticker": "TSLA", "name": "特斯拉", "market": "US (美股)", "keywords": ["TSLA", "特斯拉"]},
        {"ticker": "VRT", "name": "Vertiv", "market": "US (美股)", "keywords": ["VRT", "Vertiv"]},
        {"ticker": "2330.TW", "name": "台積電", "market": "TW (台股)", "keywords": ["台積電", "2330"]},
        {"ticker": "2317.TW", "name": "鴻海", "market": "TW (台股)", "keywords": ["鴻海", "2317"]},
        {"ticker": "3037.TW", "name": "欣興", "market": "TW (台股)", "keywords": ["欣興", "3037"]},
        {"ticker": "7203.T", "name": "豐田", "market": "JP (日股)", "keywords": ["豐田", "Toyota"]}
    ]

    exchange_rates = {"US (美股)": 1.0, "TW (台股)": 1/31.5, "JP (日股)": 1/150.0}
    results = []

    for info in stock_pool:
        ticker = info["ticker"]
        name = info["name"]
        market = info["market"]
        main_keyword = info["keywords"][0]
        rate = exchange_rates[market]
        
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="10d")
            
            if len(hist) >= 6:
                # 抓取最近一個交易日的數據
                current_vol = hist['Volume'].iloc[-1]
                current_price = hist['Close'].iloc[-1]
                current_value = current_vol * current_price * rate
                
                # 抓取前五個交易日的數據作為基期
                past_vol = hist['Volume'].iloc[-6]
                past_price = hist['Close'].iloc[-6]
                past_value = past_vol * past_price * rate
                
                # 抓取前兩個交易日的數據，計算單日漲跌幅
                prev_close = hist['Close'].iloc[-2]
                daily_return = ((current_price - prev_close) / prev_close) * 100 if prev_close > 0 else 0
                
                money_momentum = ((current_value - past_value) / past_value) * 100 if past_value > 0 else 0
            else:
                money_momentum, daily_return = 0, 0
                
            trading_value_m = round(current_value / 1000000, 2) if 'current_value' in locals() else 0
            
        except:
            money_momentum, trading_value_m, daily_return = 0, 0, 0

        # 聲量抓取
        dcard_vol = get_dcard_volume(main_keyword) if "TW" in market else 0
        news_vol = get_news_volume(main_keyword)
        total_hype = max((dcard_vol + news_vol), 1)

        baseline_hype = 10 
        hype_momentum = ((total_hype - baseline_hype) / baseline_hype) * 100

        # 判定象限與給予對應符號
        if money_momentum > 0 and hype_momentum > 0:
            insight = "🔥 右上：價量齊揚 (熱錢湧入)"
            emoji = "🔥"
        elif money_momentum > 0 and hype_momentum <= 0:
            insight = "🤫 右下：低調吸金 (法人吃貨)"
            emoji = "🤫"
        elif money_momentum <= 0 and hype_momentum > 0:
            insight = "⚠️ 左上：聲量背離 (出貨警戒)"
            emoji = "⚠️"
        else:
            insight = "❄️ 左下：冷門打底 (市場遺忘)"
            emoji = "❄️"

        results.append({
            "圖表標籤": f"{emoji} {name}",  # 產生帶有符號的標籤供圖表使用
            "名稱": name,
            "前一交易日漲跌幅 (%)": round(daily_return, 2),
            "資金動能變化 (%)": round(money_momentum, 2),
            "聲量動能變化 (%)": round(hype_momentum, 2),
            "當前總聲量": total_hype,
            "當日資金熱度 (百萬美元)": trading_value_m,
            "市場": market,
            "象限洞察": insight
        })

    return pd.DataFrame(results)

# ==========================================
# 4. 網頁側邊欄與執行邏輯
# ==========================================
st.sidebar.header("⚙️ 控制面板")
st.sidebar.markdown("點擊下方按鈕獲取全市場最新數據。")

if st.sidebar.button("🔄 立即更新數據", type="primary"):
    with st.spinner('正在掃描全球市場與社群數據...'):
        df = fetch_market_data()
        
        tw_tz = pytz.timezone('Asia/Taipei')
        current_time = datetime.now(tw_tz).strftime('%Y-%m-%d %H:%M:%S')
        st.success(f"✅ 資料更新完成！(台北時間: {current_time})")

        # 繪製圖表 (已更新標籤顯示)
        
        fig = px.scatter(
            df,
            x="資金動能變化 (%)", 
            y="聲量動能變化 (%)", 
            size="當前總聲量",
            color="象限洞察",
            hover_name="名稱",
            hover_data=["市場", "前一交易日漲跌幅 (%)", "當日資金熱度 (百萬美元)", "當前總聲量"],
            text="圖表標籤", # 這裡改為帶有 emoji 的標籤
            size_max=60,
            template="plotly_dark",
            color_discrete_map={
                "🔥 右上：價量齊揚 (熱錢湧入)": "#EF553B",
                "🤫 右下：低調吸金 (法人吃貨)": "#00CC96",
                "⚠️ 左上：聲量背離 (出貨警戒)": "#AB63FA",
                "❄️ 左下：冷門打底 (市場遺忘)": "#636EFA"
            }
        )

        fig.add_hline(y=0, line_dash="solid", line_color="white", opacity=0.3)
        fig.add_vline(x=0, line_dash="solid", line_color="white", opacity=0.3)
        fig.update_traces(textposition='top center')
        fig.update_layout(height=600)

        st.plotly_chart(fig, use_container_width=True)

        # 顯示資料表與欄位說明
        st.markdown("### 📋 詳細數據清單")
        
        # 重新排序表格欄位，讓重點數據在前面
        display_columns = [
            "圖表標籤", "市場", "前一交易日漲跌幅 (%)", 
            "資金動能變化 (%)", "聲量動能變化 (%)", 
            "當前總聲量", "當日資金熱度 (百萬美元)", "象限洞察"
        ]
        
        # 隱藏預設索引(Index)讓表格更乾淨，並依照資金動能排序
        st.dataframe(
            df[display_columns].sort_values(by="資金動能變化 (%)", ascending=False), 
            use_container_width=True,
            hide_index=True 
        )

        st.markdown("---")
        
        # 新增欄位與來源說明
        st.markdown("""
        **💡 數據欄位解讀指南：**
        * **前一交易日漲跌幅 (%)**：標的在最近一個交易日的收盤表現。早上 8 點檢視時，可作為昨夜美股或昨日台/日股的最終價格參考，搭配異常聲量動能，協助判斷趨勢延續或反轉。
        * **資金動能變化 (%)**：以近 1 日成交金額對比 5 天前的基準成交金額。正值代表市場真金白銀加速流入，負值代表量縮退潮。
        * **聲量動能變化 (%)**：當前網路討論熱度與常態基準的比較。暴增代表散戶情緒與媒體關注度極高。
        * **當前總聲量**：各大社群論壇與財經新聞提及該標的的加總次數（泡泡大小依此決定）。
        * **當日資金熱度 (百萬美元)**：前一交易日的總成交金額，已將台幣與日圓統一換算為美元，利於跨市場比較資金體量。

        **🔗 資料來源：**
        `Yahoo Finance` (跨國股價與交易量) | `Dcard 股票版` (台股社群聲量) | `Google News RSS` (工商時報、經濟日報等媒體聲量)
        """)
else:
    st.info("👈 請點擊左側「立即更新數據」按鈕開始分析。")
