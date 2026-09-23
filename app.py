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

st.set_page_config(page_title="Delta Live WebUI Trader", page_icon="📈", layout="wide")

# Session State Setup
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
    start_time = end_time - (3600 * 3)  # Last 3 hours
    url = f"{DELTA_BASE_URL}/v2/chart/history?symbol={symbol}&resolution={resolution}&start={start_time}&end={end_time}"
    try:
        res = requests.get(url, timeout=3).json()
        if res.get("success") and res.get("result"):
            df = pd.DataFrame(res["result"])
            df = df.rename(columns={"t": "time", "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
            df = df.sort_values("time").drop_duplicates(subset=["time"])
            return df[["time", "open", "high", "low", "close", "volume"]]
    except Exception:
        pass

    # Simulation fallback with strictly ordered Unix timestamps (seconds)
    now = int(time.time()) - 60
    base_time = now - (100 * 60)
    times = [base_time + (i * 60) for i in range(100)]
    
    np.random.seed(42)
    noise = np.cumsum(np.random.randn(100) * 2.0)
    base_price = 2675.0 + noise

    opens = base_price
    highs = base_price + np.random.uniform(0.5, 4.0, 100)
    lows = base_price - np.random.uniform(0.5, 4.0, 100)
    closes = base_price + np.random.uniform(-2.0, 2.0, 100)
    vols = np.random.randint(100, 1800, 100)

    return pd.DataFrame({
        "time": times,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": vols
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
c4.metric("Last Sync", datetime.now().strftime("%H:%M:%S"))

# Data Preparation
df = fetch_candles(symbol)

# Format Candlestick & Volume Data
candle_data = []
volume_data = []
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

# Format Indicators
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

candle_json = json.dumps(candle_data)
volume_json = json.dumps(volume_data)
indicators_json = json.dumps(indicator_series)

# HTML/JS with Pinned Lightweight-Charts Version 4.1.1
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
            background: rgba(19, 23, 34, 0.7);
            padding: 4px 8px;
            border-radius: 4px;
        }}
        .legend-item {{
            display: flex;
            align-items: center;
            gap: 4px;
        }}
    </style>
</head>
<body>
    <div id="chart-wrapper">
        <div class="legend" id="legend">
            <span style="color: #2962FF;">{symbol}</span>
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

        // Candlestick Series
        const candleSeries = chart.addCandlestickSeries({{
            upColor: '#26a69a',
            downColor: '#ef5350',
            borderVisible: false,
            wickUpColor: '#26a69a',
            wickDownColor: '#ef5350',
        }});
        candleSeries.setData({candle_json});

        // Volume Series
        const volumeSeries = chart.addHistogramSeries({{
            priceFormat: {{ type: 'volume' }},
            priceScaleId: 'vol_scale',
        }});
        chart.priceScale('vol_scale').applyOptions({{
            scaleMargins: {{
                top: 0.8,
                bottom: 0.0,
            }},
            visible: false,
        }});
        volumeSeries.setData({volume_json});

        // Dynamic Indicators
        const indicators = {indicators_json};
        const legend = document.getElementById('legend');
        
        indicators.forEach(ind => {{
            const lineSeries = chart.addLineSeries({{
                color: ind.color,
                lineWidth: 2,
                priceLineVisible: false,
            }});
            lineSeries.setData(ind.data);

            const item = document.createElement('div');
            item.className = 'legend-item';
            item.innerHTML = `<span style="color:${{ind.color}};">■</span> ${{ind.name}}`;
            legend.appendChild(item);
        }});

        chart.timeScale().fitContent();

        // Responsive Resizing
        window.addEventListener('resize', () => {{
            chart.applyOptions({{ width: chartElement.clientWidth }});
        }});
    </script>
</body>
</html>
"""

components.html(tv_chart_html, height=580)

# Stable auto-refresh interval (2 seconds)
time.sleep(2)
st.rerun()
