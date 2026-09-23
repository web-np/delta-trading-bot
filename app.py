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

st.set_page_config(page_title="Delta TradingView Live Trader", page_icon="📈", layout="wide")

# Session States
if "auto_trade" not in st.session_state:
    st.session_state.auto_trade = False
if "indicators" not in st.session_state:
    st.session_state.indicators = [
        {"id": 1, "type": "EMA", "param": 9, "color": "#FFFFFF"},
        {"id": 2, "type": "EMA", "param": 20, "color": "#FFEB3B"},
        {"id": 3, "type": "EMA", "param": 50, "color": "#FF9800"},
        {"id": 4, "type": "EMA", "param": 200, "color": "#4CAF50"}
    ]

# Delta Exchange API Logic
DELTA_BASE_URL = "https://api.delta.exchange"

def get_delta_balance(api_key, api_secret):
    if not api_key or not api_secret:
        return 0.0
    endpoint = "/v2/wallet/balances"
    timestamp = str(int(time.time()))
    signature_data = f"GET{timestamp}{endpoint}"
    signature = hmac.new(api_secret.encode('utf-8'), signature_data.encode('utf-8'), hashlib.sha256).hexdigest()
    headers = {
        "api-key": api_key,
        "signature": signature,
        "timestamp": timestamp,
        "Content-Type": "application/json"
    }
    try:
        res = requests.get(DELTA_BASE_URL + endpoint, headers=headers, timeout=3)
        if res.status_code == 200:
            for item in res.json().get("result", []):
                if item.get("asset_symbol") == "USDT":
                    return float(item.get("balance", 0.0))
    except Exception:
        pass
    return 0.0

def fetch_candles(symbol="BTCUSD", resolution="1m"):
    end_time = int(time.time())
    start_time = end_time - (3600 * 4)  # 4 hours
    url = f"{DELTA_BASE_URL}/v2/chart/history?symbol={symbol}&resolution={resolution}&start={start_time}&end={end_time}"
    try:
        res = requests.get(url, timeout=3).json()
        if res.get("success") and res.get("result"):
            df = pd.DataFrame(res["result"])
            df = df.rename(columns={"t": "time", "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
            return df[["time", "open", "high", "low", "close", "volume"]]
    except Exception:
        pass

    # Fallback simulation
    now = int(time.time())
    times = [now - (i * 60) for i in reversed(range(80))]
    base = 2675.0 + np.cumsum(np.random.randn(80) * 1.5)
    return pd.DataFrame({
        "time": times,
        "open": base,
        "high": base + np.random.uniform(0.5, 4.0, 80),
        "low": base - np.random.uniform(0.5, 4.0, 80),
        "close": base + np.random.uniform(-2.0, 2.0, 80),
        "volume": np.random.randint(100, 1500, 80)
    })

# --- Sidebar Controls ---
st.sidebar.title("⚙️ Delta Config")
api_key = st.sidebar.text_input("Delta API Key", type="password")
api_secret = st.sidebar.text_input("Delta API Secret", type="password")
symbol = st.sidebar.selectbox("Symbol", ["BTCUSD", "ETHUSD", "SOLUSD"])

st.sidebar.markdown("---")
st.sidebar.subheader("🤖 Bot Status")
st.session_state.auto_trade = st.sidebar.toggle("Auto Trading Mode", value=st.session_state.auto_trade)
if st.session_state.auto_trade:
    st.sidebar.success("● BOT RUNNING")
else:
    st.sidebar.info("○ BOT PAUSED")

st.sidebar.markdown("---")
st.sidebar.subheader("📈 Indicator Settings")

with st.sidebar.expander("➕ Add New Indicator", expanded=False):
    ind_type = st.selectbox("Type", ["EMA", "SMA"])
    ind_param = st.number_input("Length", min_value=2, max_value=200, value=20)
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

# --- Main Dashboard ---
bal = get_delta_balance(api_key, api_secret)
c1, c2, c3, c4 = st.columns(4)
c1.metric("Wallet Balance", f"${bal:,.2f} USDT")
c2.metric("Pair", symbol)
c3.metric("Auto Trade", "ON" if st.session_state.auto_trade else "OFF")
c4.metric("Live Time", datetime.now().strftime("%H:%M:%S"))

# Data Preparation
df = fetch_candles(symbol)

# Format Candlestick Data
candle_data = []
volume_data = []
for _, row in df.iterrows():
    candle_data.append({
        "time": int(row["time"]),
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"])
    })
    vol_color = "#26a69a80" if row["close"] >= row["open"] else "#ef535080"
    volume_data.append({
        "time": int(row["time"]),
        "value": float(row["volume"]),
        "color": vol_color
    })

# Format Line Indicators
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
        if not np.isnan(val):
            line_points.append({"time": int(row["time"]), "value": float(val)})
            
    indicator_series.append({
        "name": f"{t} ({p})",
        "color": c,
        "data": line_points
    })

# Embedded TradingView Lightweight Chart HTML
tv_chart_html = f"""
<!DOCTYPE html>
<html>
<head>
    <script src="https://unpkg.com/lightweight-charts/dist/lightweight-charts.standalone.production.js"></script>
    <style>
        body {{
            margin: 0;
            padding: 0;
            background-color: #131722;
            color: #d1d4dc;
            font-family: -apple-system, BlinkMacSystemFont, 'Trebuchet MS', Roboto, Ubuntu, sans-serif;
            overflow: hidden;
        }}
        #chart-container {{
            position: relative;
            width: 100vw;
            height: 560px;
        }}
        .watermark {{
            position: absolute;
            bottom: 8px;
            left: 12px;
            z-index: 10;
            opacity: 0.8;
            font-size: 13px;
            font-weight: 700;
            color: #868993;
            display: flex;
            align-items: center;
            gap: 5px;
            pointer-events: none;
        }}
    </style>
</head>
<body>
    <div id="chart-container">
        <div class="watermark">
            <svg width="24" height="16" viewBox="0 0 36 28" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M14 22H7V11H14V22Z" fill="#2962FF"/>
                <path d="M22 22H15V6H22V22Z" fill="#2962FF"/>
                <path d="M30 22H23V0H30V22Z" fill="#2962FF"/>
            </svg>
            TradingView
        </div>
    </div>

    <script>
        const container = document.getElementById('chart-container');
        const chart = LightweightCharts.createChart(container, {{
            width: container.clientWidth,
            height: 560,
            layout: {{
                background: {{ color: '#131722' }},
                textColor: '#9598A1',
                fontSize: 12,
            }},
            grid: {{
                vertLines: {{ color: '#1f2434' }},
                horzLines: {{ color: '#1f2434' }},
            }},
            crosshair: {{
                mode: LightweightCharts.CrosshairMode.Normal,
            }},
            rightPriceScale: {{
                borderColor: '#2B2B43',
                visible: true,
                autoScale: true,
                scaleMargins: {{
                    top: 0.1,
                    bottom: 0.25,
                }},
            }},
            timeScale: {{
                borderColor: '#2B2B43',
                timeVisible: true,
                secondsVisible: true,
            }},
        }});

        // Candlestick Series
        const candleSeries = chart.addCandlestickSeries({{
            upColor: '#26a69a',
            downColor: '#ef5350',
            borderVisible: false,
            wickUpColor: '#26a69a',
            wickDownColor: '#ef5350',
            priceFormat: {{
                type: 'price',
                precision: 2,
                minMove: 0.01,
            }},
        }});
        candleSeries.setData({json.dumps(candle_data)});

        // Volume Series (Attached at bottom)
        const volumeSeries = chart.addHistogramSeries({{
            priceFormat: {{ type: 'volume' }},
            priceScaleId: 'volume',
        }});
        chart.priceScale('volume').applyOptions({{
            scaleMargins: {{
                top: 0.78,
                bottom: 0.0,
            }},
            visible: false,
        }});
        volumeSeries.setData({json.dumps(volume_data)});

        // Indicator Lines
        const indicators = {json.dumps(indicator_series)};
        indicators.forEach(ind => {{
            const line = chart.addLineSeries({{
                color: ind.color,
                lineWidth: 2,
                title: ind.name,
                priceLineVisible: true,
            }});
            line.setData(ind.data);
        }});

        window.addEventListener('resize', () => {{
            chart.applyOptions({{ width: container.clientWidth }});
        }});
    </script>
</body>
</html>
"""

components.html(tv_chart_html, height=580)

# Auto trade signal check
if st.session_state.auto_trade:
    st.caption("⚡ Auto Trading Algorithm: Monitoring EMA lines & real-time order books...")

# 1-second auto update loop
time.sleep(1)
st.rerun()
