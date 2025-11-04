import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime
import time, requests, string, io
from urllib.parse import quote

st.set_page_config(page_title="IDX Stock Screener", page_icon="📈", layout="wide")

st.title("📈 IDX Stock Screener")
st.markdown("**Filter saham: % kenaikan, jumlah hari berturut-turut, dan volume perdagangan**")

# ---------- Small static fallback (agar tak pernah 0) ----------
STATIC_FALLBACK = [
    "BBCA.JK","BBRI.JK","BMRI.JK","BBNI.JK","TLKM.JK","ASII.JK","UNVR.JK","HMSP.JK","ICBP.JK","KLBF.JK",
    "INDF.JK","GGRM.JK","UNTR.JK","ADRO.JK","PTBA.JK","ANTM.JK","TOWR.JK","ISAT.JK","EXCL.JK","PGAS.JK"
]

# ---------- Helpers ----------
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

def _try_get_json(url, params=None, headers=None, timeout=15):
    try:
        r = requests.get(url, params=params or {}, headers=headers or {}, timeout=timeout)
        r.raise_for_status()
        return r.json(), None
    except Exception as e:
        return None, str(e)

def _clean_to_jk_symbol(s: str) -> str:
    s = (s or "").strip().upper()
    if not s:
        return ""
    if s.endswith(".JK"):
        return s
    # buang spasi/komentar
    s = s.split()[0].strip()
    # buang tanda baca umum
    s = s.replace(",", "").replace(";", "").replace(".", "")
    if not s:
        return ""
    return s + ".JK"

# ---------- Yahoo search (lebih stabil) ----------
YA_SEARCH = "https://query2.finance.yahoo.com/v1/finance/search"
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

@st.cache_data(ttl=3600)
def fetch_from_yahoo_search_verbose():
    tickers = {}
    errors = []
    queries = list(string.ascii_uppercase) + list(string.digits)

    for q in queries:
        js, err = _try_get_json(
            YA_SEARCH,
            params={"q": q, "quotesCount": 1000, "newsCount": 0, "lang": "en-US", "region": "US"},
            headers=BROWSER_HEADERS,
            timeout=12
        )
        if err or not js:
            errors.append(f"Yahoo {q}: {err or 'no data'}")
            time.sleep(0.05)
            continue

        for it in (js.get("quotes") or []):
            sym = (it.get("symbol") or "").upper()
            exch = (it.get("exchange") or it.get("exch") or "").upper()
            exch_disp = (it.get("exchDisp") or it.get("exchangeDisp") or "").lower()
            name = it.get("shortname") or it.get("longname") or it.get("name") or sym
            if sym.endswith(".JK") or exch in {"JKT", "JAKARTA", "IDX"} or "jakarta" in exch_disp:
                tickers[sym] = name
        time.sleep(0.08)

    # light cleaning
    cleaned = {}
    for sym, name in tickers.items():
        bad_suffix = any(suf in sym for suf in ["-W", "-R", "-B", "-TB", "-F", "-P", "-S", "-Q"])
        if bad_suffix:
            continue
        if len(sym) <= 3:
            continue
        cleaned[sym] = name

    final_map = cleaned if cleaned else tickers
    return sorted(final_map.keys()), final_map, errors

# ---------- IDX fetch (kadang 403/blocked di Replit) ----------
@st.cache_data(ttl=3600)
def fetch_from_idx_verbose():
    url = "https://www.idx.co.id/umbraco/Surface/ListedCompany/GetListedCompany?emitenType=s"
    js, err = _try_get_json(url, headers={"Referer": "https://www.idx.co.id/"}, timeout=15)
    if err or not isinstance(js, list):
        return [], {}, [f"IDX: {err or 'no data/list'}"]
    syms, names = [], {}
    for row in js:
        code = str(row.get("KodeEmiten") or "").strip().upper()
        name = (row.get("NamaEmiten") or row.get("NamaPerusahaan") or code).strip()
        if code and code.isalnum():
            sym = f"{code}.JK"
            syms.append(sym); names[sym] = name
    syms = sorted(set(syms))
    return syms, names, []

# ---------- Manual (Upload/Tempel) ----------
def fetch_from_manual(text_value: str, uploaded_file) -> tuple[list, dict]:
    symbols = []
    if uploaded_file is not None:
        try:
            if uploaded_file.name.lower().endswith(".csv"):
                df = pd.read_csv(uploaded_file)
            else:
                df = pd.read_excel(uploaded_file)
            # cari kolom yang memuat kode (heuristik sederhana)
            candidate_cols = [c for c in df.columns if "code" in c.lower() or "ticker" in c.lower() or "symbol" in c.lower() or "kode" in c.lower()]
            if not candidate_cols:
                candidate_cols = [df.columns[0]]
            codes = df[candidate_cols[0]].astype(str).tolist()
            symbols.extend([_clean_to_jk_symbol(c) for c in codes])
        except Exception:
            pass
    # gabung teks manual
    if text_value:
        lines = [ln.strip() for ln in text_value.splitlines() if ln.strip()]
        symbols.extend([_clean_to_jk_symbol(ln) for ln in lines])
    # bersihkan
    symbols = sorted({s for s in symbols if s.endswith(".JK") and len(s) >= 5})
    name_map = {s: s.replace(".JK", "") for s in symbols}
    return symbols, name_map

# ---------- Resolve universe ----------
def resolve_universe(mode: str, manual_text: str = "", manual_file=None):
    debug_msgs = []
    if mode == "Yahoo only":
        syms, names, errs = fetch_from_yahoo_search_verbose()
        debug_msgs.extend(errs)
        if not syms:
            debug_msgs.append("Yahoo empty → fallback STATIC")
            return STATIC_FALLBACK, {s: s.replace(".JK", "") for s in STATIC_FALLBACK}, debug_msgs
        return syms, names, debug_msgs

    if mode == "IDX only":
        syms, names, errs = fetch_from_idx_verbose()
        debug_msgs.extend(errs)
        if not syms:
            debug_msgs.append("IDX empty → fallback STATIC")
            return STATIC_FALLBACK, {s: s.replace(".JK", "") for s in STATIC_FALLBACK}, debug_msgs
        return syms, names, debug_msgs

    if mode == "Manual":
        syms, names = fetch_from_manual(manual_text, manual_file)
        if not syms:
            debug_msgs.append("Manual empty → fallback STATIC")
            return STATIC_FALLBACK, {s: s.replace(".JK", "") for s in STATIC_FALLBACK}, debug_msgs
        return syms, names, debug_msgs

    # Auto: Yahoo → IDX → STATIC
    syms, names, errs = fetch_from_yahoo_search_verbose()
    debug_msgs.extend(errs)
    if syms:
        return syms, names, debug_msgs
    syms2, names2, errs2 = fetch_from_idx_verbose()
    debug_msgs.extend(errs2)
    if syms2:
        return syms2, names2, debug_msgs
    debug_msgs.append("Auto empty → fallback STATIC")
    return STATIC_FALLBACK, {s: s.replace(".JK", "") for s in STATIC_FALLBACK}, debug_msgs

# ---------- Data & indicators ----------
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
    r = hist.tail(1)
    return float(r['Close'].values[0]) * float(r['Volume'].values[0])

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
        from plotly.subplots import make_subplots
        import plotly.graph_objects as go
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
    progress_bar = st.progress(0); status_text = st.empty()
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
            time.sleep(1.0)
        progress_bar.progress((idx + 1) / max(total, 1))
    progress_bar.empty(); status_text.empty()
    if failed:
        with st.expander(f"⚠️ {len(failed)} saham gagal dimuat (klik untuk detail)", expanded=False):
            st.dataframe(pd.DataFrame(failed), use_container_width=True, hide_index=True)
    return pd.DataFrame(filtered), failed

# ---------- Sidebar Controls ----------
st.sidebar.header("⚙️ Sumber Daftar Emiten")
source_mode = st.sidebar.radio(
    "Sumber",
    options=["Auto", "Yahoo only", "IDX only", "Manual"],
    help="Kalau Replit memblokir API, pakai 'Manual' lalu tempel/upload daftar kode."
)

manual_text = ""
manual_file = None
if source_mode == "Manual":
    manual_file = st.sidebar.file_uploader("Upload CSV/XLSX (kolom ticker/kode/symbol)", type=["csv", "xlsx"])
    manual_text = st.sidebar.text_area("Atau tempel kode (1 per baris)", height=120, placeholder="BBCA\nBBRI\nBMRI\n...")

if st.sidebar.button("🔄 Clear Cache (fetch ulang)"):
    fetch_from_yahoo_search_verbose.clear()
    fetch_from_idx_verbose.clear()
    st.sidebar.success("Cache dihapus, daftar akan diambil ulang.")

with st.spinner("Mengambil daftar emiten..."):
    SYMBOLS, NAME_MAP, DEBUG_MSGS = resolve_universe(source_mode, manual_text, manual_file)

# ---------- Debug panel ----------
with st.expander("🔎 Debug koneksi & daftar emiten (opsional)"):
    st.write(f"Total terdeteksi: **{len(SYMBOLS)}**")
    if DEBUG_MSGS:
        st.write("Log sumber:")
        for m in DEBUG_MSGS[:20]:
            st.write("•", m)
    # quick connectivity test to Yahoo price for BBCA.JK
    try:
        _h = yf.Ticker("BBCA.JK").history(period="5d")
        st.write(f"Tes harga BBCA.JK: rows={len(_h)} (>=1 artinya koneksi harga OK)")
    except Exception as e:
        st.write(f"Tes harga BBCA.JK gagal: {e}")
    if SYMBOLS:
        st.dataframe(pd.DataFrame({
            "Symbol": SYMBOLS[:50],
            "Name": [NAME_MAP.get(s, s.replace('.JK','')) for s in SYMBOLS[:50]]
        }), use_container_width=True, hide_index=True)

# ---------- Filter Screener ----------
st.sidebar.header("⚙️ Pengaturan Filter")
min_trading_value = st.sidebar.number_input("Nilai Transaksi Minimum (Miliar Rp)", min_value=1.0, max_value=100.0, value=15.0, step=1.0)
price_threshold = st.sidebar.number_input("Threshold Kenaikan Harga (%)", min_value=0.5, max_value=10.0, value=2.0, step=0.5)
num_consecutive_days = st.sidebar.number_input("Jumlah Hari Berturut-turut", min_value=2, max_value=5, value=2, step=1)

st.sidebar.markdown("---")
st.sidebar.markdown("### 📊 Indikator Teknikal")
include_indicators = st.sidebar.checkbox("Tampilkan Indikator Teknikal", value=False)
if include_indicators:
    st.sidebar.info("⚠️ Perlu data 3 bulan, scan lebih lama")

st.sidebar.markdown("---")
st.sidebar.markdown("### ℹ️ Informasi")
st.sidebar.markdown(f"**Total Saham Terdeteksi:** {len(SYMBOLS)}")
if 'last_scan' in st.session_state:
    st.sidebar.markdown(f"**Scan Terakhir:** {st.session_state['last_scan'].strftime('%H:%M:%S')}")

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
    st.sidebar.info("Data di-refresh otomatis setiap 5 menit")

# ---------- Hasil ----------
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
                code = row['Kode']; name = row['Nama']; tkr = f"{code}.JK"
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
    st.info("👈 Pilih sumber daftar emiten (atau Manual) lalu klik 'Scan Saham' untuk memulai.")

# ---------- Auto refresh ----------
if auto_refresh and 'last_scan' in st.session_state:
    if (datetime.now() - st.session_state['last_scan']).total_seconds() >= 300:
        st.rerun()

# ---------- Footer ----------
st.markdown("---")
st.markdown(
    """
    <div style='text-align: center; color: #666;'>
        <small>Sumber daftar: Yahoo / IDX / Manual • Data harga: Yahoo Finance • Update tiap 5 menit (jika auto-refresh)</small>
    </div>
    """,
    unsafe_allow_html=True
)
