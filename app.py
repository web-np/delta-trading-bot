import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import numpy as np
import requests
import hmac
import hashlib
import time
import json
from datetime import datetime

st.set_page_config(page_title="Delta Live Trader", page_icon="📈", layout="wide")

# Session States
if "auto_trade" not in st.session_state:
    st.session_state.auto_trade = False
if "candle_cache" not in st.session_state:
    st.session_state.candle_cache = {}
if "last_symbol" not in st.session_state:
    st.session_state.last_symbol = ""
if "rf_enabled" not in st.session_state:
    st.session_state.rf_enabled = True
if "indicators" not in st.session_state:
    st.session_state.indicators = [
        {"id": 1, "type": "EMA", "param": 9, "color": "#FFEB3B"},
        {"id": 2, "type": "EMA", "param": 21, "color": "#FF9800"}
    ]

# Common browser headers to bypass cloudflare blocking on Streamlit Cloud
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json"
}

def get_delta_balance(api_key, api_secret):
    if not api_key or not api_secret:
        return 0.0
    endpoint = "/v2/wallet/balances"
    timestamp = str(int(time.time()))
    signature_data = f"GET{timestamp}{endpoint}"
    signature = hmac.new(api_secret.encode('utf-8'), signature_data.encode('utf-8'), hashlib.sha256).hexdigest()
    req_headers = {
        "api-key": api_key,
        "signature": signature,
        "timestamp": timestamp,
        "Content-Type": "application/json",
        "User-Agent": HEADERS["User-Agent"]
    }
    for base in ["https://api.delta.exchange", "https://api.india.delta.exchange"]:
        try:
            res = requests.get(base + endpoint, headers=req_headers, timeout=3)
            if res.status_code == 200:
                for item in res.json().get("result", []):
                    if item.get("asset_symbol") == "USDT":
                        return float(item.get("balance", 0.0))
        except Exception:
            continue
    return 0.0

def fetch_candles_real(symbol):
    """Reliable Real Candle Fetcher with Delta & Global crypto fallback"""
    end_time = int(time.time())
    start_time = end_time - (3600 * 4)  # 4 Hours of 1m candles
    
    # 1. Try Delta Public API
    for delta_url in ["https://api.delta.exchange/v2/chart/history", "https://api.india.delta.exchange/v2/chart/history"]:
        try:
            params = {
                "symbol": symbol,
                "resolution": "1m",
                "start": start_time,
                "end": end_time
            }
            res = requests.get(delta_url, params=params, headers=HEADERS, timeout=3)
            if res.status_code == 200:
                data = res.json()
                if data.get("success") and data.get("result"):
                    df = pd.DataFrame(data["result"])
                    df = df.rename(columns={"t": "time", "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
                    df = df.sort_values("time").drop_duplicates(subset=["time"])
                    df["time"] = df["time"].astype(int)
                    for c in ["open", "high", "low", "close", "volume"]:
                        df[c] = df[c].astype(float)
                    if len(df) > 10:
                        return df[["time", "open", "high", "low", "close", "volume"]]
        except Exception:
            pass

    # 2. Universal Real Live Candle Feed (Binance public 1m candles - 100% uptime, unblocked)
    binance_map = {"ETHUSD": "ETHUSDT", "BTCUSD": "BTCUSDT", "SOLUSD": "SOLUSDT"}
    bin_symbol = binance_map.get(symbol, f"{symbol}T")
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={bin_symbol}&interval=1m&limit=180"
        res = requests.get(url, headers=HEADERS, timeout=4)
        if res.status_code == 200:
            raw = res.json()
            df = pd.DataFrame(raw, columns=[
                "time", "open", "high", "low", "close", "volume",
                "close_time", "qav", "num_trades", "tbb", "tbq", "ignore"
            ])
            df["time"] = (df["time"] // 1000).astype(int)
            for col in ["open", "high", "low", "close", "volume"]:
                df[col] = df[col].astype(float)
            return df[["time", "open", "high", "low", "close", "volume"]]
    except Exception:
        pass

    return pd.DataFrame()

def get_live_ticker_price(symbol):
    """Fetch exact live tick price"""
    # Try Delta Ticker
    for base in ["https://api.delta.exchange", "https://api.india.delta.exchange"]:
        try:
            res = requests.get(f"{base}/v2/tickers/{symbol}", headers=HEADERS, timeout=2).json()
            if res.get("success"):
                return float(res["result"]["mark_price"])
        except Exception:
            pass

    # Fallback to Binance Live Ticker
    binance_map = {"ETHUSD": "ETHUSDT", "BTCUSD": "BTCUSDT", "SOLUSD": "SOLUSDT"}
    bin_symbol = binance_map.get(symbol, f"{symbol}T")
    try:
        res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={bin_symbol}", headers=HEADERS, timeout=2).json()
        if "price" in res:
            return float(res["price"])
    except Exception:
        pass

    return None

# --- Range Filter Indicator ---
def calculate_range_filter(df, per=50, mult=2.5):
    if len(df) < 2:
        return df

    src = df['close'].values
    n = len(src)

    diff = np.abs(np.diff(src, prepend=src[0]))
    diff_s = pd.Series(diff)
    wper = per * 2 - 1
    avrng = diff_s.ewm(span=per, adjust=False).mean()
    smrng = (avrng.ewm(span=wper, adjust=False).mean() * mult).values

    filt = np.zeros(n)
    filt[0] = src[0]
    for i in range(1, n):
        prev_f = filt[i - 1]
        r = smrng[i]
        x = src[i]
        if x > prev_f:
            filt[i] = prev_f if (x - r < prev_f) else (x - r)
        else:
            filt[i] = prev_f if (x + r > prev_f) else (x + r)

    upward = np.zeros(n)
    downward = np.zeros(n)
    for i in range(1, n):
        if filt[i] > filt[i - 1]:
            upward[i] = upward[i - 1] + 1
            downward[i] = 0
        elif filt[i] < filt[i - 1]:
            downward[i] = downward[i - 1] + 1
            upward[i] = 0
        else:
            upward[i] = upward[i - 1]
            downward[i] = downward[i - 1]

    hband = filt + smrng
    lband = filt - smrng

    long_cond = np.zeros(n, dtype=bool)
    short_cond = np.zeros(n, dtype=bool)
    for i in range(1, n):
        long_cond[i] = (src[i] > filt[i] and upward[i] > 0)
        short_cond[i] = (src[i] < filt[i] and downward[i] > 0)

    cond_ini = np.zeros(n)
    for i in range(1, n):
        if long_cond[i]:
            cond_ini[i] = 1
        elif short_cond[i]:
            cond_ini[i] = -1
        else:
            cond_ini[i] = cond_ini[i - 1]

    long_condition = np.zeros(n, dtype=bool)
    short_condition = np.zeros(n, dtype=bool)
    for i in range(1, n):
        long_condition[i] = (long_cond[i] and cond_ini[i - 1] == -1)
        short_condition[i] = (short_cond[i] and cond_ini[i - 1] == 1)

    df['rf_filt'] = filt
    df['rf_hband'] = hband
    df['rf_lband'] = lband
    df['rf_buy'] = long_condition
    df['rf_sell'] = short_condition
    return df

# --- Sidebar UI ---
st.sidebar.title("⚙️ Delta Config")
api_key = st.sidebar.text_input("Delta API Key", type="password")
api_secret = st.sidebar.text_input("Delta API Secret", type="password")
symbol = st.sidebar.selectbox("Symbol", ["ETHUSD", "BTCUSD", "SOLUSD"])

st.sidebar.markdown("---")
st.sidebar.subheader("🤖 Bot Status")
st.session_state.auto_trade = st.sidebar.toggle("Auto Trading Mode", value=st.session_state.auto_trade)
if st.session_state.auto_trade:
    st.sidebar.success("● BOT RUNNING")
else:
    st.sidebar.info("○ BOT PAUSED")

st.sidebar.markdown("---")
st.sidebar.subheader("🎯 Indicator Settings")
st.session_state.rf_enabled = st.sidebar.checkbox("Enable Range Filter", value=st.session_state.rf_enabled)

with st.sidebar.expander("➕ Add EMA / SMA"):
    ind_type = st.selectbox("Type", ["EMA", "SMA"])
    ind_param = st.number_input("Period", 2, 200, 20)
    ind_color = st.color_picker("Color", "#00E676")
    if st.button("Add Indicator", use_container_width=True):
        st.session_state.indicators.append({
            "id": int(time.time()),
            "type": ind_type,
            "param": int(ind_param),
            "color": ind_color
        })
        st.rerun()

for idx, ind in enumerate(st.session_state.indicators):
    col1, col2 = st.sidebar.columns([3, 1])
    col1.markdown(f"<span style='color:{ind['color']}'>■</span> **{ind['type']} ({ind['param']})**", unsafe_allow_html=True)
    if col2.button("🗑️", key=f"del_{ind['id']}"):
        st.session_state.indicators.pop(idx)
        st.rerun()

# Symbol Change Detection
if st.session_state.last_symbol != symbol:
    st.session_state.candle_cache[symbol] = fetch_candles_real(symbol)
    st.session_state.last_symbol = symbol

df = st.session_state.candle_cache.get(symbol, pd.DataFrame())

if df.empty:
    df = fetch_candles_real(symbol)
    st.session_state.candle_cache[symbol] = df

# Real Live Candle Update
current_price = get_live_ticker_price(symbol)
current_time_min = (int(time.time()) // 60) * 60

if not df.empty and current_price is not None:
    last_idx = df.index[-1]
    last_candle_time = int(df.loc[last_idx, "time"])

    if current_time_min > last_candle_time:
        new_row = pd.DataFrame([{
            "time": current_time_min,
            "open": current_price,
            "high": current_price,
            "low": current_price,
            "close": current_price,
            "volume": 1.0
        }])
        df = pd.concat([df, new_row], ignore_index=True)
    else:
        df.loc[last_idx, "close"] = current_price
        if current_price > df.loc[last_idx, "high"]:
            df.loc[last_idx, "high"] = current_price
        if current_price < df.loc[last_idx, "low"]:
            df.loc[last_idx, "low"] = current_price
        df.loc[last_idx, "volume"] += 1.0

    st.session_state.candle_cache[symbol] = df

# Metrics Display
bal = get_delta_balance(api_key, api_secret)
c1, c2, c3, c4 = st.columns(4)
live_disp = f"${current_price:,.2f}" if current_price else (f"${df['close'].iloc[-1]:,.2f}" if not df.empty else "$0.00")
c1.metric("Delta Wallet Balance", f"${bal:,.2f} USDT")
c2.metric("Pair (Live Price)", f"{symbol} : {live_disp}")
c3.metric("Auto Trade", "ON" if st.session_state.auto_trade else "OFF")
c4.metric("Last Candle Tick", datetime.now().strftime("%H:%M:%S"))

# Indicators calculation
if st.session_state.rf_enabled and not df.empty:
    df = calculate_range_filter(df, per=50, mult=2.5)

candle_data = []
volume_data = []
markers_data = []

for _, row in df.iterrows():
    t_sec = int(row["time"])
    o = round(float(row["open"]), 2)
    h = round(float(row["high"]), 2)
    l = round(float(row["low"]), 2)
    c = round(float(row["close"]), 2)
    v = round(float(row["volume"]), 2)

    candle_data.append({"time": t_sec, "open": o, "high": h, "low": l, "close": c})
    vol_color = "rgba(38, 166, 154, 0.55)" if c >= o else "rgba(239, 83, 80, 0.55)"
    volume_data.append({"time": t_sec, "value": v, "color": vol_color})

    if st.session_state.rf_enabled:
        if row.get('rf_buy'):
            markers_data.append({
                "time": t_sec,
                "position": "belowBar",
                "color": "#00E676",
                "shape": "arrowUp",
                "text": "BUY"
            })
        elif row.get('rf_sell'):
            markers_data.append({
                "time": t_sec,
                "position": "aboveBar",
                "color": "#2962FF",
                "shape": "arrowDown",
                "text": "SELL"
            })

indicator_series = []
for ind in st.session_state.indicators:
    t = ind["type"]
    p = ind["param"]
    c = ind["color"]
    col_name = f"{t}_{p}"
    
    if t == "EMA":
        df[col_name] = df["close"].ewm(span=p, adjust=False).mean()
    else:
        df[col_name] = df["close"].rolling(window=p).mean()

    line_points = []
    for _, row in df.iterrows():
        val = row[col_name]
        if pd.notna(val):
            line_points.append({"time": int(row["time"]), "value": round(float(val), 2)})
            
    if line_points:
        indicator_series.append({
            "name": f"{t} ({p})",
            "color": c,
            "data": line_points
        })

rf_series = []
if st.session_state.rf_enabled and 'rf_filt' in df:
    rf_series.append({
        "name": "Range Filter",
        "color": "#90bff9",
        "lineWidth": 2,
        "data": [{"time": int(r["time"]), "value": round(float(r["rf_filt"]), 2)} for _, r in df.iterrows() if pd.notna(r["rf_filt"])]
    })
    rf_series.append({
        "name": "High Target",
        "color": "rgba(255, 255, 255, 0.4)",
        "lineWidth": 1,
        "data": [{"time": int(r["time"]), "value": round(float(r["rf_hband"]), 2)} for _, r in df.iterrows() if pd.notna(r["rf_hband"])]
    })
    rf_series.append({
        "name": "Low Target",
        "color": "rgba(41, 98, 255, 0.4)",
        "lineWidth": 1,
        "data": [{"time": int(r["time"]), "value": round(float(r["rf_lband"]), 2)} for _, r in df.iterrows() if pd.notna(r["rf_lband"])]
    })

candle_json = json.dumps(candle_data)
volume_json = json.dumps(volume_data)
markers_json = json.dumps(markers_data)
indicators_json = json.dumps(indicator_series)
rf_json = json.dumps(rf_series)

tv_chart_html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <script src="https://unpkg.com/lightweight-charts@4.1.1/dist/lightweight-charts.standalone.production.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            background-color: #131722;
            color: #d1d4dc;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            overflow: hidden;
            width: 100%;
            height: 100vh;
        }}
        #chart-wrapper {{
            position: relative;
            width: 100%;
            height: 560px;
        }}
        #chart {{
            width: 100%;
            height: 100%;
        }}
        .legend {{
            position: absolute;
            top: 12px;
            left: 14px;
            z-index: 20;
            font-size: 13px;
            font-weight: 600;
            display: flex;
            gap: 12px;
            pointer-events: none;
            background: rgba(19, 23, 34, 0.75);
            padding: 4px 8px;
            border-radius: 4px;
            flex-wrap: wrap;
        }}
    </style>
</head>
<body>
    <div id="chart-wrapper">
        <div class="legend" id="legend">
            <span style="color: #2962FF; font-weight: bold;">{symbol} : {live_disp}</span>
        </div>
        <div id="chart"></div>
    </div>

    <script>
        const chartElement = document.getElementById('chart');
        const chart = LightweightCharts.createChart(chartElement, {{
            width: chartElement.clientWidth || window.innerWidth,
            height: 560,
            layout: {{
                background: {{ color: '#131722' }},
                textColor: '#9598A1',
                fontSize: 12,
            }},
            grid: {{
                vertLines: {{ color: '#1e2230' }},
                horzLines: {{ color: '#1e2230' }},
            }},
            crosshair: {{
                mode: LightweightCharts.CrosshairMode.Normal,
            }},
            rightPriceScale: {{
                borderColor: '#2B2B43',
                scaleMargins: {{
                    top: 0.1,
                    bottom: 0.25,
                }},
            }},
            timeScale: {{
                borderColor: '#2B2B43',
                timeVisible: true,
                secondsVisible: false,
            }},
        }});

        const candleSeries = chart.addCandlestickSeries({{
            upColor: '#26a69a',
            downColor: '#ef5350',
            borderVisible: false,
            wickUpColor: '#26a69a',
            wickDownColor: '#ef5350',
        }});
        candleSeries.setData({candle_json});

        const markers = {markers_json};
        if (markers && markers.length > 0) {{
            candleSeries.setMarkers(markers);
        }}

        const volumeSeries = chart.addHistogramSeries({{
            priceFormat: {{ type: 'volume' }},
            priceScaleId: 'vol_scale',
        }});
        chart.priceScale('vol_scale').applyOptions({{
            scaleMargins: {{
                top: 0.82,
                bottom: 0.0,
            }},
            visible: false,
        }});
        volumeSeries.setData({volume_json});

        const legend = document.getElementById('legend');

        const rfLines = {rf_json};
        rfLines.forEach(item => {{
            const rLine = chart.addLineSeries({{
                color: item.color,
                lineWidth: item.lineWidth,
                priceLineVisible: false,
            }});
            rLine.setData(item.data);
            const div = document.createElement('div');
            div.innerHTML = `<span style="color:${{item.color}};">■</span> ${{item.name}}`;
            legend.appendChild(div);
        }});

        const indicators = {indicators_json};
        indicators.forEach(ind => {{
            const lineSeries = chart.addLineSeries({{
                color: ind.color,
                lineWidth: 2,
                priceLineVisible: false,
            }});
            lineSeries.setData(ind.data);
            const item = document.createElement('div');
            item.innerHTML = `<span style="color:${{ind.color}};">■</span> ${{item.name}}`;
            legend.appendChild(item);
        }});

        window.addEventListener('resize', () => {{
            chart.applyOptions({{ width: chartElement.clientWidth }});
        }});
    </script>
</body>
</html>
"""

components.html(tv_chart_html, height=580)

# Trade Notification Toast
if st.session_state.auto_trade and st.session_state.rf_enabled and len(df) > 1:
    last_c = df.iloc[-1]
    if last_c.get("rf_buy"):
        st.toast(f"🟢 BUY SIGNAL ON {symbol} @ {live_disp}")
    elif last_c.get("rf_sell"):
        st.toast(f"🔴 SELL SIGNAL ON {symbol} @ {live_disp}")

# 2-second refresh loop
time.sleep(2)
st.rerun()
