import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime
import time
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests, string
from urllib.parse import quote

st.set_page_config(page_title="IDX Stock Screener", page_icon="📈", layout="wide")

st.title("📈 IDX Stock Screener")
st.markdown("**Filter saham dengan parameter yang dapat disesuaikan: persentase kenaikan, jumlah hari berturut-turut, dan volume perdagangan**")

# --------- DYNAMIC TICKER SOURCES ----------
@st.cache_data(ttl=3600)
def fetch_from_idx():
    """Fetch daftar emiten dari situs IDX (JSON used by the site)."""
    url = "https://www.idx.co.id/umbraco/Surface/ListedCompany/GetListedCompany?emitenType=s"
    try:
        r = requests.get(url, headers={"Referer": "https://www.idx.co.id/"}, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception:
        return [], {}

    tickers, names = [], {}
    if isinstance(data, list):
        for row in data:
            code = str(row.get("KodeEmiten", "")).strip().upper()
            name = (row.get("NamaEmiten") or row.get("NamaPerusahaan") or code).strip()
            if code:
                sym = f"{code}.JK"
                tickers.append(sym)
                names[sym] = name
    return sorted(set(tickers)), names

@st.cache_data(ttl=3600)
def fetch_from_yahoo():
    """Sweep Yahoo autocomplete A–Z & 0–9; keep only .JK / JKT symbols."""
    base = "https://autoc.finance.yahoo.com/autoc?region=1&lang=en&query="
    tickers, names = set(), {}
    for q in list(string.ascii_uppercase) + list(string.digits):
        try:
            r = requests.get(base + quote(q), timeout=10)
            if r.status_code != 200:
                continue
            js = r.json()
            for it in js.get("ResultSet", {}).get("Result", []):
                sym = (it.get("symbol") or "").upper()
                exch = (it.get("exch") or "").upper()
                if sym.endswith(".JK") or exch == "JKT":
                    tickers.add(sym)
                    names[sym] = it.get("name") or sym
        except Exception:
            pass
        time.sleep(0.08)  # be nice to the API
    return sorted(tickers), names

def resolve_tickers(source_mode: str):
    """
    source_mode: 'Auto' (IDX -> Yahoo), 'IDX only', 'Yahoo only'
    returns (symbols_list, symbol_to_name_map)
    """
    if source_mode == "IDX only":
        syms, names = fetch_from_idx()
        return syms, names
    if source_mode == "Yahoo only":
        syms, names = fetch_from_yahoo()
        return syms, names

    # Auto: try IDX first, then Yahoo as fallback
    syms, names = fetch_from_idx()
    if len(syms) >= 200:
        return syms, names
    syms2, names2 = fetch_from_yahoo()
    return syms2, names2

# --------- Utility & indicators (unchanged from your code) ----------
def format_idr(value):
    if pd.isna(value) or value == 0:
        return "Rp 0"
    if value >= 1_000_000_000_000:  # T
        return f"Rp {value/1_000_000_000_000:.2f} T"
    elif value >= 1_000_000_000:     # M (miliar)
        return f"Rp {value/1_000_000_000:.2f} M"
    elif value >= 1_000_000:         # Jt
        return f"Rp {value/1_000_000:.2f} Jt"
    else:
        return f"Rp {value:,.0f}"

@st.cache_data(ttl=600, show_spinner=False)
def get_stock_data(ticker, period="5d"):
    stock = yf.Ticker(ticker)
    hist = stock.history(period=period, auto_adjust=False)
    info = {}
    try:
        info_full = stock.info
        if isinstance(info_full, dict):
            info["longName"] = info_full.get("longName")
    except Exception:
        pass
    return hist, info

def check_consecutive_day_increase(hist, threshold=2.0, num_days=2):
    if hist is None or len(hist) < (num_days + 1):
        return False, [], []
    recent = hist.tail(num_days + 1)
    prices = recent['Close'].values
    changes = [((prices[i + 1] - prices[i]) / prices[i]) * 100 for i in range(len(prices) - 1)]
    if all(ch >= threshold for ch in changes):
        return True, changes, list(prices)
    return False, changes, list(prices)

def calculate_trading_value(hist):
    if hist is None or len(hist) < 1:
        return 0
    recent = hist.tail(1)
    price = float(recent['Close'].values[0])
    volume = float(recent['Volume'].values[0])
    return price * volume

def calculate_rsi(hist, period=14):
    if hist is None or len(hist) < period + 1:
        return None
    prices = hist['Close'].values
    deltas = pd.Series(prices).diff()
    gains = deltas.where(deltas > 0, 0)
    losses = -deltas.where(deltas < 0, 0)
    avg_gain = gains.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = losses.ewm(alpha=1/period, adjust=False).mean()
    lg, ll = avg_gain.iloc[-1], avg_loss.iloc[-1]
    if ll == 0: return 100.0 if lg > 0 else 50.0
    if lg == 0: return 0.0
    rs = lg / ll
    rsi = 100 - (100 / (1 + rs))
    return rsi if not pd.isna(rsi) else None

def calculate_sma(hist, period=20):
    if hist is None or len(hist) < period:
        return None
    sma = hist['Close'].rolling(window=period).mean()
    return sma.iloc[-1] if not pd.isna(sma.iloc[-1]) else None

def calculate_ema(hist, period=20):
    if hist is None or len(hist) < period:
        return None
    ema = hist['Close'].ewm(span=period, adjust=False).mean()
    return ema.iloc[-1] if not pd.isna(ema.iloc[-1]) else None

def calculate_volume_trend(hist, period=5):
    if hist is None or len(hist) < period * 2:
        return None
    volumes = hist['Volume'].values
    recent_avg = sum(volumes[-period:]) / period
    previous_avg = sum(volumes[-period*2:-period]) / period
    if previous_avg == 0:
        return None
    return ((recent_avg - previous_avg) / previous_avg) * 100

def create_stock_chart(ticker, period="3mo", name_map=None):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period=period)
        if hist is None or len(hist) < 1:
            return None
        stock_name = (name_map or {}).get(ticker) or ticker.replace(".JK", "")
        fig = make_subplots(
            rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03,
            subplot_titles=(f'{stock_name} ({ticker.replace(".JK", "")})', 'Volume'),
            row_heights=[0.7, 0.3]
        )
        fig.add_trace(go.Candlestick(
            x=hist.index, open=hist['Open'], high=hist['High'],
            low=hist['Low'], close=hist['Close'], name='Price'
        ), row=1, col=1)
        colors = ['red' if hist['Close'].iloc[i] < hist['Open'].iloc[i] else 'green' for i in range(len(hist))]
        fig.add_trace(go.Bar(x=hist.index, y=hist['Volume'], name='Volume', marker_color=colors), row=2, col=1)
        fig.update_layout(height=600, xaxis_rangeslider_visible=False, showlegend=False, hovermode='x unified')
        fig.update_xaxes(title_text="Tanggal", row=2, col=1)
        fig.update_yaxes(title_text="Harga (IDR)", row=1, col=1)
        fig.update_yaxes(title_text="Volume", row=2, col=1)
        return fig
    except Exception:
        return None

def process_single_stock(ticker, min_trading_value, price_threshold, num_consecutive_days=2, include_indicators=False, name_map=None):
    try:
        period = "3mo" if include_indicators else "5d"
        hist, info = get_stock_data(ticker, period=period)
        if hist is not None and len(hist) >= (num_consecutive_days + 1):
            ok, changes, prices = check_consecutive_day_increase(hist, price_threshold, num_consecutive_days)
            if ok:
                tv = calculate_trading_value(hist)
                if tv >= min_trading_value:
                    code = ticker.replace(".JK", "")
                    name = (name_map or {}).get(ticker) or info.get('longName') or code
                    row = {
                        'Kode': code,
                        'Nama': name,
                        'Harga Sekarang': prices[-1],
                        'Nilai Transaksi Harian': tv,
                        'Nilai Transaksi (Format)': format_idr(tv),
                    }
                    for i, ch in enumerate(changes):
                        row[f"Kenaikan Hari -{len(changes)-i}"] = f"{ch:.2f}%"
                    if include_indicators:
                        rsi = calculate_rsi(hist)
                        sma20 = calculate_sma(hist, 20)
                        ema20 = calculate_ema(hist, 20)
                        vtrend = calculate_volume_trend(hist)
                        row['RSI (14)'] = f"{rsi:.2f}" if rsi is not None else "N/A"
                        row['SMA (20)'] = f"{sma20:.2f}" if sma20 is not None else "N/A"
                        row['EMA (20)'] = f"{ema20:.2f}" if ema20 is not None else "N/A"
                        row['Volume Trend (%)'] = f"{vtrend:.2f}" if vtrend is not None else "N/A"
                    return {'success': True, 'data': row}
        return {'success': True, 'data': None}
    except Exception as e:
        return {'success': False, 'error': str(e), 'ticker': ticker}

def scan_stocks_with_progress(tickers, min_trading_value=15_000_000_000, price_threshold=2.0, num_consecutive_days=2, include_indicators=False, name_map=None):
    filtered, failed = [], []
    progress_bar = st.progress(0)
    status_text = st.empty()
    total = len(tickers)
    for idx, t in enumerate(tickers):
        status_text.text(f"Scanning {t}... ({idx+1}/{total})")
        res = process_single_stock(t, min_trading_value, price_threshold, num_consecutive_days, include_indicators, name_map)
        if res['success']:
            if res['data'] is not None:
                filtered.append(res['data'])
        else:
            failed.append({'ticker': res['ticker'], 'error': res['error']})
        if (idx + 1) % 50 == 0:
            time.sleep(1.0)  # throttle politely
        progress_bar.progress((idx + 1) / max(total, 1))
    progress_bar.empty()
    status_text.empty()
    if failed:
        with st.expander(f"⚠️ {len(failed)} saham gagal dimuat (klik untuk detail)", expanded=False):
            st.dataframe(pd.DataFrame(failed), use_container_width=True, hide_index=True)
    return pd.DataFrame(filtered), failed

# --------- Sidebar controls ----------
st.sidebar.header("⚙️ Pengaturan Filter")

source_mode = st.sidebar.radio(
    "Sumber Daftar Emiten",
    options=["Auto", "IDX only", "Yahoo only"],
    help="Auto: coba IDX dulu, jika gagal pakai Yahoo."
)

if st.sidebar.button("🔄 Refresh Daftar Emiten"):
    fetch_from_idx.clear()
    fetch_from_yahoo.clear()
    st.sidebar.success("Cache dibersihkan. Daftar akan diambil ulang.")

with st.spinner("Mengambil daftar emiten..."):
    SYMBOLS, NAME_MAP = resolve_tickers(source_mode)

min_trading_value = st.sidebar.number_input(
    "Nilai Transaksi Minimum (Miliar Rp)",
    min_value=1.0, max_value=100.0, value=15.0, step=1.0,
    help="Masukkan nilai dalam miliar rupiah"
)
price_threshold = st.sidebar.number_input(
    "Threshold Kenaikan Harga (%)",
    min_value=0.5, max_value=10.0, value=2.0, step=0.5,
    help="Persentase kenaikan minimum per hari"
)
num_consecutive_days = st.sidebar.number_input(
    "Jumlah Hari Berturut-turut",
    min_value=2, max_value=5, value=2, step=1,
    help="Jumlah hari berturut-turut yang harus naik"
)

st.sidebar.markdown("---")
st.sidebar.markdown("### 📊 Indikator Teknikal")
include_indicators = st.sidebar.checkbox(
    "Tampilkan Indikator Teknikal",
    value=False,
    help="Menampilkan RSI, SMA, EMA, dan Volume Trend (membutuhkan waktu scan lebih lama)"
)
if include_indicators:
    st.sidebar.info("⚠️ Indikator teknikal membutuhkan data 3 bulan dan waktu scan lebih lama")

# Info box
st.sidebar.markdown("---")
st.sidebar.markdown("### 📊 Informasi")
st.sidebar.markdown(f"**Total Saham Terdeteksi:** {len(SYMBOLS)}")
if 'last_scan' in st.session_state:
    st.sidebar.markdown(f"**Scan Terakhir:** {st.session_state['last_scan'].strftime('%H:%M:%S')}")

# --------- Main actions ----------
st.markdown("---")

min_trading_value_actual = int(min_trading_value * 1_000_000_000)

if st.sidebar.button("🔍 Scan Saham", type="primary"):
    st.session_state['last_scan'] = datetime.now()
    results, errors = scan_stocks_with_progress(
        SYMBOLS, min_trading_value_actual, price_threshold, num_consecutive_days, include_indicators, NAME_MAP
    )
    st.session_state['results'] = results
    st.session_state['errors'] = errors

auto_refresh = st.sidebar.checkbox("Auto Refresh (5 menit)", value=False)
if auto_refresh:
    st.sidebar.info("Data akan di-refresh otomatis setiap 5 menit")

# --------- Results table & charts (unchanged) ----------
if 'results' in st.session_state and not st.session_state['results'].empty:
    df = st.session_state['results']
    st.success(f"✅ Ditemukan {len(df)} saham yang memenuhi kriteria!")
    base_cols = ['Kode', 'Nama', 'Harga Sekarang']
    change_cols = sorted([c for c in df.columns if c.startswith('Kenaikan Hari')], reverse=True)
    display_cols = base_cols + change_cols + ['Nilai Transaksi (Format)']
    if 'RSI (14)' in df.columns:
        display_cols += ['RSI (14)', 'SMA (20)', 'EMA (20)', 'Volume Trend (%)']
    display_df = df[display_cols].rename(columns={'Nilai Transaksi (Format)': 'Nilai Transaksi Harian'})
    st.dataframe(display_df, use_container_width=True, hide_index=True)

    csv = df.to_csv(index=False)
    st.download_button(
        label="📥 Download Data (CSV)",
        data=csv,
        file_name=f"idx_screener_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
    )

    st.markdown("---")
    st.markdown("### 📊 Grafik Harga Saham")
    st.markdown("Klik pada saham untuk melihat grafik harga historis")

    cols_per_row = 2
    rows = (len(df) + cols_per_row - 1) // cols_per_row
    for r in range(rows):
        cols = st.columns(cols_per_row)
        for c in range(cols_per_row):
            i = r * cols_per_row + c
            if i < len(df):
                row = df.iloc[i]
                code = row['Kode']
                name = row['Nama']
                tkr = f"{code}.JK"
                with cols[c]:
                    with st.expander(f"📈 {code} - {name}"):
                        with st.spinner(f"Memuat grafik {code}..."):
                            fig = create_stock_chart(tkr, name_map=NAME_MAP)
                            if fig:
                                st.plotly_chart(fig, use_container_width=True)
                            else:
                                st.error("Gagal memuat grafik untuk saham ini")
elif 'results' in st.session_state and st.session_state['results'].empty:
    st.warning("⚠️ Tidak ada saham yang memenuhi kriteria pada scan terakhir.")
else:
    st.info("👈 Pilih sumber daftar emiten lalu klik 'Scan Saham' untuk memulai.")

# Auto-refresh
if auto_refresh and 'last_scan' in st.session_state:
    if (datetime.now() - st.session_state['last_scan']).total_seconds() >= 300:
        st.rerun()

# Footer
st.markdown("---")
st.markdown(
    """
    <div style='text-align: center; color: #666;'>
        <small>Daftar emiten: IDX / Yahoo Finance • Data harga: Yahoo Finance • Update setiap 5 menit (jika auto-refresh aktif)</small>
    </div>
    """,
    unsafe_allow_html=True
)
