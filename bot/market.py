"""Marktdaten über yfinance: Kurse, Momentum, Volatilität, Schlagzeilen."""
import statistics


def snapshot(universe: dict) -> dict:
    """universe: {isin: {name, yf, stars}} -> {isin: {price, ret_5d, ret_20d, ret_60d, vol_20d, news}}"""
    import yfinance as yf

    out = {}
    symbols = {v["yf"]: isin for isin, v in universe.items() if v.get("yf")}
    if not symbols:
        return out
    hist = yf.download(list(symbols), period="6mo", interval="1d", auto_adjust=True,
                       progress=False, group_by="ticker", threads=True)
    for sym, isin in symbols.items():
        try:
            closes = hist[sym]["Close"].dropna().tolist() if len(symbols) > 1 else hist["Close"].dropna().tolist()
        except KeyError:
            continue
        if len(closes) < 61:
            continue
        rets = [closes[i] / closes[i - 1] - 1 for i in range(len(closes) - 20, len(closes))]
        out[isin] = {
            "price": round(closes[-1], 3),
            "ret_5d": round(closes[-1] / closes[-6] - 1, 4),
            "ret_20d": round(closes[-1] / closes[-21] - 1, 4),
            "ret_60d": round(closes[-1] / closes[-61] - 1, 4),
            "vol_20d": round(statistics.pstdev(rets) * (252 ** 0.5), 3),
        }
    return out


def headlines(universe: dict, isins: list, per: int = 3) -> dict:
    import yfinance as yf

    out = {}
    for isin in isins:
        sym = universe[isin].get("yf")
        try:
            items = yf.Ticker(sym).news[:per]
            out[isin] = [(n.get("content") or n).get("title", "") for n in items]
        except Exception:
            out[isin] = []
    return out
