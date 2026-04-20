import yfinance as yf
import json
import datetime
import pandas as pd
import requests
from bs4 import BeautifulSoup
import re
import os
import time
import random

# 1. 讀取監測清單
STOCKS_FILE = 'stocks.json'
if os.path.exists(STOCKS_FILE):
    with open(STOCKS_FILE, 'r', encoding='utf-8') as f:
        stocks_config = json.load(f)
else:
    stocks_config = {
        "6761.TWO": "穩得", "2402.TW": "毅嘉", "1582.TW": "信錦",
        "6407.TWO": "相互", "3585.TWO": "聯致", "4569.TW": "六方科-KY",
        "3305.TW": "昇貿", "3701.TW": "大眾控", "3231.TW": "緯創"
    }

def get_stock_details_from_yahoo(symbol):
    """
    更強力的網頁抓取，獲取成交價與昨收價
    """
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    try:
        url = f"https://tw.stock.yahoo.com/quote/{symbol}"
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            # 1. 抓取成交價
            # 嘗試多種可能出現成交價的 Class
            last_price = None
            price_selectors = [
                {'class': re.compile(r'Fz\(32px\)')},
                {'class': re.compile(r'Fz\(24px\)')},
                {'data-field': 'regularMarketPrice'}
            ]
            for sel in price_selectors:
                tag = soup.find('span', **sel)
                if tag:
                    try:
                        last_price = float(tag.text.replace(',', '').strip())
                        break
                    except: continue

            # 2. 抓取昨收價
            # 暴力搜尋包含 "昨收" 文字的標籤
            prev_close = None
            all_spans = soup.find_all('span')
            for i, span in enumerate(all_spans):
                if "昨收" in span.text:
                    # 通常數值就在後一個 span 或同一個 li 內
                    # 遍歷後續 3 個 span 找數字
                    for j in range(1, 4):
                        if i + j < len(all_spans):
                            candidate = all_spans[i+j].text.replace(',', '').strip()
                            if re.match(r'^\d+\.?\d*$', candidate):
                                prev_close = float(candidate)
                                break
                    if prev_close: break
            
            return last_price, prev_close
    except Exception as e:
        print(f"DEBUG: Scrape {symbol} error: {e}")
    return None, None

def analyze_chips(chips):
    if not chips: return "無籌碼數據", ["目前暫無法人籌碼數據可供分析。"]
    c5 = chips[:5]; f5 = sum(d['foreign'] for d in c5); t5 = sum(d['trust'] for d in c5); total5 = sum(d['total'] for d in c5)
    t20 = sum(d['trust'] for d in chips)
    status = "盤整待變"; points = []
    if total5 > 100:
        if f5 > 0 and t5 > 0: status = "強勢買超"; points.append(f"🔥 近5日外資與投信同步加碼，合計買超 {total5:,} 張。")
        elif t5 > 200: status = "投信佈局"; points.append(f"🚀 投信近期積極作帳，近5日已佈署 {t5:,} 張。")
        elif f5 > 500: status = "外資拉抬"; points.append(f"💰 外資為主導買盤，近5日回補 {f5:,} 張。")
        else: status = "大戶偏多"; points.append(f"📈 籌碼呈現多頭排列，短線累計買超 {total5:,} 張。")
    elif total5 < -100: status = "大戶調節"; points.append(f"❄️ 法人短線調節頻繁，近5日累計賣超 {abs(total5):,} 張。")
    if t20 > 500: points.append(f"💎 20日大趨勢：投信波段持續護盤，累計買超達 {t20:,} 張。")
    return status, points

def generate_detailed_analysis(hist, chips, last_price):
    chip_status, chip_points = analyze_chips(chips)
    ma20 = hist['Close'].tail(20).mean()
    points = []
    points.extend(chip_points)
    if last_price and not pd.isna(ma20):
        if last_price > ma20: points.append(f"🚀 技術面：當前股價 ${round(last_price,2)} 位處月線之上，趨勢偏多。")
        else: points.append(f"📉 技術面：當前股價低於月線，短線呈現修正格局。")
    if chip_status in ["強勢買超", "投信佈局", "外資拉抬"] and last_price and last_price > ma20:
        points.append("💡 策略建議：**多頭趨勢確立，回測支撐可分批佈局**。")
    else: points.append("💡 策略建議：**盤勢不明，建議分批減碼或保守觀望**。")
    return points, chip_status

def get_yahoo_smart_news(symbol_raw, stock_name):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    news_items = []
    try:
        url = f"https://tw.stock.yahoo.com/quote/{symbol_raw}/news"
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            h3_tags = soup.find_all('h3', limit=15)
            for h3 in h3_tags:
                a = h3.find('a')
                if a:
                    title = a.text.strip(); link = a.get('href', '')
                    if not link.startswith('http'): link = 'https://tw.stock.yahoo.com' + link
                    news_items.append({"source": "Yahoo新聞", "title": title, "link": link})
                if len(news_items) >= 10: break
    except: pass
    return news_items

def get_institutional_trading_history(symbol):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    try:
        url = f"https://tw.stock.yahoo.com/quote/{symbol}/institutional-trading"
        resp = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(resp.text, 'html.parser')
        rows = soup.find_all('div', class_='table-row')
        history = []
        for row in rows:
            cols = row.find_all('div', recursive=False)
            if len(cols) >= 5:
                date_text = cols[0].text.strip()
                if re.search(r'\d{4}/\d{2}/\d{2}', date_text):
                    def p_num(t):
                        t = t.strip().replace(',', '')
                        try: return int(t)
                        except: return 0
                    history.append({"date": date_text, "foreign": p_num(cols[1].text), "trust": p_num(cols[2].text), "dealer": p_num(cols[3].text), "total": p_num(cols[4].text)})
            if len(history) >= 20: break
        return history
    except: return []

DATA_FILE = 'stock_data.json'
if os.path.exists(DATA_FILE): os.remove(DATA_FILE)

data = {}
tz_taipei = datetime.timezone(datetime.timedelta(hours=8))
update_time_str = datetime.datetime.now(tz_taipei).strftime("%Y-%m-%d %H:%M:%S")

for symbol, name in stocks_config.items():
    try:
        last_price, prev_close = get_stock_details_from_yahoo(symbol)
        
        ticker = yf.Ticker(symbol)
        # API 備援
        if last_price is None:
            try: last_price = ticker.fast_info['last_price']
            except: last_price = ticker.info.get('regularMarketPrice')
        if prev_close is None:
            try: prev_close = ticker.fast_info['previous_close']
            except: prev_close = ticker.info.get('previousClose')
            
        if last_price is None or prev_close is None:
            print(f"⚠️ {symbol} 跳過：無法取得報價數據。")
            continue
            
        change = last_price - prev_close
        percent = (change / prev_close) * 100
        
        hist = ticker.history(period="3mo")
        if hist.empty: continue
        
        chips = get_institutional_trading_history(symbol)
        news = get_yahoo_smart_news(symbol, name)
        analysis_points, chip_status = generate_detailed_analysis(hist, chips, last_price)
        
        vol_history = [round(v / 1000, 1) if not pd.isna(v) else 0 for v in hist['Volume'].tail(20).tolist()]
        price_history = [round(p, 2) if not pd.isna(p) else round(last_price, 2) for p in hist['Close'].tail(20).tolist()]
        today_str = datetime.datetime.now(tz_taipei).strftime('%m/%d')
        history_dates = [d.strftime('%m/%d') for d in hist.index[-20:]]
        
        if history_dates[-1] != today_str:
            price_history = price_history[1:] + [round(last_price, 2)]
            history_dates = history_dates[1:] + [today_str]

        data[symbol] = {
            "name": name, "symbol": symbol,
            "price": round(last_price, 2), "change": round(change, 2), "percent": round(percent, 2),
            "entry": round(last_price * 0.96, 2), "long_term": round(last_price * 1.5, 1),
            "chip_status": chip_status, "chips_history": chips,
            "analysis_points": analysis_points, "news_items": news,
            "vol_history": vol_history, "price_history": price_history,
            "history_dates": history_dates,
            "updated": update_time_str 
        }
        print(f"✅ {name} ({symbol}) 同步成功 [價格: {round(last_price, 2)}, 昨收: {round(prev_close, 2)}, 漲幅: {round(percent, 2)}%]")
    except Exception as e: print(f"❌ {symbol} 失敗: {e}")

json_str = json.dumps(data, indent=4, ensure_ascii=False).replace("NaN", "null")
with open(DATA_FILE, 'w', encoding='utf-8') as f:
    f.write(json_str)
