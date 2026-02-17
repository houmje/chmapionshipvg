from flask import Flask, render_template_string, request, jsonify
import sqlite3
import requests

app = Flask(__name__)

HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>EV Fleet Planner</title>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <style>
        /* СКРЫВАЕМ ЛОГОТИП С ФЛАГОМ */
        .leaflet-control-attribution {
            display: none !important;
        }

        * { font-family: Arial, sans-serif; margin: 0; padding: 0; box-sizing: border-box; }
        body { background: #f5f7fa; padding: 20px; }
        .container { max-width: 1200px; margin: 0 auto; display: grid; grid-template-columns: 1fr 350px; gap: 20px; }
        #map { height: 500px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.1); }
        .sidebar { background: white; border-radius: 12px; padding: 20px; box-shadow: 0 4px 20px rgba(0,0,0,0.1); }
        h1 { font-size: 28px; color: #1a365d; margin-bottom: 20px; text-align: center; }
        h2 { font-size: 20px; color: #2c5282; margin-bottom: 15px; border-bottom: 2px solid #bee3f8; padding-bottom: 8px; }
        .form-group { margin-bottom: 15px; }
        label { display: block; margin-bottom: 6px; font-weight: 500; color: #4a5568; }
        input, select, button { width: 100%; padding: 10px; border: 2px solid #cbd5e0; border-radius: 8px; font-size: 16px; margin-top: 5px; }
        button { background: #3182ce; color: white; border: none; cursor: pointer; font-weight: 600; }
        button:hover { background: #2c5282; }
        #result { margin-top: 25px; padding: 20px; background: #f0f9ff; border-left: 4px solid #3182ce; border-radius: 0 8px 8px 0; display: none; }
        .metric { display: flex; justify-content: space-between; padding: 10px 0; border-bottom: 1px dashed #cbd5e0; }
        .metric:last-child { border-bottom: none; }
        .metric-value { font-weight: 600; color: #2c5282; }
        .risk-high { color: #e53e3e; font-weight: bold; font-size: 20px; }
        .risk-medium { color: #dd6b20; font-weight: bold; font-size: 20px; }
        .risk-low { color: #38a169; font-weight: bold; font-size: 20px; }
        .recommendation { background: #fff8e6; padding: 15px; border-radius: 8px; margin-top: 15px; border-left: 3px solid #f6ad55; }
        .dashboard { margin-top: 30px; }
        .metric-card { background: white; border-radius: 10px; padding: 15px; margin-bottom: 15px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); text-align: center; }
        .metric-card h3 { color: #4a5568; margin-bottom: 10px; font-size: 16px; }
        .metric-card .value { font-size: 28px; font-weight: bold; color: #2c5282; margin: 10px 0; }
        .instructions { background: #ebf8ff; padding: 15px; border-radius: 8px; margin: 15px 0; font-size: 14px; line-height: 1.5; }
        .instructions ol { padding-left: 20px; margin-top: 10px; }
        .instructions li { margin-bottom: 8px; }
        .legend { background: white; padding: 15px; border-radius: 8px; margin-top: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }
        .legend-item { display: flex; align-items: center; margin: 8px 0; }
        .legend-color { width: 20px; height: 20px; border-radius: 4px; margin-right: 10px; }
        .legend-red { background: #e53e3e; }
        .legend-orange { background: #dd6b20; }
        .legend-green { background: #38a169; }
    </style>
</head>
<body>
    <div class="container">
        <div>
            <h1>🚗 EV Fleet Route Planner</h1>
            <div id="map"></div>

            <div class="legend">
                <h3>Легенда рисковых участков</h3>
                <div class="legend-item">
                    <div class="legend-color legend-red"></div>
                    <span>🔴 Критический риск (< 15% заряда)</span>
                </div>
                <div class="legend-item">
                    <div class="legend-color legend-orange"></div>
                    <span>🟠 Средний риск (15-25% заряда)</span>
                </div>
                <div class="legend-item">
                    <div class="legend-color legend-green"></div>
                    <span>✅ Низкий риск (> 25% заряда)</span>
                </div>
            </div>
        </div>
        <div class="sidebar">
            <h2>Планирование маршрута</h2>
            <div class="instructions">
                <p><strong>Как спланировать:</strong></p>
                <ol>
                    <li>Кликните на карту 2+ раза для создания точек маршрута</li>
                    <li>Заполните параметры автомобиля</li>
                    <li>Нажмите "Рассчитать маршрут"</li>
                </ol>
            </div>

            <div class="form-group">
                <label for="vehicle_id">ID автомобиля</label>
                <input type="text" id="vehicle_id" value="EV001" placeholder="Например: EV001">
            </div>
            <div class="form-group">
                <label for="start_soc">Начальный заряд (%)</label>
                <input type="number" id="start_soc" value="80" min="0" max="100" placeholder="0-100%">
            </div>
            <div class="form-group">
                <label for="road_type">Тип дороги</label>
                <select id="road_type">
                    <option value="highway">Магистраль</option>
                    <option value="primary" selected>Основная дорога</option>
                    <option value="rural">Сельская дорога</option>
                </select>
            </div>
            <div class="form-group">
                <label for="temperature">Температура (°C)</label>
                <input type="number" id="temperature" value="15" min="-30" max="40" placeholder="Например: 15">
            </div>
            <button onclick="calculate()">Рассчитать маршрут</button>

            <div id="result">
                <h2>Результаты расчёта</h2>
                <div class="metric">
                    <span>Дистанция:</span>
                    <span class="metric-value" id="dist">— км</span>
                </div>
                <div class="metric">
                    <span>Расход:</span>
                    <span class="metric-value" id="cons">— кВт⋅ч/100км</span>
                </div>
                <div class="metric">
                    <span>Энергия:</span>
                    <span class="metric-value" id="energy">— кВт⋅ч</span>
                </div>
                <div class="metric">
                    <span>Конечный заряд:</span>
                    <span class="metric-value" id="soc">— %</span>
                </div>
                <div class="metric">
                    <span>Уровень риска:</span>
                    <span class="metric-value" id="risk">—</span>
                </div>
                <div class="recommendation" id="recommendation">
                    Рекомендации появятся после расчёта
                </div>
            </div>

            <div class="dashboard">
                <h2>📊 Дашборд парка</h2>
                <button onclick="loadDashboard()">Обновить данные</button>

                <div class="metric-card">
                    <h3>Активные автомобили</h3>
                    <div class="value" id="active-vehicles">—</div>
                    <div class="metric-desc">всего</div>
                </div>
                <div class="metric-card">
                    <h3>Средний расход</h3>
                    <div class="value" id="avg-consumption">—</div>
                    <div class="metric-desc">кВт⋅ч/100км</div>
                </div>
                <div class="metric-card">
                    <h3>Низкий заряд</h3>
                    <div class="value" id="low-soc">—</div>
                    <div class="metric-desc">авто < 20%</div>
                </div>
            </div>
        </div>
    </div>

    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script>
        // Карта
        const map = L.map('map').setView([55.75, 37.62], 11);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '&copy; OpenStreetMap contributors'
        }).addTo(map);

        // Маршрут
        let coords = [];
        map.on('click', function(e) {
            coords.push({latitude: e.latlng.lat, longitude: e.latlng.lng});
            L.circleMarker(e.latlng, {radius: 8, color: '#3182ce', fillColor: '#3182ce', fillOpacity: 1}).addTo(map);
            // Удаляем старый маршрут перед отрисовкой нового
            if (window.routeLayer) {
                map.removeLayer(window.routeLayer);
            }
        });

        // Расчёт через API Г.1 с визуализацией рисковых участков
        async function calculate() {
            if (coords.length < 2) {
                alert('⚠️ Кликните на карту минимум 2 раза для создания маршрута!');
                return;
            }

            const btn = document.querySelector('button');
            btn.disabled = true;
            btn.textContent = 'Расчёт...';

            try {
                const payload = {
                    vehicle_id: document.getElementById('vehicle_id').value,
                    coordinates: coords,
                    start_soc: parseFloat(document.getElementById('start_soc').value),
                    avg_temperature_c: parseFloat(document.getElementById('temperature').value),
                    road_type: document.getElementById('road_type').value,
                    avg_speed_kmh: 50
                };

                const res = await fetch('/predict', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(payload)
                });

                if (!res.ok) {
                    const error = await res.json();
                    throw new Error(error.error || `Ошибка сервера: ${res.status}`);
                }

                const data = await res.json();

                // Вывод результатов
                document.getElementById('dist').textContent = data.route_distance_km + ' км';
                document.getElementById('cons').textContent = data.predicted_consumption_kwh_per_100km + ' кВт⋅ч/100км';
                document.getElementById('energy').textContent = data.energy_needed_kwh + ' кВт⋅ч';
                document.getElementById('soc').textContent = data.estimated_end_soc_percent + ' %';

                // Цветовой индикатор риска
                const riskEl = document.getElementById('risk');
                riskEl.textContent = data.risk_level.toUpperCase();
                riskEl.className = 'metric-value risk-' + data.risk_level;

                // Рекомендации по зарядке
                let rec = '';
                if (data.risk_level === 'high') {
                    rec = '🔴 <strong>КРИТИЧЕСКИЙ РИСК!</strong> Обязательна промежуточная зарядка. Рекомендуем сократить дистанцию или выбрать маршрут с зарядными станциями.';
                } else if (data.risk_level === 'medium') {
                    rec = '🟠 <strong>СРЕДНИЙ РИСК.</strong> Рассмотрите возможность промежуточной зарядки для безопасности. Избегайте агрессивного вождения.';
                } else {
                    rec = '✅ <strong>НИЗКИЙ РИСК.</strong> Маршрут безопасен для запланированной поездки. Рекомендуемый запас заряда сохранён.';
                }
                document.getElementById('recommendation').innerHTML = rec;

                // Показываем результат
                document.getElementById('result').style.display = 'block';

                // ВИЗУАЛИЗАЦИЯ РИСКОВЫХ УЧАСТКОВ МАРШРУТА
                visualizeRiskSegments(coords, data.predicted_consumption_kwh_per_100km, parseFloat(document.getElementById('start_soc').value));

                // Скролл к результату
                document.getElementById('result').scrollIntoView({behavior: 'smooth', block: 'nearest'});

            } catch (e) {
                alert('❌ Ошибка расчёта:\\n' + e.message + '\\n\\nУбедитесь, что сервер Г.1 запущен на порту 8000!');
                console.error(e);
            } finally {
                btn.disabled = false;
                btn.textContent = 'Рассчитать маршрут';
            }
        }

        // Функция визуализации рисковых участков
        function visualizeRiskSegments(coordinates, consumptionKwhPer100km, startSoc) {
            // Удаляем старый маршрут
            if (window.routeLayer) {
                map.removeLayer(window.routeLayer);
            }

            // Создаём новый слой для маршрута
            window.routeLayer = L.layerGroup();

            const batteryCapacity = 60; // кВт·ч (можно брать из БД)
            let currentSoc = startSoc;

            // Разбиваем маршрут на сегменты и раскрашиваем каждый
            for (let i = 0; i < coordinates.length - 1; i++) {
                const lat1 = coordinates[i].latitude;
                const lon1 = coordinates[i].longitude;
                const lat2 = coordinates[i+1].latitude;
                const lon2 = coordinates[i+1].longitude;

                // Расчёт длины сегмента (гаверсинус)
                const R = 6371; // Радиус Земли в км
                const dLat = (lat2 - lat1) * Math.PI / 180;
                const dLon = (lon2 - lon1) * Math.PI / 180;
                const a = Math.sin(dLat/2) * Math.sin(dLat/2) +
                          Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * 
                          Math.sin(dLon/2) * Math.sin(dLon/2);
                const segmentDistance = R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));

                // Расчёт энергии на сегмент и нового заряда
                const energyForSegment = consumptionKwhPer100km * segmentDistance / 100;
                const socAfterSegment = currentSoc - (energyForSegment / batteryCapacity * 100);

                // Определение цвета риска
                let color = '#38a169'; // green
                let riskLevel = 'low';
                if (socAfterSegment < 15) {
                    color = '#e53e3e'; // red
                    riskLevel = 'high';
                } else if (socAfterSegment < 25) {
                    color = '#dd6b20'; // orange
                    riskLevel = 'medium';
                }

                // Отрисовка сегмента с цветом риска
                const segmentLine = L.polyline(
                    [[lat1, lon1], [lat2, lon2]],
                    {
                        color: color,
                        weight: 6,
                        opacity: 0.9
                    }
                ).addTo(window.routeLayer);

                // Подсказка при наведении
                const tooltipContent = `
                    <strong>Сегмент ${i+1}</strong><br>
                    Длина: ${segmentDistance.toFixed(2)} км<br>
                    Расход: ${consumptionKwhPer100km.toFixed(1)} кВт⋅ч/100км<br>
                    Заряд после: ${socAfterSegment.toFixed(1)}%<br>
                    Риск: ${riskLevel === 'high' ? '🔴 Критический' : riskLevel === 'medium' ? '🟠 Средний' : '✅ Низкий'}
                `;
                segmentLine.bindTooltip(tooltipContent, {permanent: false, direction: 'top'});

                // Обновляем текущий заряд для следующего сегмента
                currentSoc = socAfterSegment;
            }

            // Добавляем весь маршрут на карту
            window.routeLayer.addTo(map);
        }

        // Загрузка дашборда
        async function loadDashboard() {
            try {
                const res = await fetch('/dashboard');
                if (!res.ok) throw new Error('Ошибка загрузки дашборда');

                const data = await res.json();

                document.getElementById('active-vehicles').textContent = data.active_vehicles || '—';
                document.getElementById('avg-consumption').textContent = (data.avg_consumption || '—') + ' кВт⋅ч/100км';
                document.getElementById('low-soc').textContent = data.low_soc_vehicles || '—';

            } catch (e) {
                alert('❌ Ошибка загрузки дашборда: ' + e.message);
                console.error(e);
            }
        }

        // Автозагрузка дашборда при открытии страницы
        window.onload = function() {
            loadDashboard();

            // Проверка доступности API Г.1
            fetch('/predict', {method: 'OPTIONS'})
                .catch(() => {
                    alert('⚠️ Сервер Г.1 (порт 8000) недоступен!\\nЗапустите модуль Г.1 перед использованием.');
                });
        };
    </script>
</body>
</html>
'''


@app.route('/')
def index():
    return render_template_string(HTML)


@app.route('/predict', methods=['POST', 'OPTIONS'])
def predict():
    if request.method == 'OPTIONS':
        return '', 200

    try:
        # Прокси к API Г.1
        resp = requests.post(
            'http://127.0.0.1:8000/predict_consumption',
            json=request.get_json(),
            timeout=10
        )
        return resp.json(), resp.status_code
    except requests.exceptions.ConnectionError:
        return {'error': 'Сервер Г.1 (порт 8000) недоступен. Запустите модуль Г.1.'}, 503
    except Exception as e:
        return {'error': str(e)}, 500


@app.route('/dashboard')
def dashboard():
    try:
        conn = sqlite3.connect('ev_championship.db')
        cur = conn.cursor()

        # АКТИВНЫЕ АВТОМОБИЛИ (ВСЁ ВРЕМЯ)
        cur.execute("""
                    SELECT COUNT(DISTINCT vehicle_id)
                    FROM telematics_preprocessed
                    """)
        active = cur.fetchone()[0] or 0

        # СРЕДНИЙ РАСХОД (ВСЁ ВРЕМЯ)
        cur.execute("""
                    SELECT AVG(consumption_kwh_per_100km)
                    FROM telematics_preprocessed
                    """)
        avg = cur.fetchone()[0] or 0

        # АВТОМОБИЛИ С НИЗКИМ ЗАРЯДОМ (ВСЁ ВРЕМЯ)
        cur.execute("""
                    SELECT COUNT(DISTINCT vehicle_id)
                    FROM telematics_preprocessed
                    WHERE battery_soc_percent < 20
                    """)
        low_soc = cur.fetchone()[0] or 0

        conn.close()

        return jsonify({
            'active_vehicles': int(active),
            'avg_consumption': round(avg, 1),
            'low_soc_vehicles': int(low_soc)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    print("=" * 60)
    print("🚀 EV FLEET PLANNER (МОДУЛЬ Г.2)")
    print("=" * 60)
    print("• Веб-интерфейс: http://127.0.0.1:5000")
    print("• API Г.1 должен быть запущен на порту 8000")
    print("• Дашборд: метрики за всё время эксплуатации")
    print("• Рисковые участки: цветовая индикация по остатку заряда")
    print("=" * 60)
    app.run(host='127.0.0.1', port=5000, debug=False)