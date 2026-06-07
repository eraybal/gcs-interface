import sys
import time
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtCore import QThread, pyqtSignal
from pymavlink import mavutil

MAP_HTML = """
<!DOCTYPE html>
<html>
<head>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <style>
        body, html, #map { height: 100%; margin: 0; padding: 0; }
    </style>
</head>
<body>
    <div id="map"></div>
    <script>
        var map = L.map('map').setView([40.18, 29.06], 15);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);
        
        var droneMarker = L.marker([40.18, 29.06]).addTo(map);
        
        function updateDronePosition(lat, lon) {
            var newLatLng = new L.LatLng(lat, lon);
            droneMarker.setLatLng(newLatLng);
            map.panTo(newLatLng); // Haritayı drona odakla
        }
    </script>
</body>
</html>
"""

class MAVLinkThread(QThread):
    telemetry_signal = pyqtSignal(dict)

    def __init__(self, connection_string):
        super().__init__()
        self.connection_string = connection_string
        self.running = True
        self.master = None

    def run(self):
        try:
            self.master = mavutil.mavlink_connection(self.connection_string)
            self.master.wait_heartbeat()
            
            mode_map = {0: 'STABILIZE', 3: 'AUTO', 4: 'GUIDED', 5: 'LOITER', 6: 'RTL', 9: 'LAND'}
            
            self.master.mav.request_data_stream_send(
                self.master.target_system, self.master.target_component,
                mavutil.mavlink.MAV_DATA_STREAM_ALL, 10, 1
            )
            
            telemetry_data = {
                'alt': 0.0, 'airspeed': 0.0, 'heading': 0,
                'lat': 0.0, 'lon': 0.0,
                'battery': 0, 'mode': 'Bilinmiyor'
            }
            
            last_ui_update = 0
            
            while self.running:
                msg = self.master.recv_match(
                    type=['VFR_HUD', 'GLOBAL_POSITION_INT', 'SYS_STATUS', 'HEARTBEAT'], 
                    blocking=True, timeout=0.1
                )
                
                if msg:
                    msg_type = msg.get_type()
                    
                    if msg_type == 'VFR_HUD':
                        telemetry_data['alt'] = round(msg.alt, 2)
                        telemetry_data['airspeed'] = round(msg.airspeed, 2)
                        telemetry_data['heading'] = msg.heading
                    elif msg_type == 'GLOBAL_POSITION_INT':
                        telemetry_data['lat'] = msg.lat / 10000000.0
                        telemetry_data['lon'] = msg.lon / 10000000.0
                    elif msg_type == 'SYS_STATUS':
                        telemetry_data['battery'] = msg.battery_remaining
                    elif msg_type == 'HEARTBEAT':
                        telemetry_data['mode'] = mode_map.get(msg.custom_mode, str(msg.custom_mode))

                    current_time = time.time()
                    if current_time - last_ui_update >= 0.1:
                        self.telemetry_signal.emit(telemetry_data)
                        last_ui_update = current_time
                        
        except Exception as e:
            print(f"Bağlantı hatası: {e}")

class GCSWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()
        
        self.mav_thread = MAVLinkThread('tcp:127.0.0.1:5762') 
        self.mav_thread.telemetry_signal.connect(self.update_ui)
        self.mav_thread.start()

    def initUI(self):
        self.setWindowTitle('Gelişmiş Yer Kontrol İstasyonu')
        self.resize(800, 500)
        
        main_layout = QHBoxLayout()

        telemetry_layout = QVBoxLayout()
        
        self.mode_label = QLabel('Uçuş Modu: Bekleniyor...')
        self.alt_label = QLabel('İrtifa (MSL): Bekleniyor...')
        self.speed_label = QLabel('Hız (m/s): Bekleniyor...')
        self.bat_label = QLabel('Batarya (%): Bekleniyor...')
        self.gps_label = QLabel('Konum: Bekleniyor...')
        
        font = self.mode_label.font()
        font.setPointSize(12)
        font.setBold(True)
        self.mode_label.setFont(font)
        
        normal_font = self.alt_label.font()
        normal_font.setPointSize(11)
        for label in [self.alt_label, self.speed_label, self.bat_label, self.gps_label]:
            label.setFont(normal_font)
        
        telemetry_layout.addWidget(self.mode_label)
        telemetry_layout.addWidget(self.bat_label)
        telemetry_layout.addWidget(self.alt_label)
        telemetry_layout.addWidget(self.speed_label)
        telemetry_layout.addWidget(self.gps_label)
        telemetry_layout.addStretch() 
        
        self.map_view = QWebEngineView()
        self.map_view.setHtml(MAP_HTML)
        
        main_layout.addLayout(telemetry_layout, 1)
        main_layout.addWidget(self.map_view, 2)
        self.setLayout(main_layout)

    def update_ui(self, data):
        self.mode_label.setText(f"Uçuş Modu: {data['mode']}")
        self.alt_label.setText(f"İrtifa (MSL): {data['alt']} m")
        self.speed_label.setText(f"Hız: {data['airspeed']} m/s")
        self.bat_label.setText(f"Batarya: %{data['battery']}")
        
        if data['lat'] != 0.0 and data['lon'] != 0.0:
            self.gps_label.setText(f"Lat: {data['lat']:.5f}\nLon: {data['lon']:.5f}")
            
            js_code = f"updateDronePosition({data['lat']}, {data['lon']});"
            self.map_view.page().runJavaScript(js_code)

    def closeEvent(self, event):
        self.mav_thread.running = False
        self.mav_thread.wait()
        event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = GCSWindow()
    window.show()
    sys.exit(app.exec_())