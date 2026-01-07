# BTC Bot (GitHub Actions) - diario 365d + mensual (últimos 24 meses aprox) via CoinGecko
# Env vars requeridas:
#   TELEGRAM_TOKEN
#   TELEGRAM_CHAT_ID

import os
import math
import requests
import numpy as np
from datetime import datetime, timezone

COINGECKO_URL = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
VS = "usd"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def fetch_prices(days: str | int):
    """
    days: 365, 730, "max"
    return: list of (datetime_utc, price_float)
    """
    params = {"vs_currency": VS, "days": str(days), "interval": "daily"}
    r = requests.get(COINGECKO_URL, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    raw = data.get("prices", [])
    out = []
    for ts_ms, price in raw:
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        out.append((dt, float(price)))
    if len(out) < 30:
        raise RuntimeError("No se pudieron obtener suficientes datos desde CoinGecko.")
    return out


def last_365_daily(prices):
    # prices ya viene daily. Tomamos los últimos 366 para poder tener 365 diffs.
    return prices[-366:]


def monthly_series_from_daily(prices, months=24):
    """
    De daily -> mensual: toma el último precio disponible de cada mes.
    Devuelve últimos `months` meses.
    """
    by_month = {}  # (y,m) -> (dt, price) del último día
    for dt, p in prices:
        key = (dt.year, dt.month)
        # nos quedamos con el último día del mes
        if key not in by_month or dt > by_month[key][0]:
            by_month[key] = (dt, p)

    keys_sorted = sorted(by_month.keys())
    series = [(by_month[k][0], by_month[k][1]) for k in keys_sorted]
    # últimos N meses
    series = series[-months:]
    return series


def analizar_precios(precios: np.ndarray, etiqueta: str) -> dict:
    precios = np.asarray(precios, dtype=float)
    n = int(len(precios))
    x = np.arange(n)

    pendiente, intercepto = np.polyfit(x, precios, 1)
    y_pred = pendiente * x + intercepto

    ss_res = float(np.sum((precios - y_pred) ** 2))
    ss_tot = float(np.sum((precios - np.mean(precios)) ** 2))
    r2 = float(1 - ss_res / ss_tot) if ss_tot != 0 else 0.0

    cambios = np.diff(precios)
    cambio_ultimo = float(cambios[-1]) if len(cambios) else 0.0
    cambio_promedio = float(cambios.mean()) if len(cambios) else 0.0

    media = float(precios.mean())
    desvio = float(precios.std())
    distancia = float(precios[-1] - media)

    prob_subir = float(np.sum(cambios > 0) / len(cambios)) if len(cambios) else 0.0
    prob_bajar = float(1 - prob_subir)

    if pendiente > 0 and r2 >= 0.60 and cambio_ultimo > cambio_promedio:
        escenario = "📈 Continuación alcista probable"
    elif pendiente < 0 and r2 >= 0.60:
        escenario = "📉 Continuación bajista probable"
    else:
        escenario = "⏸ Mercado lateral / indeciso"

    return {
        "etiqueta": etiqueta,
        "n": n,
        "precio": float(precios[-1]),
        "pendiente": float(pendiente),
        "r2": float(r2),
        "prob_subir": float(prob_subir),
        "prob_bajar": float(prob_bajar),
        "cambio_ultimo": float(cambio_ultimo),
        "cambio_promedio": float(cambio_promedio),
        "media": float(media),
        "desvio": float(desvio),
        "distancia": float(distancia),
        "escenario": escenario,
    }


def senal_combinada(res_m: dict, res_d: dict) -> str:
    mensual_alcista = (res_m["pendiente"] > 0) and (res_m["r2"] >= 0.60)
    mensual_bajista = (res_m["pendiente"] < 0) and (res_m["r2"] >= 0.60)

    diario_tendencia = res_d["r2"] >= 0.20
    diario_alcista = diario_tendencia and (res_d["pendiente"] > 0)
    diario_bajista = diario_tendencia and (res_d["pendiente"] < 0)
    diario_lateral = not (diario_alcista or diario_bajista)

    if mensual_alcista and diario_alcista:
        return "🧩 SEÑAL COMBINADA: ✅ Alineado alcista (macro + diario)"
    if mensual_alcista and diario_lateral:
        return "🧩 SEÑAL COMBINADA: ⚠️ Alcista macro, pero en pausa / rango (diario lateral)"
    if mensual_alcista and diario_bajista:
        return "🧩 SEÑAL COMBINADA: 🚨 Macro alcista, pero diario bajista (riesgo de corrección)"

    if mensual_bajista and diario_bajista:
        return "🧩 SEÑAL COMBINADA: ❌ Alineado bajista (macro + diario)"
    if mensual_bajista and diario_lateral:
        return "🧩 SEÑAL COMBINADA: ⚠️ Bajista macro, pero diario lateral / rebotes"
    if mensual_bajista and diario_alcista:
        return "🧩 SEÑAL COMBINADA: 🚨 Macro bajista, pero diario alcista (rebote contra tendencia)"

    # si mensual no es fuerte
    if res_m["pendiente"] > 0:
        return "🧩 SEÑAL COMBINADA: 📈 Sesgo macro alcista (no fuerte), diario mixto"
    if res_m["pendiente"] < 0:
        return "🧩 SEÑAL COMBINADA: 📉 Sesgo macro bajista (no fuerte), diario mixto"
    return "🧩 SEÑAL COMBINADA: ⏸ Sin sesgo claro"


def generar_alertas(res_m: dict, res_d: dict) -> list[str]:
    alertas = []

    if res_d["prob_bajar"] >= 0.55:
        alertas.append(f"⚠️ ALERTA: Probabilidad diaria de baja elevada ({res_d['prob_bajar']*100:.1f}%).")

    if res_d["desvio"] > 0:
        z_mov = abs(res_d["cambio_ultimo"]) / res_d["desvio"]
        if z_mov >= 0.15:
            alertas.append(f"⚠️ ALERTA: Movimiento diario fuerte (|Δ|/sd={z_mov:.2f}).")

        z_dist = abs(res_d["distancia"]) / res_d["desvio"]
        if z_dist >= 0.75:
            alertas.append(f"⚠️ ALERTA: Precio diario lejos de la media (|dist|/sd={z_dist:.2f}).")

    if (res_m["pendiente"] > 0 and res_m["r2"] >= 0.60) and (res_d["pendiente"] < 0 and res_d["r2"] >= 0.20):
        alertas.append("🚨 ALERTA: Macro alcista pero diario bajista con tendencia (posible corrección).")

    return alertas


def resumen(res: dict) -> str:
    return (
        f"[{res['etiqueta']}] n={res['n']}\n"
        f"Precio: {res['precio']:,.2f} USD\n"
        f"Pendiente: {res['pendiente']:,.2f}\n"
        f"R²: {res['r2']:.2f}\n"
        f"Prob subir/bajar: {res['prob_subir']*100:.1f}% / {res['prob_bajar']*100:.1f}%\n"
        f"Momento (último vs prom): {res['cambio_ultimo']:,.2f} vs {res['cambio_promedio']:,.2f}\n"
        f"Distancia a media: {res['distancia']:,.2f} (sd {res['desvio']:,.2f})\n"
        f"Escenario: {res['escenario']}\n"
    )


def send_telegram(text: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("Faltan TELEGRAM_TOKEN o TELEGRAM_CHAT_ID (Secrets).")

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
    r = requests.post(url, data=payload, timeout=30)
    r.raise_for_status()


def main():
    # 1) Daily data (para diario + para armar mensual)
    all_daily = fetch_prices("max")

    # DIARIO 365d
    daily_365 = last_365_daily(all_daily)
    precios_d = np.array([p for _, p in daily_365], dtype=float)
    res_d = analizar_precios(precios_d, "DIARIO (365d)")

    # MENSUAL (últimos 24 meses aprox, desde daily max)
    mensual = monthly_series_from_daily(all_daily, months=24)
    precios_m = np.array([p for _, p in mensual], dtype=float)
    res_m = analizar_precios(precios_m, "MENSUAL (24m)")

    # Señal + alertas
    senal = senal_combinada(res_m, res_d)
    alertas = generar_alertas(res_m, res_d)

    # Mensaje
    mensaje = "📊 BTC ANALYSIS BOT\n\n"
    mensaje += resumen(res_m) + "\n"
    mensaje += resumen(res_d) + "\n"
    mensaje += senal + "\n"
    if alertas:
        mensaje += "\n" + "\n".join(alertas) + "\n"

    send_telegram(mensaje)


if __name__ == "__main__":
    main()
