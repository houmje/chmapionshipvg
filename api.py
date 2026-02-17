from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
import joblib
import sqlite3
import pandas as pd
import numpy as np
from math import radians, sin, cos, sqrt, atan2
from datetime import datetime

app = FastAPI(title="EV Fleet API", version="1.0")

# ============================================
# ЗАГРУЗКА МОДЕЛИ ИЗ МОДУЛЯ В.1
# ============================================

try:
    model_pkg = joblib.load('ev_incremental_regressor_v1.pkl')
    model = model_pkg['model']
    scaler = model_pkg['scaler']
    feature_cols = model_pkg['feature_cols']
    road_mapping = model_pkg['road_mapping']
    print(f"✅ Загружена модель из В.1: {model_pkg['metadata']['best_model']}")
except FileNotFoundError:
    raise RuntimeError("❌ Модель не найдена! Сначала выполните модуль В.1")


# ============================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================

def haversine(lat1, lon1, lat2, lon2):
    """Расчёт расстояния между двумя точками (км)"""
    R = 6371
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


def get_db():
    return sqlite3.connect('ev_championship.db')


def get_battery_capacity(vehicle_id):
    """Получение реальной ёмкости батареи из БД"""
    conn = get_db()
    try:
        df = pd.read_sql("""
                         SELECT battery_capacity_kwh
                         FROM vehicles
                         WHERE vehicle_id = ?
                         """, conn, params=(vehicle_id,))
        if df.empty or df['battery_capacity_kwh'].iloc[0] is None:
            return 60.0  # значение по умолчанию
        return float(df['battery_capacity_kwh'].iloc[0])
    finally:
        conn.close()


def calculate_end_soc(start_soc, consumption, distance, battery_capacity_kwh):
    """Расчёт конечного заряда с учётом реальной ёмкости батареи"""
    energy_used = consumption * distance / 100  # кВт·ч
    start_energy = battery_capacity_kwh * start_soc / 100
    end_energy = max(0, start_energy - energy_used)
    return end_energy / battery_capacity_kwh * 100


def assess_risk(start_soc, end_soc, consumption):
    """
    ИСПРАВЛЕННАЯ ЛОГИКА ОПРЕДЕЛЕНИЯ РИСКА:
    - Учитывает динамику разряда (потеря заряда)
    - Не помечает как высокий риск при высоком расходе, если конечный заряд остаётся высоким
    - Учитывает реальный уровень заряда
    """
    soc_drop = start_soc - end_soc  # Сколько % заряда потеряно

    # КРИТИЧЕСКИЙ РИСК: конечный заряд < 15%
    if end_soc < 15:
        return "high", "🔴 КРИТИЧЕСКИЙ РИСК! Немедленно зарядите. Конечный заряд < 15%."

    # СРЕДНИЙ РИСК: значительная потеря заряда + высокий расход
    if soc_drop > 20 and consumption > 30:
        return "medium", "🟠 СРЕДНИЙ РИСК. Потеря заряда >20% при высоком расходе. Оптимизируйте маршрут."

    # ВЫСОКИЙ РИСК: низкий конечный заряд + высокий расход
    if end_soc < 30 and consumption > 35:
        return "high", "🔴 ВЫСОКИЙ РИСК! Конечный заряд <30% при высоком расходе. Рекомендуется зарядка."

    # НИЗКИЙ РИСК: всё в норме
    return "low", "✅ НИЗКИЙ РИСК. Маршрут безопасен для запланированной поездки."


# ============================================
# СХЕМЫ ЗАПРОСОВ И ОТВЕТОВ
# ============================================

class Coordinate(BaseModel):
    latitude: float
    longitude: float


class RouteRequest(BaseModel):
    vehicle_id: str
    coordinates: List[Coordinate]
    start_soc: float
    avg_temperature_c: float
    road_type: str = "highway"
    avg_speed_kmh: float = 50.0


class PredictionResponse(BaseModel):
    route_distance_km: float
    predicted_consumption_kwh_per_100km: float
    energy_needed_kwh: float
    estimated_end_soc_percent: float
    risk_level: str
    recommendation: str
    coordinates_processed: int
    model_used: str


# ============================================
# ЭНДПОИНТ 1: ПРОГНОЗ РАСХОДА ПО КООРДИНАТАМ (ИСПРАВЛЕННЫЙ)
# ============================================

@app.post("/predict_consumption", response_model=PredictionResponse)
async def predict_consumption(req: RouteRequest):
    # Валидация
    if len(req.coordinates) < 2:
        raise HTTPException(400, "Маршрут должен содержать минимум 2 координаты")
    if not (0 <= req.start_soc <= 100):
        raise HTTPException(400, "start_soc должен быть в диапазоне 0-100%")
    if req.road_type not in road_mapping:
        raise HTTPException(400, f"road_type должен быть: {list(road_mapping.keys())}")

    # РАСЧЁТ ДИСТАНЦИИ ПО КООРДИНАТАМ
    total_distance = 0.0
    for i in range(len(req.coordinates) - 1):
        total_distance += haversine(
            req.coordinates[i].latitude,
            req.coordinates[i].longitude,
            req.coordinates[i + 1].latitude,
            req.coordinates[i + 1].longitude
        )

    # ПОЛУЧЕНИЕ РЕАЛЬНОЙ ЁМКОСТИ БАТАРЕИ ИЗ БД
    battery_capacity = get_battery_capacity(req.vehicle_id)

    # Подготовка признаков для модели В.1
    road_encoded = road_mapping[req.road_type]
    input_data = pd.DataFrame([{
        'distance_km': total_distance,
        'avg_speed_kmh': req.avg_speed_kmh,
        'start_soc': req.start_soc,
        'avg_temperature_c': req.avg_temperature_c,
        'road_type_encoded': road_encoded,
        'avg_acceleration': 0.05
    }])[feature_cols]

    # ПРОГНОЗ ЧЕРЕЗ МОДЕЛЬ В.1
    scaled = scaler.transform(input_data)
    consumption = model.predict(scaled)[0]

    # РАСЧЁТ КОНЕЧНОГО ЗАРЯДА С УЧЁТОМ РЕАЛЬНОЙ ЁМКОСТИ
    energy_needed = consumption * total_distance / 100
    end_soc = calculate_end_soc(req.start_soc, consumption, total_distance, battery_capacity)

    # ОПРЕДЕЛЕНИЕ РИСКА ПО ИСПРАВЛЕННОЙ ЛОГИКЕ
    risk_level, recommendation = assess_risk(req.start_soc, end_soc, consumption)

    return PredictionResponse(
        route_distance_km=round(total_distance, 2),
        predicted_consumption_kwh_per_100km=round(consumption, 2),
        energy_needed_kwh=round(energy_needed, 2),
        estimated_end_soc_percent=round(end_soc, 1),
        risk_level=risk_level,
        recommendation=recommendation,
        coordinates_processed=len(req.coordinates),
        model_used=model_pkg['metadata']['best_model']
    )


# ============================================
# ЭНДПОИНТ 2: ОЦЕНКА РИСКА АВТОМОБИЛЯ (ИСПРАВЛЕННЫЙ)
# ============================================

@app.get("/vehicle_risk/{vehicle_id}")
async def vehicle_risk(vehicle_id: str):
    conn = get_db()
    try:
        df = pd.read_sql("""
                         SELECT consumption_kwh_per_100km, battery_soc_percent, timestamp
                         FROM telematics_preprocessed
                         WHERE vehicle_id = ?
                           AND consumption_kwh_per_100km BETWEEN 5
                           AND 50
                         ORDER BY timestamp DESC
                             LIMIT 10
                         """, conn, params=(vehicle_id,))
    finally:
        conn.close()

    if df.empty:
        raise HTTPException(404, f"Автомобиль {vehicle_id} не найден")

    # Расчёт метрик
    avg_consumption = df['consumption_kwh_per_100km'].mean()
    last_soc = df['battery_soc_percent'].iloc[0]

    # ИСПРАВЛЕННАЯ ЛОГИКА РИСКА
    if last_soc < 10:
        recommendation = "🔴 КРИТИЧЕСКИ НИЗКИЙ ЗАРЯД! Немедленно подключите зарядку."
        risk_level = "critical"
    elif last_soc < 20:
        recommendation = "🟠 Низкий заряд (<20%). Рекомендуется зарядка перед следующей поездкой."
        risk_level = "high"
    elif avg_consumption > 35:
        recommendation = "⚠️ Высокий расход энергии. Проверьте стиль вождения и условия эксплуатации."
        risk_level = "medium"
    else:
        recommendation = "✅ Автомобиль в нормальном состоянии."
        risk_level = "low"

    return {
        "vehicle_id": vehicle_id,
        "last_recorded_soc_percent": round(last_soc, 1),
        "avg_consumption_last_10_trips": round(avg_consumption, 2),
        "risk_level": risk_level,
        "recommendation": recommendation,
        "analyzed_trips": len(df),
        "timestamp": datetime.now().isoformat()
    }


# ============================================
# ЭНДПОИНТ 3: ПРОГНОЗ СОСТОЯНИЯ БАТАРЕИ (КАК В МОДУЛЕ В.3)
# ============================================

@app.get("/battery_health_forecast/{vehicle_id}")
async def battery_health_forecast(vehicle_id: str):
    conn = get_db()
    try:
        df = pd.read_sql("""
                         SELECT vehicle_id,
                                model,
                                battery_capacity_kwh,
                                battery_health,
                                initial_odometer_km,
                                year_of_manufacture
                         FROM vehicles
                         WHERE vehicle_id = ?
                         """, conn, params=(vehicle_id,))
    finally:
        conn.close()

    if df.empty:
        raise HTTPException(404, f"Автомобиль {vehicle_id} не найден в таблице vehicles")

    row = df.iloc[0]
    model_name = row['model'] or "Unknown"

    # КОРРЕКТНОЕ ПРЕОБРАЗОВАНИЕ ДОЛИ В ПРОЦЕНТЫ
    health_at_entry = (row['battery_health'] or 0.0) * 100
    odometer_at_entry = row['initial_odometer_km'] or 0.0

    # Расчёт скорости деградации (как в В.3)
    degradation_to_entry = 100.0 - health_at_entry
    km_to_entry = max(odometer_at_entry, 1)
    degradation_rate = (degradation_to_entry / km_to_entry) * 1000

    # Оставшийся ресурс до 80%
    remaining_to_80 = health_at_entry - 80.0
    if remaining_to_80 > 0:
        remaining_km = (remaining_to_80 / degradation_rate) * 1000
        remaining_years = remaining_km / 15000
    else:
        remaining_km = 0
        remaining_years = 0

    # Прогноз на 1 год
    degradation_1y = degradation_rate * 15
    health_1y = max(0, health_at_entry - degradation_1y)

    # Статус и рекомендация
    if health_at_entry < 80:
        status = "critical"
        recommendation = "🔴 КРИТИЧЕСКИЙ ИЗНОС! Батарея ниже 80% — требуется замена."
    elif health_at_entry < 90:
        status = "warning"
        recommendation = "⚠️ Повышенный износ. Рекомендуется мониторинг и планирование замены."
    else:
        status = "normal"
        recommendation = "✅ Батарея в хорошем состоянии. Рекомендуемый порог замены: 80%."

    return {
        "vehicle_id": vehicle_id,
        "model": model_name,
        "current_health_percent": round(health_at_entry, 1),
        "odometer_at_entry_km": int(odometer_at_entry),
        "degradation_rate_percent_per_1000km": round(degradation_rate, 3),
        "remaining_km_to_80_percent": round(remaining_km, 0),
        "remaining_years_to_80_percent": round(remaining_years, 1),
        "forecast_health_1_year_percent": round(health_1y, 1),
        "status": status,
        "recommendation": recommendation,
        "note": "Прогноз основан на линейной модели деградации из модуля В.3",
        "timestamp": datetime.now().isoformat()
    }


# ============================================
# HEALTH CHECK
# ============================================

@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "model_loaded": True,
        "model_type": model_pkg['metadata']['best_model'],
        "features": feature_cols,
        "timestamp": datetime.now().isoformat()
    }


# ============================================
# ЗАПУСК СЕРВЕРА
# ============================================

if __name__ == "__main__":
    import uvicorn

    print("\n" + "=" * 60)
    print("🚀 EV FLEET API (МОДУЛЬ Г.1) — ИСПРАВЛЕННАЯ ВЕРСИЯ")
    print("=" * 60)
    print(f"• Модель из В.1: {model_pkg['metadata']['best_model']}")
    print(f"• MAE на холд-аут: {model_pkg['metadata']['mae_holdout']:.2f} кВт⋅ч/100км")
    print(f"\nЭндпоинты:")
    print("  POST /predict_consumption         ← с учётом реальной ёмкости батареи")
    print("  GET  /vehicle_risk/{vehicle_id}   ← исправленная логика риска")
    print("  GET  /battery_health_forecast/{id} ← как в модуле В.3")
    print("\nДокументация: http://127.0.0.1:8000/docs")
    print("=" * 60 + "\n")
    uvicorn.run(app, host="127.0.0.1", port=8000)