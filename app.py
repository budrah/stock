import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import time
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import string
from urllib.parse import quote

st.set_page_config(page_title="IDX Stock Screener", page_icon="📈", layout="wide")

st.title("📈 IDX Stock Screener")
st.markdown("**Filter saham dengan parameter yang dapat disesuaikan: persentase kenaikan, jumlah hari berturut-turut, dan volume perdagangan**")

# ---------- Helpers to build a COMPLETE IDX ticker list ----------
STATIC_FALLBACK = [
    "BBCA.JK","BBRI.JK","BMRI.JK","BBNI.JK","TLKM.JK","ASII.JK","UNVR.JK","HMSP.JK","ICBP.JK","KLBF.JK",
    "INDF.JK","GGRM.JK","SMGR.JK","UNTR.JK","ADRO.JK","PTBA.JK","INCO.JK","ANTM.JK","ITMG.JK","TINS.JK",
    "CPIN.JK","JPFA.JK","MNCN.JK","SCMA.JK","EXCL.JK","PGAS.JK","JSMR.JK","WIKA.JK","PTPP.JK","WSKT.JK",
    "AKRA.JK","MAPI.JK","LPPF.JK","ACES.JK","ITMG.JK","MEDC.JK","BSDE.JK","PWON.JK","CTRA.JK","SMRA.JK",
    "ERAA.JK","ESSA.JK","SRIL.JK","INTP.JK","WSBP.JK","TBIG.JK","TPIA.JK","SMBR.JK","AMRT.JK","MYOR.JK",
    "ROTI.JK","STTP.JK","ULTJ.JK","BYAN.JK","HRUM.JK","ELSA.JK","SIDO.JK","KAEF.JK","DVLA.JK","PYFA.JK",
    "TOWR.JK","ISAT.JK","FREN.JK","LINK.JK","BRPT.JK","AALI.JK","LSIP.JK","SIMP.JK","TAPG.JK","SMAR.JK",
    "BBTN.JK","BJBR.JK","BRIS.JK","NISP.JK","PNBN.JK","MEGA.JK","BDMN.JK","BNLI.JK","BNGA.JK","BTPS.JK",
]

def _safe_get_json(url, headers=None, timeout=15):
    try:
        r = requests.get(url, headers=headers or {}, timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None

@st.cache_data(ttl=3600)
def fetch_from_idx():
    """
    Try to fetch the official listed company directory from IDX.
    This endpoint is used by their site (Umbraco surface controller).
    """
    # Known public endpoint historically used by IDX site (may change over time).
    # If this 404s in the future, the app will fall back to Yahoo sweep.
    idx_url = "https://www.idx.co.id/umbraco/Surface/ListedCompany/GetListedCompany?emitenType=s"
    data = _safe_get_json(idx_url, headers={"Referer": "https://www.idx.co.id/"})
    tickers = []
    names = {}
    if isinstance(data, list) and data:
        # Common keys seen: 'KodeEmiten' (ticker w/o .JK), 'NamaEmiten'
        for row in data:
            code = str(row.get("KodeEmiten", "")).strip().upper()
            name = (row.get("NamaEmiten") or row.get("NamaPerusahaan") or "").strip()
            if code and code.isalnum():  # avoid odd entries like '-' etc.
                sym = f"{code}.JK"
                tickers.append(sym)
                names[sym] = name if name else code
    return sorted(set(tickers)), names

@st.cache_data(ttl=3600)
def fetch_from_yahoo_autocomplete():
    """
    Sweep Yahoo autocomplete A-Z and 0-9, keeping only JKT/IDX symbols (.JK).
    """
    base = "https://autoc.finance.yahoo.com/autoc?region=1&lang=en&query="
    queries = list(string.ascii_uppercase) + list(string.digits)
    tickers = set()
    names = {}
    for q in queries:
        url = base + quote(q)
        try:
            r = requests.get(url, timeout=10)
            if r.status_code != 200:
                continue
            js = r.json()
            for it in js.get("ResultSet", {}).get("Result", []):
                sym = it.get("symbol", "")
                exch = (it.get("exch") or "").upper()
                name = it.get("name") or sym
                # Yahoo commonly marks Jakarta as "JKT" (and symbols end with .JK)
                if sym.endswith(".JK") or exch == "JKT":
                    tickers.add(sym.upper())
                    names[sym.upper()] = name
        except Exception:
            continue
        # be nice to the API
        time.sleep(0.08)
    # Some symbols may be warrants/bonds/rights; keep them all so users can filter later if desired.
    return sorted(tickers), names

@st.cache_data(ttl=3600)
def fetch_all_idx_tickers():
    # 1) Try IDX official JSON
    t1, n1 = fetch_from_idx()
    if len(t1) >= 200:  # IDX usually lists 800+; but even 200+ is already better than 80
        return t1, n1

    # 2) Fallback to Yahoo autocomplete sweep
    t2, n2 = fetch_from_yahoo_autocomplete()
    if len(t2) >= 200:
        return t2, n2

    # 3) Final fallback: static list
    names = {s: s.replace(".JK", "") for s in STATIC_FALLBACK}
    return STATIC_FALLBACK, names

# --------- Currency / indicator helpers ---------
def format_idr(value):
    if pd.isna(value) or value == 0:
        return "Rp 0"
    if value >= 1_000_000_000_000:
        return f"Rp {value/1_000_000_000_000:.2f} T"
    elif value >= 1_000_000_000:
        return f"Rp {value/1_000_000_000:.2f} M"
    elif value >= 1_000_000:
        return f"Rp {value/1_000_000:.2f} Jt"
    else:
        return f"Rp {value:,.0f}"

@st.cache_data(ttl=600, show_spinner=False)
def get_stock_data(ticker, period="5d"):
    stock = yf.Ticker(ticker)
    hist = stock.history(period=period, auto_adjust=False)
    # prefer fast_info for speed if available; fall back to .info
    info = {}
    try:
        fi = getattr(stock, "fast_info", None)
        if fi:
            info["longName"] = fi.get("long_name") or None
    except Exception:
        pass
    if not info.get("longName"):
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
    if len(recent) < (num_days + 1):
        return False, [], []
    prices = recent['Close'].values
    changes = [((prices[i + 1] - prices[i]) / prices[i]) * 100 for i in range(len(prices) - 1)]
    all_meet = all(change >= threshold for change in changes)
    if all_meet:
        return True, changes, list(prices)
    return False, changes, list(prices)

def calculate_trading_value(hist):
    if hist is None or len(hist) < 1:
        return 0
    recent = hist.tail(1)
    if len(recent) < 1:
        return 0
    price = recent['Close'].values[0]
    volume = recent['Volume'].values[0]
    return float(price) * float(volume)

def calculate_rsi(hist, period=14):
    if hist is None or len(hist) < period + 1:
        return None
    prices = hist['Close'].values
    deltas = pd.Series(prices).diff()
    gains = deltas.where(deltas > 0, 0)
    losses = -deltas.where(deltas < 0, 0)
    avg_gain = gains.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = losses.ewm(alpha=1/period, adjust=False).mean()
    latest_gain = avg_gain.iloc[-1]
    latest_loss = avg_loss.iloc[-1]
    if latest_loss == 0:
        return 100.0 if latest_gain > 0 else 50.0
    if latest_gain == 0:
        return 0.0
    rs = latest_gain / latest_loss
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
    trend_pct = ((recent_avg - previous_avg) / previous_avg) * 100
    return trend_pct

def create_stock_chart(ticker, period="3mo"):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period=period)
        # Prefer name from our cached mapping if available
        stock_name = SYMBOL_NAME_MAP.get(ticker) or ticker.replace(".JK", "")
        if hist is None or len(hist) < 1:
            return None
        fig = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.03,
            subplot_titles=(f'{stock_name} ({ticker.replace(".JK", "")})', 'Volume'),
            row_heights=[0.7, 0.3]
        )
        fig.add_trace(
            go.Candlestick(
                x=hist.index,
                open=hist['Open'],
                high=hist['High'],
                low=hist['Low'],
                close=hist['Close'],
                name='Price'
            ),
            row=1, col=1
        )
        colors = ['red' if hist['Close'].iloc[i] < hist['Open'].iloc[i] else 'green'
                  for i in range(len(hist))]
        fig.add_trace(
            go.Bar(x=hist.index, y=hist['Volume'], name='Volume', marker_color=colors),
            row=2, col=1
        )
        fig.update_layout(height=600, xaxis_rangeslider_visible=False, showlegend=False, hovermode='x unified')
        fig.update_xaxes(title_text="Tanggal", row=2, col=1)
        fig.update_yaxes(title_text="Harga (IDR)", row=1, col=1)
        fig.update_yaxes(title_text="Volume", row=2, col=1)
        return fig
    except Exception:
        return None

def process_single_stock(ticker, min_trading_value, price_threshold, num_consecutive_days=2, include_indicators=False):
    try:
        period = "3mo" if include_indicators else "5d"
        hist, info = get_stock_data(ticker, period=period)
        if hist is not None and len(hist) >= (num_consecutive_days + 1):
            meets_criteria, changes, prices = check_consecutive_day_increase(hist, price_threshold, num_consecutive_days)
            if meets_criteria:
                trading_value = calculate_trading_value(hist)
                if trading_value >= min_trading_value:
                    stock_code = ticker.replace(".JK", "")
                    # Prefer cached name first, then Yahoo info, then code
                    stock_name = SYMBOL_NAME_MAP.get(ticker) or info.get('longName') or stock_code
                    data_dict = {
                        'Kode': stock_code,
                        'Nama': stock_name,
                        'Harga Sekarang': prices[-1],
                        'Nilai Transaksi Harian': trading_value,
                        'Nilai Transaksi (Format)': format_idr(trading_value),
                    }
                    for i, change in enumerate(changes):
                        day_label = f"Kenaikan Hari -{len(changes) - i}"
                        data_dict[day_label] = f"{change:.2f}%"
                    if include_indicators:
                        rsi = calculate_rsi(hist)
                        sma_20 = calculate_sma(hist, 20)
                        ema_20 = calculate_ema(hist, 20)
                        volume_trend = calculate_volume_trend(hist)
                        data_dict['RSI (14)'] = f"{rsi:.2f}" if rsi is not None else "N/A"
                        data_dict['SMA (20)'] = f"{sma_20:.2f}" if sma_20 is not None else "N/A"
                        data_dict['EMA (20)'] = f"{ema_20:.2f}" if ema_20 is not None else "N/A"
                        data_dict['Volume Trend (%)'] = f"{volume_trend:.2f}" if volume_trend is not None else "N/A"
                    return {'success': True, 'data': data_dict}
        return {'success': True, 'data': None}
    except Exception as e:
        return {'success': False, 'error': str(e), 'ticker': ticker}

def scan_stocks_with_progress(tickers, min_trading_value=15_000_000_000, price_threshold=2.0, num_consecutive_days=2, include_indicators=False):
    filtered_stocks = []
    failed_tickers = []
    progress_bar = st.progress(0)
    status_text = st.empty()
    total_stocks = len(tickers)
    for idx, ticker in enumerate(tickers):
        status_text.text(f"Scanning {ticker}... ({idx+1}/{total_stocks})")
        result = process_single_stock(ticker, min_trading_value, price_threshold, num_consecutive_days, include_indicators)
        if result['success']:
            if result['data'] is not None:
                filtered_stocks.append(result['data'])
        else:
            failed_tickers.append({'ticker': result['ticker'], 'error': result['error']})
        # light throttling to be polite to Yahoo
        if (idx + 1) % 50 == 0:
            time.sleep(1.0)
        progress_bar.progress((idx + 1) / max(total_stocks, 1))
    progress_bar.empty()
    status_text.empty()
    if failed_tickers:
        with st.expander(f"⚠️ {len(failed_tickers)} saham gagal dimuat (klik untuk detail)", expanded=False):
            error_df = pd.DataFrame(failed_tickers)
            st.dataframe(error_df, use_container_width=True, hide_index=True)
    return pd.DataFrame(filtered_stocks), failed_tickers

# ---------- Build the live ticker universe ----------
with st.spinner("Mengambil daftar lengkap emiten IDX..."):
    SYMBOLS, SYMBOL_NAME_MAP = fetch_all_idx_tickers()
    st.session_state["SYMBOLS"] = SYMBOLS
    st.session_state["SYMBOL_NAME_MAP"] = SYMBOL_NAME_MAP

# Sidebar for filters
st.sidebar.header("⚙️ Pengaturan Filter")

if st.sidebar.button("🔄 Refresh Daftar Emiten"):
    fetch_from_idx.clear()
    fetch_from_yahoo_autocomplete.clear()
    fetch_all_idx_tickers.clear()
    with st.spinner("Merefresh daftar emiten..."):
        SYMBOLS, SYMBOL_NAME_MAP = fetch_all_idx_tickers()
        st.session_state["SYMBOLS"] = SYMBOLS
        st.session_state["SYMBOL_NAME_MAP"] = SYMBOL_NAME_MAP
    st.sidebar.success("Daftar emiten berhasil diperbarui!")

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

min_trading_value_actual = int(min_trading_value * 1_000_000_000)

# Scan button
if st.sidebar.button("🔍 Scan Saham", type="primary"):
    st.session_state['last_scan'] = datetime.now()
    results, errors = scan_stocks_with_progress(
        st.session_state.get("SYMBOLS", STATIC_FALLBACK),
        min_trading_value_actual, price_threshold, num_consecutive_days, include_indicators
    )
    st.session_state['results'] = results
    st.session_state['errors'] = errors

# Auto-refresh option
auto_refresh = st.sidebar.checkbox("Auto Refresh (5 menit)", value=False)
if auto_refresh:
    st.sidebar.info("Data akan di-refresh otomatis setiap 5 menit")

# Sidebar info
st.sidebar.markdown("---")
st.sidebar.markdown("### 📊 Informasi")
st.sidebar.markdown(f"**Total Saham Terdeteksi:** {len(st.session_state.get('SYMBOLS', []))}")
if 'last_scan' in st.session_state:
    st.sidebar.markdown(f"**Scan Terakhir:** {st.session_state['last_scan'].strftime('%H:%M:%S')}")

# Main content
st.markdown("---")

# Display results
if 'results' in st.session_state and not st.session_state['results'].empty:
    df = st.session_state['results']
    st.success(f"✅ Ditemukan {len(df)} saham yang memenuhi kriteria!")
    base_columns = ['Kode', 'Nama', 'Harga Sekarang']
    change_columns = [col for col in df.columns if col.startswith('Kenaikan Hari')]
    change_columns.sort(reverse=True)
    display_columns = base_columns + change_columns + ['Nilai Transaksi (Format)']
    indicator_columns = []
    if 'RSI (14)' in df.columns:
        indicator_columns = ['RSI (14)', 'SMA (20)', 'EMA (20)', 'Volume Trend (%)']
        display_columns += indicator_columns
    display_df = df[display_columns].rename(columns={'Nilai Transaksi (Format)': 'Nilai Transaksi Harian'})
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
    for row_idx in range(rows):
        cols = st.columns(cols_per_row)
        for col_idx in range(cols_per_row):
            stock_idx = row_idx * cols_per_row + col_idx
            if stock_idx < len(df):
                stock_row = df.iloc[stock_idx]
                stock_code = stock_row['Kode']
                stock_name = stock_row['Nama']
                ticker = f"{stock_code}.JK"
                with cols[col_idx]:
                    with st.expander(f"📈 {stock_code} - {stock_name}"):
                        with st.spinner(f"Memuat grafik {stock_code}..."):
                            chart = create_stock_chart(ticker)
                            if chart:
                                st.plotly_chart(chart, use_container_width=True)
                            else:
                                st.error("Gagal memuat grafik untuk saham ini")
elif 'results' in st.session_state and st.session_state['results'].empty:
    st.warning("⚠️ Tidak ada saham yang memenuhi kriteria pada scan terakhir.")
else:
    st.info("👈 Klik tombol 'Scan Saham' di sidebar untuk memulai pencarian.")

# Auto-refresh logic
if auto_refresh and 'last_scan' in st.session_state:
    time_since_scan = (datetime.now() - st.session_state['last_scan']).total_seconds()
    if time_since_scan >= 300:  # 5 minutes
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
