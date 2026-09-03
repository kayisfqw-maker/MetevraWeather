import requests
import threading
import random
import os
import hashlib
import re
import locale
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote
from PIL import Image as PILImage, ImageDraw, ImageFilter, ImageEnhance
from datetime import datetime

from kivy.config import Config
# Sağ tık ile oluşan Kivy çoklu-dokunma kırmızı noktalarını kapat.
Config.set("input", "mouse", "mouse,disable_multitouch")

from kivy.app import App
from kivy.clock import Clock
from kivy.animation import Animation
from kivy.storage.jsonstore import JsonStore
from kivy.core.window import Window
from kivy.metrics import dp, sp
from kivy.core.text import LabelBase
from kivy.utils import get_color_from_hex, platform as KIVY_PLATFORM

# Android konum izni: GPS başlatılmadan önce çalışma zamanı iznini ister.
# Windows/iOS tarafında bu import kullanılmaz.
def _request_android_location_permission(callback):
    if KIVY_PLATFORM != "android":
        callback(True)
        return
    try:
        from android.permissions import request_permissions, Permission, check_permission
        perms = [Permission.ACCESS_FINE_LOCATION, Permission.ACCESS_COARSE_LOCATION]
        try:
            already = all(check_permission(p) for p in perms)
        except Exception:
            already = False
        if already:
            callback(True)
            return
        def permission_callback(permissions, grants):
            # Android 12+ cihazlarda yaklaşık konum bile yeterli olabilir;
            # mümkünse hassas konumu tercih ederiz.
            granted = any(bool(g) for g in grants) if grants else False
            Clock.schedule_once(lambda *_: callback(granted), 0)
        request_permissions(perms, permission_callback)
    except Exception as e:
        print("Android konum izni istenemedi:", e)
        callback(False)
from kivy.graphics import Color, Rectangle, Ellipse, Line, RoundedRectangle
from kivy.uix.widget import Widget
from kivy.uix.image import Image
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.popup import Popup
from kivy.uix.slider import Slider
from kivy.uix.image import AsyncImage


# ============================================================
# MODERN YAZI TİPİ / BUTONLAR
# ============================================================

# Önce uygulamayla birlikte gelen fontları kullan; böylece Windows/iOS/Android
# arasında tipografi değişmez. Fallback olarak Segoe UI/Roboto kullanılır.
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
_FONT_CANDIDATES = [
    os.path.join(_APP_DIR, "fonts", "Inter-Regular.ttf"),
    os.path.join(_APP_DIR, "fonts", "Inter-VariableFont_opsz,wght.ttf"),
    os.path.join(_APP_DIR, "fonts", "Manrope-Regular.ttf"),
    os.path.join(_APP_DIR, "fonts", "Poppins-Regular.ttf"),
    r"C:\Windows\Fonts\segoeui.ttf",
]
FONT_NAME = "Roboto"
for _font_path in _FONT_CANDIDATES:
    if os.path.exists(_font_path):
        try:
            LabelBase.register(name="WeatherFont", fn_regular=_font_path)
            FONT_NAME = "WeatherFont"
            break
        except Exception:
            pass


class ModernLabel(Label):
    def __init__(self, **kwargs):
        kwargs.setdefault("font_name", FONT_NAME)
        super().__init__(**kwargs)


class ModernButton(Button):
    def __init__(self, **kwargs):
        kwargs.setdefault("font_name", FONT_NAME)
        kwargs.setdefault("font_size", "12sp")
        kwargs.setdefault("background_normal", "")
        kwargs.setdefault("background_down", "")
        kwargs.setdefault("border", (0, 0, 0, 0))
        kwargs.setdefault("bold", True)
        kwargs.setdefault("color", (0.92, 0.95, 1, 1))
        super().__init__(**kwargs)
        with self.canvas.before:
            self._button_color = Color(1, 1, 1, 1)
            self._button_rect = RoundedRectangle(
                pos=self.pos, size=self.size, radius=[dp(9)]
            )
        self.bind(
            pos=self._sync_button,
            size=self._sync_button,
            background_color=self._sync_button,
            state=self._sync_button,
        )
        self._sync_button()

    def _sync_button(self, *_):
        c = list(self.background_color or (0.08, 0.12, 0.18, 1))
        if len(c) < 4:
            c += [1] * (4 - len(c))
        if self.disabled:
            c[3] *= 0.82
            c[:3] = [min(1, x * 0.92) for x in c[:3]]
        elif self.state == "down":
            c[:3] = [min(1, x * 0.78) for x in c[:3]]
        self._button_color.rgba = tuple(c)
        self._button_rect.pos = self.pos
        self._button_rect.size = self.size


# ============================================================
# PENCERE
# ============================================================

Window.size = (380, 670)
Window.minimum_width = 320
Window.minimum_height = 560
Window.clearcolor = get_color_from_hex("#07101C")


# ============================================================
# DİL
# ============================================================

TR = {
    "title": "Hava Durumu",
    "country": "Ülke",
    "province": "İl",
    "district": "İlçe",
    "search": "Ara...",
    "details": "HAVA DURUMU DETAYLARI",
    "max": "Maks Sıcaklık",
    "min": "Min Sıcaklık",
    "status": "Hava Durumu",
    "humidity": "Hava Nemi",
    "pressure": "Basınç",
    "wind": "Rüzgar Hızı",
    "visibility": "Görüş Mesafesi",
    "rain": "Yağış Oranı",
    "forecast": "30 GÜNLÜK TAHMİN",
    "today": "BUGÜN",
    "select_country": "Ülke Seçiniz",
    "select_province": "İl Seçiniz",
    "select_district": "İlçe Seçiniz",
    "loading": "Yükleniyor...",
    "no_data": "Veri alınamadı",
    "no_internet": "İnternet bağlantısı yok",
    "close": "Kapat",
    "clear": "Açık Hava",
    "partly": "Parçalı Bulutlu",
    "cloudy": "Bulutlu",
    "fog": "Sisli",
    "rainy": "Yağmurlu",
    "snowy": "Karlı",
    "showers": "Sağanak",
    "storm": "Fırtına",
    "seasonal": "Uzun vadeli eğilim",
    "location": "Konum seçiniz",
    "language": "Dil",
    "favorites": "Favoriler",
    "save_current": "＋ Mevcut konumu kaydet",
    "no_favorites": "Henüz kayıtlı konum yok.",
    "search_min_chars": "En az 2 karakter yazın",
    "results_count": "{count} sonuç",
    "location_denied": "Konum izni verilmedi",
    "location_loading": "Konumunuz bulunuyor...",
    "weather_error": "Hava durumu verileri yenilenemedi.",
    "weather_error_detail": "Hava durumu verilerini yenileyemedik.\nBağlantınızı kontrol edip tekrar deneyin.",
    "retry": "Tekrar Dene",
}

EN = {
    "title": "Metevra Weather",
    "country": "Country",
    "province": "State / Province",
    "district": "City / District",
    "search": "Search...",
    "details": "WEATHER DETAILS",
    "max": "Max Temp",
    "min": "Min Temp",
    "status": "Weather",
    "humidity": "Humidity",
    "pressure": "Pressure",
    "wind": "Wind Speed",
    "visibility": "Visibility",
    "rain": "Precipitation",
    "forecast": "30 DAY OUTLOOK",
    "today": "TODAY",
    "select_country": "Select Country",
    "select_province": "Select Province",
    "select_district": "Select City",
    "loading": "Loading...",
    "no_data": "No data",
    "no_internet": "No internet connection",
    "close": "Close",
    "clear": "Clear Sky",
    "partly": "Partly Cloudy",
    "cloudy": "Cloudy",
    "fog": "Foggy",
    "rainy": "Rainy",
    "snowy": "Snowy",
    "showers": "Rain Showers",
    "storm": "Thunderstorm",
    "seasonal": "Long-range trend",
    "location": "Select a location",
    "language": "Language",
    "favorites": "Favorites",
    "save_current": "＋ Save current",
    "no_favorites": "No saved locations yet.",
    "search_min_chars": "Type at least 2 characters",
    "results_count": "{count} results",
    "location_denied": "Location permission was denied",
    "location_loading": "Finding your location...",
    "weather_error": "We could not refresh weather data.",
    "weather_error_detail": "We could not refresh weather data.\nCheck your connection and try again.",
    "retry": "Try Again",
}


# ============================================================
# ÇOKLU DİL SİSTEMİ
# ============================================================
# Uygulamanın arayüzü seçilen ülkenin yaygın diline otomatik uyarlanır.
# Kullanıcı ayrıca Dil düğmesinden desteklenen diller arasında seçim yapabilir.

# Ülke -> arayüz dili eşlemesi. Tanımsız ülkeler global varsayılan olan EN
# dilinde kalır. Bu değişken ülke seçimi callback'inden ÖNCE tanımlanmalıdır.
COUNTRY_LANGUAGE_MAP = {
    "TR":"TR", "DE":"DE", "AT":"DE", "CH":"DE", "LI":"DE",
    "FR":"FR", "BE":"FR", "LU":"FR", "MC":"FR",
    "ES":"ES", "MX":"ES", "AR":"ES", "CL":"ES", "CO":"ES", "PE":"ES",
    "IT":"IT", "SM":"IT", "VA":"IT",
    "PT":"PT", "BR":"PT",
    "RU":"RU", "BY":"RU", "KZ":"RU", "KG":"RU",
    "UA":"UK",
    "NL":"NL",
    "PL":"PL",
    "GR":"EL",
    "RO":"RO", "MD":"RO",
    "BG":"BG",
    "RS":"SR", "ME":"SR", "BA":"SR",
    "SA":"AR", "AE":"AR", "QA":"AR", "EG":"AR", "JO":"AR", "KW":"AR", "OM":"AR", "BH":"AR", "IQ":"AR", "MA":"AR", "DZ":"AR", "TN":"AR",
    "CN":"ZH", "TW":"ZH", "HK":"ZH", "MO":"ZH",
    "JP":"JA",
    "KR":"KO",
    "IN":"HI",
    "ID":"ID",
    "TH":"TH",
    "VN":"VI",
    "IL":"HE",
    "IR":"FA",
    "US":"EN", "GB":"EN", "CA":"EN", "AU":"EN", "NZ":"EN",
    "IE":"EN", "ZA":"EN", "SG":"EN", "PH":"EN", "MY":"EN",
    "KKTC":"TR",
}

LANG_PACKS = {
    "TR": TR,
    "EN": EN,
    "DE": dict(EN, title="Wetter", country="Land", province="Bundesland", district="Stadt / Bezirk", search="Suchen...", details="WETTERDETAILS", max="Max. Temperatur", min="Min. Temperatur", status="Wetter", humidity="Luftfeuchtigkeit", pressure="Luftdruck", wind="Windgeschwindigkeit", visibility="Sichtweite", rain="Niederschlag", forecast="30-TAGE-PROGNOSE", today="HEUTE", select_country="Land auswählen", select_province="Bundesland auswählen", select_district="Stadt auswählen", loading="Wird geladen...", no_data="Keine Daten", no_internet="Keine Internetverbindung", close="Schließen", clear="Klarer Himmel", partly="Teilweise bewölkt", cloudy="Bewölkt", fog="Nebelig", rainy="Regnerisch", snowy="Schnee", showers="Regenschauer", storm="Gewitter", seasonal="Langfristiger Trend", location="Ort auswählen"),
    "FR": dict(EN, title="Météo", country="Pays", province="Région", district="Ville / District", search="Rechercher...", details="DÉTAILS MÉTÉO", max="Temp. max", min="Temp. min", status="Météo", humidity="Humidité", pressure="Pression", wind="Vitesse du vent", visibility="Visibilité", rain="Précipitations", forecast="PRÉVISIONS À 30 JOURS", today="AUJOURD'HUI", select_country="Choisir un pays", select_province="Choisir une région", select_district="Choisir une ville", loading="Chargement...", no_data="Aucune donnée", no_internet="Pas de connexion Internet", close="Fermer", clear="Ciel dégagé", partly="Partiellement nuageux", cloudy="Nuageux", fog="Brouillard", rainy="Pluvieux", snowy="Neigeux", showers="Averses", storm="Orage", seasonal="Tendance à long terme", location="Choisir un lieu"),
    "ES": dict(EN, title="Tiempo", country="País", province="Provincia", district="Ciudad / Distrito", search="Buscar...", details="DETALLES DEL TIEMPO", max="Temp. máx.", min="Temp. mín.", status="Tiempo", humidity="Humedad", pressure="Presión", wind="Velocidad del viento", visibility="Visibilidad", rain="Precipitación", forecast="PRONÓSTICO DE 30 DÍAS", today="HOY", select_country="Seleccionar país", select_province="Seleccionar provincia", select_district="Seleccionar ciudad", loading="Cargando...", no_data="Sin datos", no_internet="Sin conexión a Internet", close="Cerrar", clear="Cielo despejado", partly="Parcialmente nublado", cloudy="Nublado", fog="Niebla", rainy="Lluvioso", snowy="Nevado", showers="Chubascos", storm="Tormenta", seasonal="Tendencia a largo plazo", location="Seleccionar ubicación"),
    "IT": dict(EN, title="Meteo", country="Paese", province="Regione", district="Città / Distretto", search="Cerca...", details="DETTAGLI METEO", max="Temp. max", min="Temp. min", status="Meteo", humidity="Umidità", pressure="Pressione", wind="Velocità del vento", visibility="Visibilità", rain="Precipitazioni", forecast="PREVISIONI 30 GIORNI", today="OGGI", select_country="Seleziona paese", select_province="Seleziona regione", select_district="Seleziona città", loading="Caricamento...", no_data="Nessun dato", no_internet="Nessuna connessione Internet", close="Chiudi", clear="Cielo sereno", partly="Parzialmente nuvoloso", cloudy="Nuvoloso", fog="Nebbia", rainy="Piovoso", snowy="Nevoso", showers="Rovesci", storm="Temporale", seasonal="Tendenza a lungo termine", location="Seleziona località"),
    "PT": dict(EN, title="Clima", country="País", province="Estado / Província", district="Cidade / Distrito", search="Pesquisar...", details="DETALHES DO TEMPO", max="Temp. máx.", min="Temp. mín.", status="Tempo", humidity="Humidade", pressure="Pressão", wind="Velocidade do vento", visibility="Visibilidade", rain="Precipitação", forecast="PREVISÃO DE 30 DIAS", today="HOJE", select_country="Selecionar país", select_province="Selecionar estado", select_district="Selecionar cidade", loading="A carregar...", no_data="Sem dados", no_internet="Sem ligação à Internet", close="Fechar", clear="Céu limpo", partly="Parcialmente nublado", cloudy="Nublado", fog="Nevoeiro", rainy="Chuvoso", snowy="Nevado", showers="Aguaceiros", storm="Trovoada", seasonal="Tendência de longo prazo", location="Selecionar local"),
    "RU": dict(EN, title="Погода", country="Страна", province="Регион", district="Город / Район", search="Поиск...", details="ДЕТАЛИ ПОГОДЫ", max="Макс. температура", min="Мин. температура", status="Погода", humidity="Влажность", pressure="Давление", wind="Скорость ветра", visibility="Видимость", rain="Осадки", forecast="ПРОГНОЗ НА 30 ДНЕЙ", today="СЕГОДНЯ", select_country="Выберите страну", select_province="Выберите регион", select_district="Выберите город", loading="Загрузка...", no_data="Нет данных", no_internet="Нет подключения к интернету", close="Закрыть", clear="Ясно", partly="Переменная облачность", cloudy="Облачно", fog="Туман", rainy="Дождь", snowy="Снег", showers="Ливни", storm="Гроза", seasonal="Долгосрочная тенденция", location="Выберите место"),
    "AR": dict(EN, title="الطقس", country="الدولة", province="المنطقة", district="المدينة / المنطقة", search="بحث...", details="تفاصيل الطقس", max="أعلى حرارة", min="أدنى حرارة", status="الطقس", humidity="الرطوبة", pressure="الضغط", wind="سرعة الرياح", visibility="الرؤية", rain="الهطول", forecast="توقعات 30 يومًا", today="اليوم", select_country="اختر الدولة", select_province="اختر المنطقة", select_district="اختر المدينة", loading="جار التحميل...", no_data="لا توجد بيانات", no_internet="لا يوجد اتصال بالإنترنت", close="إغلاق", clear="سماء صافية", partly="غائم جزئيًا", cloudy="غائم", fog="ضباب", rainy="ممطر", snowy="ثلجي", showers="زخات مطر", storm="عاصفة رعدية", seasonal="اتجاه طويل المدى", location="اختر الموقع"),
    "ZH": dict(EN, title="天气", country="国家", province="省 / 州", district="城市 / 地区", search="搜索...", details="天气详情", max="最高温度", min="最低温度", status="天气", humidity="湿度", pressure="气压", wind="风速", visibility="能见度", rain="降水", forecast="30天预报", today="今天", select_country="选择国家", select_province="选择省份", select_district="选择城市", loading="加载中...", no_data="暂无数据", no_internet="无网络连接", close="关闭", clear="晴朗", partly="局部多云", cloudy="多云", fog="雾", rainy="有雨", snowy="下雪", showers="阵雨", storm="雷暴", seasonal="长期趋势", location="选择位置"),
    "JA": dict(EN, title="天気", country="国", province="都道府県 / 州", district="都市 / 地区", search="検索...", details="天気の詳細", max="最高気温", min="最低気温", status="天気", humidity="湿度", pressure="気圧", wind="風速", visibility="視程", rain="降水確率", forecast="30日予報", today="今日", select_country="国を選択", select_province="地域を選択", select_district="都市を選択", loading="読み込み中...", no_data="データなし", no_internet="インターネット接続なし", close="閉じる", clear="快晴", partly="晴れ時々曇り", cloudy="曇り", fog="霧", rainy="雨", snowy="雪", showers="にわか雨", storm="雷雨", seasonal="長期傾向", location="場所を選択"),
    "KO": dict(EN, title="날씨", country="국가", province="주 / 지역", district="도시 / 지역", search="검색...", details="날씨 상세", max="최고 기온", min="최저 기온", status="날씨", humidity="습도", pressure="기압", wind="풍속", visibility="가시거리", rain="강수량", forecast="30일 예보", today="오늘", select_country="국가 선택", select_province="지역 선택", select_district="도시 선택", loading="불러오는 중...", no_data="데이터 없음", no_internet="인터넷 연결 없음", close="닫기", clear="맑음", partly="구름 조금", cloudy="흐림", fog="안개", rainy="비", snowy="눈", showers="소나기", storm="뇌우", seasonal="장기 추세", location="위치 선택"),
    "NL": dict(EN, title="Weer", country="Land", province="Provincie", district="Stad / District", search="Zoeken...", details="WEERDETAILS", max="Max. temperatuur", min="Min. temperatuur", status="Weer", humidity="Luchtvochtigheid", pressure="Luchtdruk", wind="Windsnelheid", visibility="Zicht", rain="Neerslag", forecast="30-DAAGSE VERWACHTING", today="VANDAAG", select_country="Kies land", select_province="Kies provincie", select_district="Kies stad", loading="Laden...", no_data="Geen gegevens", no_internet="Geen internetverbinding", close="Sluiten", clear="Onbewolkt", partly="Gedeeltelijk bewolkt", cloudy="Bewolkt", fog="Mist", rainy="Regenachtig", snowy="Sneeuw", showers="Regenbuien", storm="Onweer", seasonal="Langetermijntrend", location="Kies locatie"),
    "PL": dict(EN, title="Pogoda", country="Kraj", province="Województwo / Region", district="Miasto / Okręg", search="Szukaj...", details="SZCZEGÓŁY POGODY", max="Maks. temperatura", min="Min. temperatura", status="Pogoda", humidity="Wilgotność", pressure="Ciśnienie", wind="Prędkość wiatru", visibility="Widoczność", rain="Opady", forecast="PROGNOZA 30-DNIOWA", today="DZISIAJ", select_country="Wybierz kraj", select_province="Wybierz region", select_district="Wybierz miasto", loading="Ładowanie...", no_data="Brak danych", no_internet="Brak połączenia z internetem", close="Zamknij", clear="Bezchmurnie", partly="Częściowe zachmurzenie", cloudy="Pochmurno", fog="Mgła", rainy="Deszczowo", snowy="Śnieg", showers="Przelotny deszcz", storm="Burza", seasonal="Trend długoterminowy", location="Wybierz lokalizację"),
    "EL": dict(EN, title="Καιρός", country="Χώρα", province="Περιφέρεια", district="Πόλη / Περιοχή", search="Αναζήτηση...", details="ΛΕΠΤΟΜΕΡΕΙΕΣ ΚΑΙΡΟΥ", max="Μέγιστη θερμοκρασία", min="Ελάχιστη θερμοκρασία", status="Καιρός", humidity="Υγρασία", pressure="Πίεση", wind="Ταχύτητα ανέμου", visibility="Ορατότητα", rain="Υετός", forecast="ΠΡΟΓΝΩΣΗ 30 ΗΜΕΡΩΝ", today="ΣΗΜΕΡΑ", select_country="Επιλογή χώρας", select_province="Επιλογή περιοχής", select_district="Επιλογή πόλης", loading="Φόρτωση...", no_data="Χωρίς δεδομένα", no_internet="Χωρίς σύνδεση στο διαδίκτυο", close="Κλείσιμο", clear="Αίθριος", partly="Μερική συννεφιά", cloudy="Συννεφιασμένος", fog="Ομίχλη", rainy="Βροχή", snowy="Χιόνι", showers="Μπόρες", storm="Καταιγίδα", seasonal="Μακροπρόθεσμη τάση", location="Επιλογή τοποθεσίας"),
    "RO": dict(EN, title="Vremea", country="Țară", province="Regiune", district="Oraș / District", search="Caută...", details="DETALII METEO", max="Temp. maximă", min="Temp. minimă", status="Vremea", humidity="Umiditate", pressure="Presiune", wind="Viteza vântului", visibility="Vizibilitate", rain="Precipitații", forecast="PROGNOZA PE 30 DE ZILE", today="ASTĂZI", select_country="Alege țara", select_province="Alege regiunea", select_district="Alege orașul", loading="Se încarcă...", no_data="Fără date", no_internet="Fără conexiune la internet", close="Închide", clear="Cer senin", partly="Parțial noros", cloudy="Noros", fog="Ceață", rainy="Ploios", snowy="Ninsoare", showers="Averse", storm="Furtună", seasonal="Tendință pe termen lung", location="Alege locația"),
    "BG": dict(EN, title="Времето", country="Държава", province="Област", district="Град / Район", search="Търсене...", details="ПОДРОБНОСТИ ЗА ВРЕМЕТО", max="Макс. температура", min="Мин. температура", status="Време", humidity="Влажност", pressure="Налягане", wind="Скорост на вятъра", visibility="Видимост", rain="Валежи", forecast="30-ДНЕВНА ПРОГНОЗА", today="ДНЕС", select_country="Изберете държава", select_province="Изберете област", select_district="Изберете град", loading="Зареждане...", no_data="Няма данни", no_internet="Няма интернет връзка", close="Затвори", clear="Ясно", partly="Разкъсана облачност", cloudy="Облачно", fog="Мъгла", rainy="Дъждовно", snowy="Сняг", showers="Валежи", storm="Буря", seasonal="Дългосрочна тенденция", location="Изберете място"),
    "SR": dict(EN, title="Vreme", country="Država", province="Pokrajina / Region", district="Grad / Okrug", search="Pretraga...", details="DETALJI VREMENA", max="Maks. temperatura", min="Min. temperatura", status="Vreme", humidity="Vlažnost", pressure="Pritisak", wind="Brzina vetra", visibility="Vidljivost", rain="Padavine", forecast="PROGNOZA 30 DANA", today="DANAS", select_country="Izaberite državu", select_province="Izaberite region", select_district="Izaberite grad", loading="Učitavanje...", no_data="Nema podataka", no_internet="Nema internet veze", close="Zatvori", clear="Vedro", partly="Delimično oblačno", cloudy="Oblačno", fog="Magla", rainy="Kišovito", snowy="Sneg", showers="Pljuskovi", storm="Oluja", seasonal="Dugoročni trend", location="Izaberite lokaciju"),
    "UK": dict(EN, title="Погода", country="Країна", province="Область", district="Місто / Район", search="Пошук...", details="ДЕТАЛІ ПОГОДИ", max="Макс. температура", min="Мін. температура", status="Погода", humidity="Вологість", pressure="Тиск", wind="Швидкість вітру", visibility="Видимість", rain="Опади", forecast="ПРОГНОЗ НА 30 ДНІВ", today="СЬОГОДНІ", select_country="Оберіть країну", select_province="Оберіть область", select_district="Оберіть місто", loading="Завантаження...", no_data="Немає даних", no_internet="Немає підключення до Інтернету", close="Закрити", clear="Ясно", partly="Мінлива хмарність", cloudy="Хмарно", fog="Туман", rainy="Дощ", snowy="Сніг", showers="Зливи", storm="Гроза", seasonal="Довгострокова тенденція", location="Оберіть місце"),
    "HE": dict(EN, title="מזג האוויר", country="מדינה", province="מחוז", district="עיר / אזור", search="חיפוש...", details="פרטי מזג האוויר", max="טמפרטורה מרבית", min="טמפרטורה מינימלית", status="מזג האוויר", humidity="לחות", pressure="לחץ", wind="מהירות רוח", visibility="ראות", rain="משקעים", forecast="תחזית ל-30 יום", today="היום", select_country="בחר מדינה", select_province="בחר אזור", select_district="בחר עיר", loading="טוען...", no_data="אין נתונים", no_internet="אין חיבור לאינטרנט", close="סגור", clear="שמיים בהירים", partly="מעונן חלקית", cloudy="מעונן", fog="ערפל", rainy="גשום", snowy="שלג", showers="ממטרים", storm="סופת רעמים", seasonal="מגמה ארוכת טווח", location="בחר מיקום"),
    "HI": dict(EN, title="मौसम", country="देश", province="राज्य / प्रांत", district="शहर / ज़िला", search="खोजें...", details="मौसम विवरण", max="अधिकतम तापमान", min="न्यूनतम तापमान", status="मौसम", humidity="नमी", pressure="दाब", wind="हवा की गति", visibility="दृश्यता", rain="वर्षा", forecast="30 दिन का पूर्वानुमान", today="आज", select_country="देश चुनें", select_province="राज्य चुनें", select_district="शहर चुनें", loading="लोड हो रहा है...", no_data="कोई डेटा नहीं", no_internet="इंटरनेट कनेक्शन नहीं", close="बंद करें", clear="साफ़ आकाश", partly="आंशिक बादल", cloudy="बादल", fog="कोहरा", rainy="बारिश", snowy="बर्फ़", showers="बौछारें", storm="तूफ़ान", seasonal="दीर्घकालिक रुझान", location="स्थान चुनें"),
    "ID": dict(EN, title="Cuaca", country="Negara", province="Provinsi", district="Kota / Distrik", search="Cari...", details="DETAIL CUACA", max="Suhu Maks", min="Suhu Min", status="Cuaca", humidity="Kelembapan", pressure="Tekanan", wind="Kecepatan Angin", visibility="Jarak Pandang", rain="Curah Hujan", forecast="PRAKIRAAN 30 HARI", today="HARI INI", select_country="Pilih negara", select_province="Pilih provinsi", select_district="Pilih kota", loading="Memuat...", no_data="Tidak ada data", no_internet="Tidak ada koneksi internet", close="Tutup", clear="Cerah", partly="Berawan sebagian", cloudy="Berawan", fog="Berkabut", rainy="Hujan", snowy="Salju", showers="Hujan deras", storm="Badai petir", seasonal="Tren jangka panjang", location="Pilih lokasi"),
    "TH": dict(EN, title="สภาพอากาศ", country="ประเทศ", province="จังหวัด / ภูมิภาค", district="เมือง / เขต", search="ค้นหา...", details="รายละเอียดสภาพอากาศ", max="อุณหภูมิสูงสุด", min="อุณหภูมิต่ำสุด", status="สภาพอากาศ", humidity="ความชื้น", pressure="ความกดอากาศ", wind="ความเร็วลม", visibility="ทัศนวิสัย", rain="ปริมาณฝน", forecast="พยากรณ์ 30 วัน", today="วันนี้", select_country="เลือกประเทศ", select_province="เลือกภูมิภาค", select_district="เลือกเมือง", loading="กำลังโหลด...", no_data="ไม่มีข้อมูล", no_internet="ไม่มีการเชื่อมต่ออินเทอร์เน็ต", close="ปิด", clear="ท้องฟ้าแจ่มใส", partly="มีเมฆบางส่วน", cloudy="มีเมฆมาก", fog="มีหมอก", rainy="ฝนตก", snowy="หิมะ", showers="ฝนตกหนัก", storm="พายุฝนฟ้าคะนอง", seasonal="แนวโน้มระยะยาว", location="เลือกสถานที่"),
    "VI": dict(EN, title="Thời tiết", country="Quốc gia", province="Tỉnh / Khu vực", district="Thành phố / Quận", search="Tìm kiếm...", details="CHI TIẾT THỜI TIẾT", max="Nhiệt độ cao nhất", min="Nhiệt độ thấp nhất", status="Thời tiết", humidity="Độ ẩm", pressure="Áp suất", wind="Tốc độ gió", visibility="Tầm nhìn", rain="Lượng mưa", forecast="DỰ BÁO 30 NGÀY", today="HÔM NAY", select_country="Chọn quốc gia", select_province="Chọn tỉnh", select_district="Chọn thành phố", loading="Đang tải...", no_data="Không có dữ liệu", no_internet="Không có kết nối Internet", close="Đóng", clear="Trời quang", partly="Có mây một phần", cloudy="Nhiều mây", fog="Sương mù", rainy="Mưa", snowy="Tuyết", showers="Mưa rào", storm="Giông bão", seasonal="Xu hướng dài hạn", location="Chọn vị trí"),
    "FA": dict(EN, title="آب‌وهوا", country="کشور", province="استان / منطقه", district="شهر / ناحیه", search="جستجو...", details="جزئیات آب‌وهوا", max="حداکثر دما", min="حداقل دما", status="آب‌وهوا", humidity="رطوبت", pressure="فشار", wind="سرعت باد", visibility="دید", rain="بارش", forecast="پیش‌بینی ۳۰ روزه", today="امروز", select_country="انتخاب کشور", select_province="انتخاب منطقه", select_district="انتخاب شهر", loading="در حال بارگذاری...", no_data="بدون داده", no_internet="بدون اتصال اینترنت", close="بستن", clear="آسمان صاف", partly="نیمه ابری", cloudy="ابری", fog="مه‌آلود", rainy="بارانی", snowy="برفی", showers="رگبار", storm="طوفان", seasonal="روند بلندمدت", location="انتخاب مکان"),
}

# Yeni ortak UI metinleri: eski dil paketlerinde bulunmayan anahtarlar için güvenli fallback.
_COMMON_UI_TEXT = {
    "search_min_chars": {"TR":"En az 2 karakter yazın", "EN":"Type at least 2 characters"},
    "results_count": {"TR":"{count} sonuç", "EN":"{count} results"},
    "location_denied": {"TR":"Konum izni verilmedi", "EN":"Location permission was denied"},
    "location_loading": {"TR":"Konumunuz bulunuyor...", "EN":"Finding your location..."},
    "weather_error": {"TR":"Hava durumu verileri yenilenemedi.", "EN":"We could not refresh weather data."},
    "weather_error_detail": {"TR":"Hava durumu verilerini yenileyemedik.\nBağlantınızı kontrol edip tekrar deneyin.", "EN":"We could not refresh weather data.\nCheck your connection and try again."},
    "retry": {"TR":"Tekrar Dene", "EN":"Try Again"},
}
for _lang_code, _pack in LANG_PACKS.items():
    for _key, _values in _COMMON_UI_TEXT.items():
        _pack.setdefault(_key, _values.get(_lang_code, _values["EN"]))


# Ülke -> varsayılan arayüz dili. Haritada bulunmayan ülkeler İngilizceye düşer.
COUNTRY_LANGUAGE = {
    "TR":"TR","KKTC":"TR","DE":"DE","AT":"DE","CH":"DE","LI":"DE",
    "FR":"FR","BE":"FR","MC":"FR","LU":"FR","ES":"ES","MX":"ES","AR":"ES","CL":"ES","CO":"ES","PE":"ES","PT":"PT","BR":"PT",
    "IT":"IT","SM":"IT","VA":"IT","RU":"RU","BY":"RU","KZ":"RU","KG":"RU","UZ":"RU",
    "SA":"AR","AE":"AR","QA":"AR","KW":"AR","BH":"AR","OM":"AR","JO":"AR","IQ":"AR","EG":"AR","MA":"AR","DZ":"AR","TN":"AR","LY":"AR",
    "CN":"ZH","TW":"ZH","HK":"ZH","MO":"ZH","JP":"JA","KR":"KO","NL":"NL","PL":"PL","GR":"EL","CY":"EL",
    "RO":"RO","BG":"BG","RS":"SR","ME":"SR","UA":"UK","IL":"HE","IN":"HI","ID":"ID","TH":"TH","VN":"VI","IR":"FA"
}

LANGUAGE_ITEMS = [
    {"name":"Türkçe — Türkçe", "code":"TR"}, {"name":"English — English", "code":"EN"},
    {"name":"Deutsch — Deutsch", "code":"DE"}, {"name":"Français — Français", "code":"FR"},
    {"name":"Español — Español", "code":"ES"}, {"name":"Italiano — Italiano", "code":"IT"},
    {"name":"Português — Português", "code":"PT"}, {"name":"Русский — Русский", "code":"RU"},
    {"name":"العربية — العربية", "code":"AR"}, {"name":"中文 — 简体中文", "code":"ZH"},
    {"name":"日本語 — 日本語", "code":"JA"}, {"name":"한국어 — 한국어", "code":"KO"},
    {"name":"Nederlands — Nederlands", "code":"NL"}, {"name":"Polski — Polski", "code":"PL"},
    {"name":"Ελληνικά — Ελληνικά", "code":"EL"}, {"name":"Română — Română", "code":"RO"},
    {"name":"Български — Български", "code":"BG"}, {"name":"Srpski — Srpski", "code":"SR"},
    {"name":"Українська — Українська", "code":"UK"}, {"name":"עברית — עברית", "code":"HE"},
    {"name":"हिन्दी — हिन्दी", "code":"HI"}, {"name":"Bahasa Indonesia — Indonesia", "code":"ID"},
    {"name":"ไทย — ไทย", "code":"TH"}, {"name":"Tiếng Việt — Việt Nam", "code":"VI"},
    {"name":"فارسی — فارسی", "code":"FA"},
]


# Alt menü etiketleri: seçilen arayüz diliyle birlikte DAİMA güncellenir.
NAV_TEXT = {
    "TR": ("Ana Sayfa", "Arama", "Harita", "Favoriler", "Ayarlar"),
    "EN": ("Home", "Search", "Map", "Favorites", "Settings"),
    "DE": ("Startseite", "Suche", "Karte", "Favoriten", "Einstellungen"),
    "FR": ("Accueil", "Recherche", "Carte", "Favoris", "Paramètres"),
    "ES": ("Inicio", "Buscar", "Mapa", "Favoritos", "Ajustes"),
    "IT": ("Home", "Cerca", "Mappa", "Preferiti", "Impostazioni"),
    "PT": ("Início", "Pesquisar", "Mapa", "Favoritos", "Definições"),
    "RU": ("Главная", "Поиск", "Карта", "Избранное", "Настройки"),
    "AR": ("الرئيسية", "بحث", "الخريطة", "المفضلة", "الإعدادات"),
    "ZH": ("首页", "搜索", "地图", "收藏", "设置"),
    "JA": ("ホーム", "検索", "地図", "お気に入り", "設定"),
    "KO": ("홈", "검색", "지도", "즐겨찾기", "설정"),
    "NL": ("Home", "Zoeken", "Kaart", "Favorieten", "Instellingen"),
    "PL": ("Start", "Szukaj", "Mapa", "Ulubione", "Ustawienia"),
    "EL": ("Αρχική", "Αναζήτηση", "Χάρτης", "Αγαπημένα", "Ρυθμίσεις"),
    "RO": ("Acasă", "Căutare", "Hartă", "Favorite", "Setări"),
    "BG": ("Начало", "Търсене", "Карта", "Любими", "Настройки"),
    "SR": ("Početna", "Pretraga", "Mapa", "Omiljeno", "Podešavanja"),
    "UK": ("Головна", "Пошук", "Карта", "Обране", "Налаштування"),
    "HE": ("בית", "חיפוש", "מפה", "מועדפים", "הגדרות"),
    "HI": ("होम", "खोजें", "मानचित्र", "पसंदीदा", "सेटिंग्स"),
    "ID": ("Beranda", "Cari", "Peta", "Favorit", "Pengaturan"),
    "TH": ("หน้าหลัก", "ค้นหา", "แผนที่", "รายการโปรด", "การตั้งค่า"),
    "VI": ("Trang chủ", "Tìm kiếm", "Bản đồ", "Yêu thích", "Cài đặt"),
    "FA": ("خانه", "جستجو", "نقشه", "موارد دلخواه", "تنظیمات"),
}




# ============================================================
# HAVA DURUMU AÇIKLAMA
# ============================================================

def weather_text(code, lang):
    d = LANG_PACKS.get(lang, EN)
    try:
        code = int(code) if code is not None else 3
    except (TypeError, ValueError):
        code = 3

    if code == 0:
        return d["clear"]
    if code in (1, 2):
        return d["partly"]
    if code == 3:
        return d["cloudy"]
    if code in (45, 48):
        return d["fog"]
    if code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67):
        return d["rainy"]
    if code in (71, 73, 75, 77, 85, 86):
        return d["snowy"]
    if code in (80, 81, 82):
        return d["showers"]
    if code in (95, 96, 99):
        return d["storm"]

    return d["cloudy"]


def season_name(month):
    if month in (12, 1, 2):
        return "winter"
    if month in (3, 4, 5):
        return "spring"
    if month in (6, 7, 8):
        return "summer"
    return "autumn"


# ============================================================
# HAREKETLİ HAVA ARKA PLANI
# ============================================================

class WeatherBackground(FloatLayout):
    """İnternetten rastgele fotoğraf çekmek yerine konum + mevsim + hava
    durumuna göre yerel, yapay/sinematik bir sahne üretir. Üzerine gerçek
    zamanlı yağmur, kar, bulut, yıldırım ve güneş/ay efektleri eklenir.
    """
    RAIN_CODES = (51,53,55,56,57,61,63,65,66,67,80,81,82,95,96,99)
    SNOW_CODES = (71,73,75,77,85,86)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.code = 3
        self.is_day = True
        self.season = season_name(datetime.now().month)
        self.location_query = "Turkey"
        self.location_lat = None
        self.location_lon = None
        self.request_token = 0
        self.particles = []
        self.lightning = 0.0
        self.clouds = [
            {"x":0.08,"y":0.78,"speed":0.010,"scale":1.0},
            {"x":0.60,"y":0.64,"speed":-0.006,"scale":0.72},
            {"x":0.35,"y":0.50,"speed":0.004,"scale":0.55},
        ]
        self.cache_dir = os.path.join(os.path.expanduser("~"), ".kivy", "weather_generated")
        os.makedirs(self.cache_dir, exist_ok=True)
        self.photo = Image(source="", size_hint=(None,None), allow_stretch=True, keep_ratio=False)
        self.add_widget(self.photo)
        self.bind(pos=self._sync_photo, size=self._sync_photo)
        self.bind(pos=lambda *_: self.redraw(), size=lambda *_: self.redraw())
        Clock.schedule_interval(self.animate, 1/30)
        Clock.schedule_once(lambda *_: self._sync_photo(), 0)
        Clock.schedule_once(lambda *_: self.redraw(), 0)
        self.make_particles()

    def _sync_photo(self, *_):
        self.photo.pos = self.pos
        self.photo.size = self.size

    def set_location(self, location, lat=None, lon=None):
        self.location_query = str(location or "Turkey").strip()
        self.location_lat, self.location_lon = lat, lon
        self.request_token += 1
        token = self.request_token
        self.photo.source = ""
        self._generate_async(token)

    def set_weather(self, code, is_day=True):
        try: self.code = int(code) if code is not None else 3
        except Exception: self.code = 3
        self.is_day = bool(is_day)
        self.season = season_name(datetime.now().month)
        self.make_particles()
        self.redraw()
        self._generate_async(self.request_token)

    def _generate_async(self, token):
        threading.Thread(target=self._generate_scene, args=(token,), daemon=True).start()

    def _scene_palette(self, seed):
        palettes = {
            "winter": ((35,62,92),(120,150,175),(190,205,215),(55,70,82)),
            "spring": ((40,105,125),(115,180,175),(205,225,190),(45,90,65)),
            "summer": ((25,95,145),(85,175,210),(245,205,125),(35,100,85)),
            "autumn": ((80,50,48),(180,115,70),(235,170,95),(80,60,45)),
        }
        return palettes[self.season]

    def _generate_scene(self, token):
        try:
            key = f"{self.location_query}|{self.season}|{self.code}|{self.is_day}"
            path = os.path.join(self.cache_dir, hashlib.sha256(key.encode('utf-8')).hexdigest()+".png")
            if os.path.exists(path):
                if token == self.request_token: Clock.schedule_once(lambda *_: self._set_scene(path, token), 0)
                return
            W,H = 1080,1920
            seed = int(hashlib.sha256(self.location_query.encode('utf-8')).hexdigest()[:12],16)
            rnd = random.Random(seed)
            top,bottom,light,ground = self._scene_palette(seed)
            if self.code in self.RAIN_CODES:
                top = tuple(max(0,c-12) for c in top); bottom=tuple(max(0,c-18) for c in bottom)
            if self.code in self.SNOW_CODES:
                top=(65,92,120); bottom=(155,175,190); ground=(185,190,195)
            if not self.is_day: top=(8,18,34); bottom=(25,36,52)
            im=PILImage.new('RGB',(W,H)); pix=im.load()
            for y in range(H):
                t=y/(H-1); c=tuple(int(top[i]*(1-t)+bottom[i]*t) for i in range(3))
                for x in range(W): pix[x,y]=c
            d=ImageDraw.Draw(im,'RGBA')
            # cinematic sun/moon glow
            if self.is_day:
                sx=int(W*(0.74+0.08*rnd.random())); sy=int(H*0.22); r=95
                for rr in range(220,25,-10):
                    a=max(2,int(40*(1-rr/220)))
                    d.ellipse((sx-rr,sy-rr,sx+rr,sy+rr), fill=light+(a,))
                d.ellipse((sx-r,sy-r,sx+r,sy+r), fill=(255,224,145,255))
            else:
                sx=int(W*0.78); sy=int(H*0.20); r=72
                d.ellipse((sx-r,sy-r,sx+r,sy+r), fill=(238,238,205,240))
                d.ellipse((sx-r+22,sy-r-8,sx+r+22,sy+r-8), fill=(12,22,38,255))
                for _ in range(70):
                    x=rnd.randrange(W); y=rnd.randrange(int(H*.65)); d.ellipse((x,y,x+3,y+3), fill=(255,255,230,rnd.randrange(70,180)))
            # distant mountains / skyline
            horizon=int(H*0.67)
            pts=[(0,horizon)]
            for x in range(0,W+1,80):
                peak=horizon-rnd.randint(70,260)
                pts.append((x,peak))
            pts += [(W,H),(0,H)]
            d.polygon(pts, fill=ground+(235,))
            # city silhouette, unique to location hash
            city_top=int(H*0.61)
            x=0
            while x<W:
                bw=rnd.randint(35,95); bh=rnd.randint(45,230)
                y=city_top-bh
                d.rectangle((x,y,x+bw,city_top+35), fill=(8,14,22,185))
                if rnd.random()<0.18: d.polygon([(x,y),(x+bw//2,y-rnd.randint(25,75)),(x+bw,y)], fill=(8,14,22,190))
                for wx in range(x+10,x+bw-8,18):
                    if rnd.random()<0.35: d.rectangle((wx,y+15,wx+5,min(city_top,y+bh-15)), fill=(255,207,92,130))
                x += bw+8
            # foreground ground / coast depending hash
            if seed % 3 == 0:
                d.rectangle((0,int(H*.74),W,H), fill=(15,40,52,120))
                for _ in range(25):
                    yy=int(H*.75)+rnd.randint(0,300); d.line((0,yy,W,yy+rnd.randint(-4,4)), fill=(150,195,205,55), width=3)
            else:
                d.rectangle((0,int(H*.76),W,H), fill=ground+(245,))
                for _ in range(25):
                    x=rnd.randrange(W); y=int(H*.76)+rnd.randrange(250); d.ellipse((x,y,x+rnd.randint(8,28),y+rnd.randint(4,12)), fill=(35,45,35,120))
            # weather-specific atmosphere baked into image
            if self.code in (1,2,3,45,48):
                for _ in range(8):
                    cx=rnd.randint(-100,W); cy=rnd.randint(300,int(H*.65)); d.ellipse((cx,cy,cx+260,cy+75), fill=(220,230,235,35))
            if self.code in self.RAIN_CODES:
                overlay=PILImage.new('RGBA',(W,H),(30,50,70,55)); im=Image.composite(overlay, PILImage.new('RGBA',(W,H),(0,0,0,0)), overlay.getchannel('A')).convert('RGB')
                d=ImageDraw.Draw(im,'RGBA')
                for _ in range(420):
                    x=rnd.randrange(W); y=rnd.randrange(H); d.line((x,y,x-8,y+28), fill=(185,215,235,65), width=2)
            if self.code in self.SNOW_CODES:
                for _ in range(500):
                    x=rnd.randrange(W); y=rnd.randrange(H); r=rnd.randint(2,6); d.ellipse((x-r,y-r,x+r,y+r), fill=(245,250,255,rnd.randint(80,210)))
            im=im.filter(ImageFilter.GaussianBlur(0.35))
            im.save(path,'PNG',optimize=True)
            if token == self.request_token: Clock.schedule_once(lambda *_: self._set_scene(path, token), 0)
        except Exception as e:
            print('Yapay arka plan üretilemedi:', e)

    def _set_scene(self, path, token):
        if token != self.request_token or not os.path.exists(path): return
        self.photo.source=path; self.photo.pos=self.pos; self.photo.size=self.size; self.photo.reload(); self.redraw()

    def make_particles(self):
        if self.code in self.SNOW_CODES:
            self.particles=[{"x":random.random(),"y":random.random(),"s":random.uniform(.003,.010),"r":random.uniform(1.5,4.5)} for _ in range(150)]
        elif self.code in self.RAIN_CODES:
            self.particles=[{"x":random.random(),"y":random.random(),"s":random.uniform(.012,.028),"l":random.uniform(.018,.038)} for _ in range(180)]
        else:
            self.particles=[]

    def animate(self, dt):
        for c in self.clouds:
            c['x'] += c['speed']*dt
            if c['x']>1.25: c['x']=-.25
            if c['x']<-.25: c['x']=1.25
        for p in self.particles:
            p['y'] -= p['s']*dt*20
            if self.code in self.RAIN_CODES: p['x'] -= .0004*dt*20
            else: p['x'] += .0005*dt*20
            if p['y']<-.05: p['y']=1.05; p['x']=random.random()
        if self.code in (95,96,99) and random.random()<0.004: self.lightning=0.22
        self.lightning=max(0,self.lightning-dt)
        self.redraw()

    def redraw(self):
        self.canvas.after.clear(); w,h=self.size
        if w<=0 or h<=0:return
        with self.canvas.after:
            # cinematic dark veil
            Color(0.01,0.02,0.05,0.12 if self.is_day else 0.32); self.canvas.after.add(Rectangle(pos=self.pos,size=self.size))
            # moving clouds
            for c in self.clouds:
                cx=self.x+c['x']*w; cy=self.y+c['y']*h; sc=c['scale']
                Color(0.94,0.97,1,0.08 if self.code not in self.RAIN_CODES else 0.15)
                self.canvas.after.add(Ellipse(pos=(cx-90*sc,cy-22*sc),size=(180*sc,55*sc)))
                self.canvas.after.add(Ellipse(pos=(cx-35*sc,cy-42*sc),size=(100*sc,75*sc)))
            # animated precipitation
            for p in self.particles:
                x=self.x+p['x']*w; y=self.y+p['y']*h
                if self.code in self.RAIN_CODES:
                    Color(0.70,0.86,1,0.42); self.canvas.after.add(Line(points=[x,y,x-w*.008,y-h*p['l']],width=1.2))
                else:
                    Color(1,1,1,0.72); r=p['r']; self.canvas.after.add(Ellipse(pos=(x-r,y-r),size=(2*r,2*r)))
            if self.lightning>0:
                Color(1,1,1,self.lightning); self.canvas.after.add(Rectangle(pos=self.pos,size=self.size))



# ============================================================
# PREMIUM HARİTA MOTORU
# ============================================================
MAP_USER_AGENT = "MetevraWeather/1.0 (+weather app)"
# ---------------------------------------------------------------------------
# PROVIDER / APP-STORE LICENCE CONFIGURATION
# ---------------------------------------------------------------------------
# The app can still be tested locally without keys, but a Store build must
# supply the commercial credentials/agreements for the providers it enables.
# This prevents silently shipping an unauthenticated tile/API integration.
APP_STORE_BUILD = os.getenv("HAVADURUMU_STORE_BUILD", "0").strip() == "1"
CARTO_API_KEY = os.getenv("HAVADURUMU_CARTO_API_KEY", "").strip()
ESRI_API_KEY = os.getenv("HAVADURUMU_ESRI_API_KEY", "").strip()
OPEN_METEO_API_KEY = os.getenv("HAVADURUMU_OPEN_METEO_API_KEY", "").strip()
RAINVIEWER_COMMERCIAL_ENABLED = os.getenv("HAVADURUMU_RAINVIEWER_COMMERCIAL", "0").strip() == "1"

OSM_TILE_TEMPLATE = os.getenv(
    "HAVADURUMU_MAP_TILE_URL",
    "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
)
MAP_MIN_ZOOM = 2
MAP_MAX_ZOOM = 11
RAINVIEWER_API = "https://api.rainviewer.com/public/weather-maps.json"
# RainViewer public Weather Maps API currently supports tiles only through z=7.
# Asking for z=8+ returns a "Zoom Level Not Supported" tile, which is both
# visually wrong and needlessly wastes downloads during layer switching.
RAINVIEWER_MAX_ZOOM = 7

# ---------------------------------------------------------------------------
# MOBILE-FIRST PERFORMANCE PROFILE
# ---------------------------------------------------------------------------
# Kivy itself can render the map smoothly, but mobile devices punish large
# numbers of Image widgets, concurrent HTTP requests and repeated texture
# uploads.  The map therefore uses an adaptive profile: fewer tiles, a smaller
# worker pool, smaller memory cache and lower-cost overlay sampling on Android/iOS.
# The environment variable is also useful for testing the mobile profile on
# Windows: HAVADURUMU_MAP_PROFILE=mobile
MAP_PROFILE = os.getenv("HAVADURUMU_MAP_PROFILE", "auto").strip().lower()
IS_MOBILE_RUNTIME = KIVY_PLATFORM in ("android", "ios")
if MAP_PROFILE == "mobile":
    IS_MOBILE_RUNTIME = True
elif MAP_PROFILE == "desktop":
    IS_MOBILE_RUNTIME = False

MAP_TILE_WORKERS = 3 if IS_MOBILE_RUNTIME else 6
MAP_TILE_EXECUTOR = ThreadPoolExecutor(max_workers=MAP_TILE_WORKERS, thread_name_prefix="weather-map")
MAP_TILE_MEMORY = OrderedDict()
MAP_TILE_MEMORY_LIMIT = 40 if IS_MOBILE_RUNTIME else 80
MAP_TILE_MEMORY_LOCK = threading.Lock()
MAP_LOAD_DEBOUNCE = 0.10 if IS_MOBILE_RUNTIME else 0.06
MAP_VIEW_MARGIN_X = 1
MAP_VIEW_MARGIN_Y = 1
GPU_TILE_INSTALL_PER_FRAME = 1 if IS_MOBILE_RUNTIME else 4
GPU_ZOOM_LERP = 0.28 if IS_MOBILE_RUNTIME else 0.22
GPU_MAX_TILES = 14 if IS_MOBILE_RUNTIME else 28
MAP_TILE_SIZE = 256
MAP_GRID_SIDE = 3 if IS_MOBILE_RUNTIME else 5
MAP_GRID_POINTS = MAP_GRID_SIDE * MAP_GRID_SIDE
MAP_INTERACTION_FPS = 30 if IS_MOBILE_RUNTIME else 60
SATELLITE_TILE_TEMPLATE = os.getenv(
    "HAVADURUMU_SATELLITE_TILE_URL",
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
)

# Open-Meteo commercial plans use customer-api.open-meteo.com with an API key.
OPEN_METEO_FORECAST_URL = (
    "https://customer-api.open-meteo.com/v1/forecast"
    if OPEN_METEO_API_KEY else
    "https://api.open-meteo.com/v1/forecast"
)
OPEN_METEO_GEOCODING_URL = (
    "https://customer-api.open-meteo.com/v1/search"
    if OPEN_METEO_API_KEY else
    "https://geocoding-api.open-meteo.com/v1/search"
)
OPEN_METEO_SEASONAL_URL = (
    "https://customer-api.open-meteo.com/v1/seasonal"
    if OPEN_METEO_API_KEY else
    "https://seasonal-api.open-meteo.com/v1/seasonal"
)

def _provider_tile_url(template, z, x, y, provider):
    url = template.format(z=z, x=x, y=y)
    if provider == "carto" and CARTO_API_KEY:
        return url + ("&" if "?" in url else "?") + "key=" + quote(CARTO_API_KEY)
    if provider == "esri" and ESRI_API_KEY:
        return url + ("&" if "?" in url else "?") + "token=" + quote(ESRI_API_KEY)
    return url

def _open_meteo_params(params):
    if APP_STORE_BUILD and not OPEN_METEO_API_KEY:
        raise RuntimeError("Open-Meteo commercial API key is required for Store builds")
    p = dict(params)
    if OPEN_METEO_API_KEY:
        p["apikey"] = OPEN_METEO_API_KEY
    return p


def _lonlat_to_tile(lat, lon, zoom):
    import math
    lat = max(-85.05112878, min(85.05112878, float(lat)))
    n = 2 ** zoom
    x = (float(lon) + 180.0) / 360.0 * n
    lat_rad = math.radians(lat)
    y = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
    return x, y


def _tile_to_xy(lat, lon, zoom):
    x, y = _lonlat_to_tile(lat, lon, zoom)
    return int(x), int(y)


def _download_bytes(url, timeout=12, headers=None):
    r = requests.get(url, timeout=timeout, headers=headers or {"User-Agent": MAP_USER_AGENT})
    r.raise_for_status()
    return r.content


class PremiumMapView(FloatLayout):
    """Premium interactive weather map.

    - High-density base map (4x4 tiles) with smooth cinematic treatment.
    - Live RainViewer radar playback.
    - Live Open-Meteo grid overlays for temperature, wind and cloud cover.
    - Localized UI for every language supported by the application.
    - Zoom, recenter, radar play/pause and a compact legend.
    """
    SATELLITE_LABELS = {
        "TR":"Uydu", "EN":"Satellite", "DE":"Satellit", "FR":"Satellite",
        "ES":"Satélite", "IT":"Satellite", "PT":"Satélite", "RU":"Спутник",
        "AR":"القمر الصناعي", "ZH":"卫星", "JA":"衛星", "KO":"위성",
        "NL":"Satelliet", "PL":"Satelita", "EL":"Δορυφόρος", "RO":"Satelit",
        "BG":"Сателит", "SR":"Satelit", "UK":"Супутник", "HE":"לוויין",
        "HI":"उपग्रह", "ID":"Satelit", "TH":"ดาวเทียม", "VI":"Vệ tinh", "FA":"ماهواره"
    }

    MAP_TEXT = {
        "TR": {"title":"Hava Haritası","temperature":"Sıcaklık","rain":"Yağış","wind":"Rüzgâr","clouds":"Bulutlar","lightning":"Yıldırım Riski","standard":"Standart","satellite":"Canlı Atmosfer","zoom_in":"Yakınlaştır","zoom_out":"Uzaklaştır","center":"Konumuma Git","play":"Oynat","pause":"Durdur","radar":"Radar","frames":"kare","live":"CANLI","loading":"Harita yükleniyor…","legend":"Gösterge","now":"Şimdi","risk":"Fırtına riski","source":"Veri: Open-Meteo • Radar: RainViewer"},
        "EN": {"title":"Weather Map","temperature":"Temperature","rain":"Rain","wind":"Wind","clouds":"Clouds","lightning":"Lightning Risk","standard":"Standard","satellite":"Live Atmosphere","zoom_in":"Zoom in","zoom_out":"Zoom out","center":"My Location","play":"Play","pause":"Pause","radar":"Radar","frames":"frames","live":"LIVE","loading":"Loading map…","legend":"Legend","now":"Now","risk":"Storm risk","source":"Data: Open-Meteo • Radar: RainViewer"},
        "DE": {"title":"Wetterkarte","temperature":"Temperatur","rain":"Regen","wind":"Wind","clouds":"Wolken","lightning":"Gewitterrisiko","standard":"Standard","satellite":"Live-Atmosphäre","zoom_in":"Vergrößern","zoom_out":"Verkleinern","center":"Mein Standort","play":"Start","pause":"Pause","radar":"Radar","frames":"Frames","live":"LIVE","loading":"Karte wird geladen…","legend":"Legende","now":"Jetzt","risk":"Sturmrisiko","source":"Daten: Open-Meteo • Radar: RainViewer"},
        "FR": {"title":"Carte météo","temperature":"Température","rain":"Pluie","wind":"Vent","clouds":"Nuages","lightning":"Risque d’orage","standard":"Standard","satellite":"Atmosphère en direct","zoom_in":"Zoomer","zoom_out":"Dézoomer","center":"Ma position","play":"Lire","pause":"Pause","radar":"Radar","frames":"images","live":"EN DIRECT","loading":"Chargement de la carte…","legend":"Légende","now":"Maintenant","risk":"Risque d’orage","source":"Données : Open-Meteo • Radar : RainViewer"},
        "ES": {"title":"Mapa del tiempo","temperature":"Temperatura","rain":"Lluvia","wind":"Viento","clouds":"Nubes","lightning":"Riesgo de tormenta","standard":"Estándar","satellite":"Atmósfera en vivo","zoom_in":"Acercar","zoom_out":"Alejar","center":"Mi ubicación","play":"Reproducir","pause":"Pausa","radar":"Radar","frames":"marcos","live":"EN VIVO","loading":"Cargando mapa…","legend":"Leyenda","now":"Ahora","risk":"Riesgo de tormenta","source":"Datos: Open-Meteo • Radar: RainViewer"},
        "IT": {"title":"Mappa meteo","temperature":"Temperatura","rain":"Pioggia","wind":"Vento","clouds":"Nuvole","lightning":"Rischio temporali","standard":"Standard","satellite":"Atmosfera live","zoom_in":"Ingrandisci","zoom_out":"Riduci","center":"La mia posizione","play":"Avvia","pause":"Pausa","radar":"Radar","frames":"fotogrammi","live":"LIVE","loading":"Caricamento mappa…","legend":"Legenda","now":"Ora","risk":"Rischio temporali","source":"Dati: Open-Meteo • Radar: RainViewer"},
        "PT": {"title":"Mapa meteorológico","temperature":"Temperatura","rain":"Chuva","wind":"Vento","clouds":"Nuvens","lightning":"Risco de trovoada","standard":"Padrão","satellite":"Atmosfera ao vivo","zoom_in":"Aumentar","zoom_out":"Diminuir","center":"Minha localização","play":"Reproduzir","pause":"Pausa","radar":"Radar","frames":"quadros","live":"AO VIVO","loading":"A carregar o mapa…","legend":"Legenda","now":"Agora","risk":"Risco de tempestade","source":"Dados: Open-Meteo • Radar: RainViewer"},
        "RU": {"title":"Карта погоды","temperature":"Температура","rain":"Дождь","wind":"Ветер","clouds":"Облака","lightning":"Риск грозы","standard":"Стандарт","satellite":"Живая атмосфера","zoom_in":"Приблизить","zoom_out":"Отдалить","center":"Моё местоположение","play":"Пуск","pause":"Пауза","radar":"Радар","frames":"кадров","live":"ПРЯМОЙ ЭФИР","loading":"Загрузка карты…","legend":"Легенда","now":"Сейчас","risk":"Риск грозы","source":"Данные: Open-Meteo • Радар: RainViewer"},
        "AR": {"title":"خريطة الطقس","temperature":"درجة الحرارة","rain":"الأمطار","wind":"الرياح","clouds":"السحب","lightning":"خطر العواصف الرعدية","standard":"قياسي","satellite":"الغلاف الجوي المباشر","zoom_in":"تكبير","zoom_out":"تصغير","center":"موقعي","play":"تشغيل","pause":"إيقاف مؤقت","radar":"الرادار","frames":"إطار","live":"مباشر","loading":"جار تحميل الخريطة…","legend":"المفتاح","now":"الآن","risk":"خطر العواصف","source":"البيانات: Open-Meteo • الرادار: RainViewer"},
        "ZH": {"title":"天气地图","temperature":"温度","rain":"降雨","wind":"风力","clouds":"云量","lightning":"雷暴风险","standard":"标准","satellite":"实时大气","zoom_in":"放大","zoom_out":"缩小","center":"我的位置","play":"播放","pause":"暂停","radar":"雷达","frames":"帧","live":"实时","loading":"正在加载地图…","legend":"图例","now":"现在","risk":"雷暴风险","source":"数据：Open-Meteo • 雷达：RainViewer"},
        "JA": {"title":"天気マップ","temperature":"気温","rain":"雨","wind":"風","clouds":"雲","lightning":"雷雨リスク","standard":"標準","satellite":"ライブ大気","zoom_in":"拡大","zoom_out":"縮小","center":"現在地","play":"再生","pause":"一時停止","radar":"レーダー","frames":"フレーム","live":"ライブ","loading":"地図を読み込み中…","legend":"凡例","now":"現在","risk":"雷雨リスク","source":"データ: Open-Meteo • レーダー: RainViewer"},
        "KO": {"title":"날씨 지도","temperature":"기온","rain":"강수","wind":"바람","clouds":"구름","lightning":"뇌우 위험","standard":"표준","satellite":"실시간 대기","zoom_in":"확대","zoom_out":"축소","center":"내 위치","play":"재생","pause":"일시정지","radar":"레이더","frames":"프레임","live":"실시간","loading":"지도 불러오는 중…","legend":"범례","now":"현재","risk":"폭풍 위험","source":"데이터: Open-Meteo • 레이더: RainViewer"},
        "NL": {"title":"Weerkaart","temperature":"Temperatuur","rain":"Regen","wind":"Wind","clouds":"Wolken","lightning":"Onweerrisico","standard":"Standaard","satellite":"Live atmosfeer","zoom_in":"Inzoomen","zoom_out":"Uitzoomen","center":"Mijn locatie","play":"Afspelen","pause":"Pauze","radar":"Radar","frames":"beelden","live":"LIVE","loading":"Kaart laden…","legend":"Legenda","now":"Nu","risk":"Stormrisico","source":"Data: Open-Meteo • Radar: RainViewer"},
        "PL": {"title":"Mapa pogody","temperature":"Temperatura","rain":"Deszcz","wind":"Wiatr","clouds":"Chmury","lightning":"Ryzyko burzy","standard":"Standard","satellite":"Atmosfera na żywo","zoom_in":"Powiększ","zoom_out":"Pomniejsz","center":"Moja lokalizacja","play":"Odtwórz","pause":"Pauza","radar":"Radar","frames":"klatek","live":"NA ŻYWO","loading":"Ładowanie mapy…","legend":"Legenda","now":"Teraz","risk":"Ryzyko burzy","source":"Dane: Open-Meteo • Radar: RainViewer"},
        "EL": {"title":"Χάρτης καιρού","temperature":"Θερμοκρασία","rain":"Βροχή","wind":"Άνεμος","clouds":"Νέφη","lightning":"Κίνδυνος καταιγίδας","standard":"Τυπικό","satellite":"Ζωντανή ατμόσφαιρα","zoom_in":"Μεγέθυνση","zoom_out":"Σμίκρυνση","center":"Η τοποθεσία μου","play":"Αναπαραγωγή","pause":"Παύση","radar":"Ραντάρ","frames":"καρέ","live":"ΖΩΝΤΑΝΑ","loading":"Φόρτωση χάρτη…","legend":"Υπόμνημα","now":"Τώρα","risk":"Κίνδυνος καταιγίδας","source":"Δεδομένα: Open-Meteo • Ραντάρ: RainViewer"},
        "RO": {"title":"Harta meteo","temperature":"Temperatură","rain":"Ploaie","wind":"Vânt","clouds":"Nori","lightning":"Risc de furtună","standard":"Standard","satellite":"Atmosferă live","zoom_in":"Mărește","zoom_out":"Micșorează","center":"Locația mea","play":"Redare","pause":"Pauză","radar":"Radar","frames":"cadre","live":"LIVE","loading":"Se încarcă harta…","legend":"Legendă","now":"Acum","risk":"Risc de furtună","source":"Date: Open-Meteo • Radar: RainViewer"},
        "BG": {"title":"Метеорологична карта","temperature":"Температура","rain":"Дъжд","wind":"Вятър","clouds":"Облаци","lightning":"Риск от буря","standard":"Стандарт","satellite":"Жива атмосфера","zoom_in":"Увеличаване","zoom_out":"Намаляване","center":"Моето местоположение","play":"Пускане","pause":"Пауза","radar":"Радар","frames":"кадъра","live":"НА ЖИВО","loading":"Зареждане на картата…","legend":"Легенда","now":"Сега","risk":"Риск от буря","source":"Данни: Open-Meteo • Радар: RainViewer"},
        "SR": {"title":"Vremenska mapa","temperature":"Temperatura","rain":"Kiša","wind":"Vetar","clouds":"Oblaci","lightning":"Rizik od oluje","standard":"Standardno","satellite":"Atmosfera uživo","zoom_in":"Uvećaj","zoom_out":"Umanji","center":"Moja lokacija","play":"Pokreni","pause":"Pauza","radar":"Radar","frames":"kadrova","live":"UŽIVO","loading":"Učitavanje mape…","legend":"Legenda","now":"Sada","risk":"Rizik od oluje","source":"Podaci: Open-Meteo • Radar: RainViewer"},
        "UK": {"title":"Мапа погоди","temperature":"Температура","rain":"Опади","wind":"Вітер","clouds":"Хмари","lightning":"Ризик грози","standard":"Стандарт","satellite":"Атмосфера наживо","zoom_in":"Збільшити","zoom_out":"Зменшити","center":"Моє місцезнаходження","play":"Відтворити","pause":"Пауза","radar":"Радар","frames":"кадрів","live":"НАЖИВО","loading":"Завантаження карти…","legend":"Легенда","now":"Зараз","risk":"Ризик грози","source":"Дані: Open-Meteo • Радар: RainViewer"},
        "HE": {"title":"מפת מזג האוויר","temperature":"טמפרטורה","rain":"גשם","wind":"רוח","clouds":"עננים","lightning":"סיכון לסופות רעמים","standard":"רגיל","satellite":"אטמוספרה חיה","zoom_in":"הגדלה","zoom_out":"הקטנה","center":"המיקום שלי","play":"הפעל","pause":"השהה","radar":"מכ״ם","frames":"פריימים","live":"חי","loading":"טוען מפה…","legend":"מקרא","now":"עכשיו","risk":"סיכון לסערה","source":"נתונים: Open-Meteo • מכ״ם: RainViewer"},
        "HI": {"title":"मौसम मानचित्र","temperature":"तापमान","rain":"बारिश","wind":"हवा","clouds":"बादल","lightning":"तूफान का जोखिम","standard":"मानक","satellite":"लाइव वातावरण","zoom_in":"ज़ूम इन","zoom_out":"ज़ूम आउट","center":"मेरा स्थान","play":"चलाएँ","pause":"रोकें","radar":"रडार","frames":"फ्रेम","live":"लाइव","loading":"मानचित्र लोड हो रहा है…","legend":"संकेत","now":"अभी","risk":"तूफान जोखिम","source":"डेटा: Open-Meteo • रडार: RainViewer"},
        "ID": {"title":"Peta cuaca","temperature":"Suhu","rain":"Hujan","wind":"Angin","clouds":"Awan","lightning":"Risiko badai petir","standard":"Standar","satellite":"Atmosfer langsung","zoom_in":"Perbesar","zoom_out":"Perkecil","center":"Lokasi saya","play":"Putar","pause":"Jeda","radar":"Radar","frames":"bingkai","live":"LANGSUNG","loading":"Memuat peta…","legend":"Legenda","now":"Sekarang","risk":"Risiko badai","source":"Data: Open-Meteo • Radar: RainViewer"},
        "TH": {"title":"แผนที่สภาพอากาศ","temperature":"อุณหภูมิ","rain":"ฝน","wind":"ลม","clouds":"เมฆ","lightning":"ความเสี่ยงพายุฝนฟ้าคะนอง","standard":"มาตรฐาน","satellite":"บรรยากาศสด","zoom_in":"ซูมเข้า","zoom_out":"ซูมออก","center":"ตำแหน่งของฉัน","play":"เล่น","pause":"หยุดชั่วคราว","radar":"เรดาร์","frames":"เฟรม","live":"สด","loading":"กำลังโหลดแผนที่…","legend":"คำอธิบาย","now":"ตอนนี้","risk":"ความเสี่ยงพายุ","source":"ข้อมูล: Open-Meteo • เรดาร์: RainViewer"},
        "VI": {"title":"Bản đồ thời tiết","temperature":"Nhiệt độ","rain":"Mưa","wind":"Gió","clouds":"Mây","lightning":"Nguy cơ giông bão","standard":"Tiêu chuẩn","satellite":"Khí quyển trực tiếp","zoom_in":"Phóng to","zoom_out":"Thu nhỏ","center":"Vị trí của tôi","play":"Phát","pause":"Tạm dừng","radar":"Radar","frames":"khung hình","live":"TRỰC TIẾP","loading":"Đang tải bản đồ…","legend":"Chú giải","now":"Bây giờ","risk":"Nguy cơ bão","source":"Dữ liệu: Open-Meteo • Radar: RainViewer"},
        "FA": {"title":"نقشه آب‌وهوا","temperature":"دما","rain":"بارش","wind":"باد","clouds":"ابرها","lightning":"خطر رعدوبرق","standard":"استاندارد","satellite":"جو زنده","zoom_in":"بزرگ‌نمایی","zoom_out":"کوچک‌نمایی","center":"موقعیت من","play":"پخش","pause":"مکث","radar":"رادار","frames":"فریم","live":"زنده","loading":"در حال بارگذاری نقشه…","legend":"راهنما","now":"اکنون","risk":"خطر طوفان","source":"داده: Open-Meteo • رادار: RainViewer"},
    }

    def __init__(self, app, **kwargs):
        super().__init__(**kwargs)
        self.app = app
        self.lat = app.lat if app.lat is not None else 39.92
        self.lon = app.lon if app.lon is not None else 32.85
        self.zoom = 4
        self.layer = "temperature"
        self._base_provider = None
        self._map_anim_t = 0.0
        self._map_load_thread = None
        # MUST exist before Clock can call _animate_map. v28 could start the
        # 15 FPS callback before the first _redraw_overlay(), causing:
        # AttributeError: 'PremiumMapView' object has no attribute '_pulse_ring'
        self._pulse_ring = None
        self._wind_anim_lines = []
        self._last_grid = None
        self._last_grid_fetch_at = 0.0
        self._last_grid_center = None
        self._map_anim_event = None
        self._pan_visual = (0.0, 0.0)
        self._drag_start = None
        self._drag_origin = None
        self._drag_moved = False
        # Mobile pinch-to-zoom state. The map remains GPU-only while the
        # gesture is active; network work happens only after the gesture ends.
        self._active_touches = {}
        self._pinch_start_distance = None
        self._pinch_start_zoom = None
        self._pinch_visual_center = None
        self._refresh_event = None
        self._last_map_size = (0, 0)
        self.radar_frames = []
        self.radar_host = None
        self.radar_index = -1
        self.radar_playing = False
        self.radar_event = None
        self._radar_load_token = 0
        self._radar_loading = False
        self._radar_frame_token = 0
        self.map_token = 0
        self.data_token = 0
        # GPU/OpenGL tile renderer. Each map tile is an independent Kivy Image
        # texture rendered by the GPU. We never stitch the viewport into one
        # giant PIL bitmap, so pan/zoom only changes texture transforms.
        self.tile_size = MAP_TILE_SIZE
        self._base_tiles = []
        self._radar_tiles = []
        self._visual_scale = 1.0
        self._target_scale = 1.0
        self._visual_scale = 2.0 ** (float(self.zoom) - int(self.zoom))
        self._target_scale = self._visual_scale
        self._zoom_anchor = (0.5, 0.5)
        self._tile_install_event = None
        self._tile_generation = 0
        self._tile_batches = {}
        self._loaded_tile_zoom = None
        self._loaded_tile_center = None
        self._loaded_provider = None
        self._last_load_signature = None
        self._radar_generation = 0
        self._radar_install_event = None
        # Layer switching is intentionally staged. The button click only changes
        # lightweight state; network/texture work continues asynchronously.
        self._layer_switch_token = 0
        self._layer_switch_event = None
        self._layer_switch_busy = False

        # Dedicated map scene: tiles must live BELOW the HUD. In v34 tiles were
        # inserted at index=0 of the root and could paint over the layer buttons.
        # A separate scene layer makes z-order deterministic and keeps controls clickable.
        self.map_scene = FloatLayout(size_hint=(1,1), pos_hint={"x":0,"y":0})
        self.add_widget(self.map_scene)
        self.hud = BoxLayout(orientation="vertical", size_hint=(1,1), padding=dp(10), spacing=dp(6))
        self.add_widget(self.hud)
        # On phones the six map modes must remain reachable without shrinking
        # into unreadable half-buttons. A horizontal strip scrolls only the
        # controls; the map itself remains fully touchable.
        self.header = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(5))
        self.header_scroll = None
        self.title_label = ModernLabel(text="", font_size="13sp", bold=True, halign="left", valign="middle", size_hint_x=.22)
        if not IS_MOBILE_RUNTIME:
            self.header.add_widget(self.title_label)
        else:
            self.header.size_hint_x = None
            self.header.width = dp(6)
            self.header_scroll = ScrollView(do_scroll_x=True, do_scroll_y=False, bar_width=dp(2), size_hint_y=None, height=dp(38),
                                             scroll_type=["content"], effect_cls="ScrollEffect")
            self.header.bind(minimum_width=self.header.setter("width"))
            self.header_scroll.add_widget(self.header)
        self.layer_buttons = []
        self.layer_names = ("temperature","rain","wind","clouds","lightning","satellite")
        for name in self.layer_names:
            b = ModernButton(text="", font_size="7.5sp" if IS_MOBILE_RUNTIME else "8.2sp", background_color=(.035,.065,.12,.94),
                             size_hint_x=None if IS_MOBILE_RUNTIME else 1,
                             width=dp(76) if IS_MOBILE_RUNTIME else 0)
            b.bind(on_release=lambda _, n=name: self.set_layer(n))
            self.layer_buttons.append(b); self.header.add_widget(b)
        if IS_MOBILE_RUNTIME:
            self.header.width = dp(6 + 76*len(self.layer_names) + 5*(len(self.layer_names)-1))
            self.hud.add_widget(self.header_scroll)
        else:
            self.hud.add_widget(self.header)
        # Store builds do not silently use free/non-commercial radar or
        # unauthenticated imagery. The buttons remain visible in test builds.
        if APP_STORE_BUILD and not ESRI_API_KEY:
            self.layer_buttons[self.layer_names.index("satellite")].disabled = True
        if APP_STORE_BUILD and not RAINVIEWER_COMMERCIAL_ENABLED:
            self.layer_buttons[self.layer_names.index("rain")].disabled = True

        body = FloatLayout()
        self.hud.add_widget(body)
        self.legend = Card(orientation="vertical", size_hint=(None,None), size=(dp(170),dp(78)), padding=dp(8), spacing=dp(2))
        self.legend_title = ModernLabel(text="", font_size="9sp", bold=True, size_hint_y=None, height=dp(16))
        self.legend_value = ModernLabel(text="", font_size="9sp", color=(.78,.86,.95,1), size_hint_y=None, height=dp(18))
        self.legend_hint = ModernLabel(text="", font_size="8sp", color=(.65,.75,.86,1), size_hint_y=None, height=dp(18))
        self.legend.add_widget(self.legend_title); self.legend.add_widget(self.legend_value); self.legend.add_widget(self.legend_hint)
        self.legend.pos_hint={"x":.015,"y":.02}; body.add_widget(self.legend)

        self.center_card = Card(orientation="vertical", size_hint=(None,None), size=(dp(190),dp(74)) if IS_MOBILE_RUNTIME else (dp(210),dp(82)), padding=dp(10), spacing=dp(2))
        self.center_title = ModernLabel(text="", font_size="13sp", bold=True, halign="center", size_hint_y=None, height=dp(25))
        self.center_sub = ModernLabel(text="", font_size="9sp", halign="center", size_hint_y=None, height=dp(18))
        self.center_card.add_widget(self.center_title); self.center_card.add_widget(self.center_sub)
        self.center_card.pos_hint={"center_x":.5,"center_y":.48}; body.add_widget(self.center_card)

        self.controls = BoxLayout(size_hint=(None,None), size=(dp(44),dp(132)) if IS_MOBILE_RUNTIME else (dp(50),dp(150)), orientation="vertical", spacing=dp(5), pos_hint={"right":.985,"top":.985})
        for text, fn, tooltip in (("+",self.zoom_in,""),("−",self.zoom_out,""),("⌾",self.center_location,"")):
            b=ModernButton(text=text,font_size="18sp",background_color=(.025,.055,.10,.94),color=(.9,.95,1,1))
            b.bind(on_release=lambda *_ ,f=fn:f()); self.controls.add_widget(b)
        body.add_widget(self.controls)

        bottom = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(5))
        self.radar_label = ModernLabel(text="", font_size="9sp", size_hint_x=.24, halign="left")
        self.radar_slider = Slider(min=0,max=1,value=1,step=1,size_hint_x=.36)
        self.radar_slider.bind(value=self._radar_slider_changed)
        self.play_btn = ModernButton(text="", font_size="9sp", size_hint_x=None, width=dp(68), background_color=(.05,.16,.22,.96))
        self.play_btn.bind(on_release=self.toggle_radar_play)
        prev=ModernButton(text="‹",size_hint_x=None,width=dp(38),background_color=(.04,.08,.14,.95))
        nxt=ModernButton(text="›",size_hint_x=None,width=dp(38),background_color=(.04,.08,.14,.95))
        prev.bind(on_release=lambda *_:self._radar_step(-1)); nxt.bind(on_release=lambda *_:self._radar_step(1))
        bottom.add_widget(self.radar_label); bottom.add_widget(self.radar_slider); bottom.add_widget(self.play_btn); bottom.add_widget(prev); bottom.add_widget(nxt)
        self.hud.add_widget(bottom)
        self.attribution = ModernLabel(text="© OpenStreetMap contributors",font_size="7sp" if IS_MOBILE_RUNTIME else "7.5sp",color=(.82,.89,.96,.88),size_hint_y=None,height=dp(17),halign="right")
        self.hud.add_widget(self.attribution)

        self.bind(size=self._layout_images,pos=self._layout_images)
        self.refresh_labels()
        Clock.schedule_once(lambda *_: self.refresh(), .08)
        self._map_anim_event = Clock.schedule_interval(self._animate_map, 1.0 / MAP_INTERACTION_FPS)

    def on_parent(self, widget, parent):
        # Cancel Kivy timers when the map is removed so callbacks cannot fire
        # against a partially destroyed PremiumMapView.
        if parent is None:
            for attr in ("_map_anim_event", "_radar_event", "_refresh_event", "_tile_install_event", "_radar_install_event", "_layer_switch_event"):
                ev = getattr(self, attr, None)
                if ev is not None:
                    try:
                        ev.cancel()
                    except Exception:
                        pass
                    setattr(self, attr, None)
        # Kivy Widget exposes on_parent as an EventDispatcher event, not a
        # superclass method that should be called directly. Calling
        # super().on_parent() raises: AttributeError: 'super' object has no
        # attribute 'on_parent'. Cleanup above is sufficient.

    def _t(self,key):
        lang=getattr(self.app,"lang","EN")
        if key == "satellite":
            return self.SATELLITE_LABELS.get(lang, self.SATELLITE_LABELS["EN"])
        return self.MAP_TEXT.get(lang,self.MAP_TEXT["EN"]).get(key,key)

    def refresh_labels(self):
        self.title_label.text=self._t("title")
        for b,name in zip(self.layer_buttons,self.layer_names):
            b.text=self._t(name)
            b.background_color=(.10,.28,.40,.98) if self.layer==name else (.035,.065,.12,.94)
        self.play_btn.text=self._t("pause") if self.radar_playing else self._t("play")
        self.radar_label.text=f"{self._t('radar')} • {self._t('now')}" if not self.radar_frames else f"{self._t('radar')} • {len(self.radar_frames)} {self._t('frames')}"
        self.legend_title.text=self._t("legend")
        self._update_legend()
        self._update_center_card()

    def _layout_images(self,*_):
        # Repositioning is GPU-friendly: textures stay resident; only widget
        # transforms change when the window is resized.
        self._reposition_gpu_tiles()

    def set_center(self,lat,lon):
        if lat is not None and lon is not None:
            self.lat,self.lon=float(lat),float(lon)
        self.refresh()

    def center_location(self):
        self.set_center(self.app.lat,self.app.lon)

    def zoom_in(self):
        if self.zoom < MAP_MAX_ZOOM:
            self.zoom = min(float(MAP_MAX_ZOOM), round(float(self.zoom) + 0.5, 2))
            self._target_scale = 2.0 ** (self.zoom - int(self.zoom))
            self.refresh()

    def zoom_out(self):
        if self.zoom > MAP_MIN_ZOOM:
            self.zoom = max(float(MAP_MIN_ZOOM), round(float(self.zoom) - 0.5, 2))
            self._target_scale = 2.0 ** (self.zoom - int(self.zoom))
            self.refresh()

    def _touch_is_ui(self, touch):
        # Never steal touches from map controls. This is important on Windows
        # mouse input and on mobile touch input.
        widgets = list(getattr(self, "layer_buttons", [])) + [
            getattr(self, "play_btn", None),
            getattr(self, "radar_slider", None),
        ]
        widgets += list(getattr(self, "controls", []).children if getattr(self, "controls", None) else [])
        for w in widgets:
            if w is not None and w.collide_point(*touch.pos):
                return True
        return False

    def _touch_distance(self):
        pts=list(self._active_touches.values())
        if len(pts) < 2:
            return None
        (x1,y1),(x2,y2)=pts[0],pts[1]
        return max(1.0, ((x2-x1)**2+(y2-y1)**2)**0.5)

    def on_touch_down(self, touch):
        if getattr(touch, "is_mouse_scrolling", False):
            if self._touch_is_ui(touch):
                return super().on_touch_down(touch)
            if touch.button == "scrolldown" and self.zoom > MAP_MIN_ZOOM:
                self.zoom = max(float(MAP_MIN_ZOOM), float(self.zoom) - 0.25)
                self._target_scale = 2.0 ** (self.zoom - int(self.zoom))
                self.refresh()
                return True
            if touch.button == "scrollup" and self.zoom < MAP_MAX_ZOOM:
                self.zoom = min(float(MAP_MAX_ZOOM), float(self.zoom) + 0.25)
                self._target_scale = 2.0 ** (self.zoom - int(self.zoom))
                self.refresh()
                return True

        if self._touch_is_ui(touch):
            return super().on_touch_down(touch)
        if not self.collide_point(*touch.pos):
            return super().on_touch_down(touch)

        self._active_touches[touch.uid] = (float(touch.x), float(touch.y))
        if len(self._active_touches) == 2:
            self._pinch_start_distance = self._touch_distance()
            self._pinch_start_zoom = float(self.zoom)
            self._pinch_visual_center = (self.center_x, self.center_y)
            self._drag_start = None
            self._drag_origin = None
            self._drag_moved = False
            touch.grab(self)
            return True

        self._drag_start = tuple(touch.pos)
        self._drag_origin = (float(self.lat), float(self.lon))
        self._drag_moved = False
        self._pan_visual = (0.0, 0.0)
        touch.grab(self)
        return True

    def on_touch_move(self, touch):
        if touch.uid in self._active_touches:
            self._active_touches[touch.uid] = (float(touch.x), float(touch.y))

        if len(self._active_touches) >= 2:
            if self._pinch_start_distance is None:
                self._pinch_start_distance = self._touch_distance()
                self._pinch_start_zoom = float(self.zoom)
            dist=self._touch_distance()
            if dist and self._pinch_start_distance:
                import math
                delta=math.log(dist/self._pinch_start_distance, 2.0)
                self.zoom=max(float(MAP_MIN_ZOOM),min(float(MAP_MAX_ZOOM),self._pinch_start_zoom+delta))
                self._target_scale=2.0**(self.zoom-int(self.zoom))
                self._reposition_gpu_tiles()
            return True

        if touch.grab_current is not self or not self._drag_start:
            return super().on_touch_move(touch)
        dx=float(touch.x)-self._drag_start[0]
        dy=float(touch.y)-self._drag_start[1]
        if abs(dx)+abs(dy)>dp(4): self._drag_moved=True
        if not self._drag_moved: return True
        self._pan_visual=(dx,dy)
        self._translate_gpu_tiles(dx,dy)
        return True

    def on_touch_up(self, touch):
        if touch.uid in self._active_touches:
            self._active_touches.pop(touch.uid,None)

        if len(self._active_touches) == 0:
            self._pinch_start_distance=None
            self._pinch_start_zoom=None
            if touch.grab_current is self:
                try: touch.ungrab(self)
                except Exception: pass
                moved=self._drag_moved
                dx,dy=self._pan_visual
                origin=self._drag_origin
                self._drag_start=None; self._drag_origin=None
                self._pan_visual=(0.0,0.0); self._drag_moved=False
                if moved and origin:
                    self._apply_pan_delta(origin[0],origin[1],dx,dy)
                else:
                    self.refresh_map_only(force=False)
                return True
        elif len(self._active_touches) == 1:
            # One finger remains after a pinch. Do not synthesize a large pan.
            self._drag_start=None; self._drag_origin=None; self._pan_visual=(0.0,0.0); self._drag_moved=False
            self._pinch_start_distance=None; self._pinch_start_zoom=None
        return super().on_touch_up(touch)

    def _apply_pan_delta(self, lat0, lon0, dx, dy):
        z=max(MAP_MIN_ZOOM,min(MAP_MAX_ZOOM,int(self.zoom)))
        n=2**z
        cx0,cy0=_lonlat_to_tile(lat0,lon0,z)
        cx=(cx0-dx/self.tile_size)%n
        cy=max(0.0,min(float(n-1e-6),cy0+dy/self.tile_size))
        self.lon=cx/n*360.0-180.0
        import math
        merc=math.pi*(1-2*cy/n)
        self.lat=max(-85.0511,min(85.0511,math.degrees(math.atan(math.sinh(merc)))))
        self.refresh()

    def _finish_drag_refresh(self, *_):
        # Kept for compatibility with older callers; release now refreshes once.
        self._refresh_event = None

    def set_layer(self,layer):
        """Switch map layers without doing heavy work inside the button callback.

        The old implementation immediately rebuilt the overlay and could start
        radar/base-map texture work from the same UI event. On phones that made
        the layer buttons feel frozen. V37 separates the cheap visual state
        change from the expensive async work and keeps the current map visible
        until replacement textures are ready.
        """
        if layer not in self.layer_names:
            return
        if APP_STORE_BUILD and layer == "satellite" and not ESRI_API_KEY:
            print("Uydu katmanı kapalı: HAVADURUMU_ESRI_API_KEY eksik.")
            return
        if APP_STORE_BUILD and layer == "rain" and not RAINVIEWER_COMMERCIAL_ENABLED:
            print("Radar katmanı kapalı: ticari RainViewer sözleşmesi/erişimi etkin değil.")
            return
        if layer == self.layer and not self._layer_switch_busy:
            return

        self._layer_switch_token += 1
        token = self._layer_switch_token
        old_layer = self.layer
        self.layer = layer
        self._layer_switch_busy = True

        # Cancel radar playback as soon as we leave the radar page.
        if old_layer == "rain" and layer != "rain":
            self.radar_playing = False
            if self.radar_event:
                try: self.radar_event.cancel()
                except Exception: pass
                self.radar_event = None

        # This is intentionally cheap: no HTTP, no tile creation and no large
        # canvas rebuild in the button event itself.
        self._set_radar_tiles_visible(layer == "rain" and bool(self.radar_frames))
        self.refresh_labels()

        if self._layer_switch_event is not None:
            try: self._layer_switch_event.cancel()
            except Exception: pass
        self._layer_switch_event = Clock.schedule_once(
            lambda *_: self._finish_layer_switch(token), 0.02
        )

    def _finish_layer_switch(self, token):
        self._layer_switch_event = None
        if token != self._layer_switch_token:
            return
        try:
            # Redraw only after the click event has returned to Kivy.
            self._redraw_overlay(getattr(self, "_last_grid", None))

            if self.layer == "rain":
                if not self.radar_frames:
                    self.load_radar()
                else:
                    self._load_radar_frame(self.radar_index)
            elif self.layer != "satellite":
                self.load_live_grid()

            new_provider = "satellite" if self.layer == "satellite" else "standard"
            if self._base_provider != new_provider:
                self.refresh_map_only(force=True)
        finally:
            self._layer_switch_busy = False

    def refresh_map_only(self, force=True):
        # Fractional zoom is visual/GPU-only until an integer tile level is crossed.
        # Likewise, small pans inside the already loaded tile neighborhood do not
        # trigger HTTP requests. This is the main bandwidth + stutter reduction.
        provider = "satellite" if self.layer == "satellite" else "standard"
        z = max(MAP_MIN_ZOOM, min(MAP_MAX_ZOOM, int(self.zoom)))
        cx, cy = _lonlat_to_tile(self.lat, self.lon, z)
        sig = (provider, z, int(cx), int(cy))
        self._target_scale = 2.0 ** (float(self.zoom) - float(z))
        self._visual_scale = max(0.75, min(2.0, self._visual_scale))
        if (not force) and self._last_load_signature == sig:
            self._reposition_gpu_tiles()
            return
        if self._last_load_signature == sig and self._base_tiles:
            self._reposition_gpu_tiles()
            return
        self.map_token += 1
        token=self.map_token
        ev = getattr(self, "_refresh_event", None)
        if ev is not None:
            try: ev.cancel()
            except Exception: pass
        self._refresh_event = Clock.schedule_once(lambda *_: self._start_map_load(token), MAP_LOAD_DEBOUNCE)

    def _start_map_load(self, token):
        self._refresh_event = None
        if token != self.map_token:
            return
        self._map_load_thread = threading.Thread(target=self._load_map_worker,args=(token,),daemon=True)
        self._map_load_thread.start()

    def refresh(self):
        # Map rendering is independent from weather-grid requests. This is a
        # major responsiveness fix: panning/zooming no longer fires a 25-point
        # weather API request every time the bitmap is refreshed.
        self.refresh_map_only()
        self._update_center_card()
        if self.layer == "rain":
            if not self.radar_frames:
                self.load_radar()
        elif self.layer != "satellite":
            self.load_live_grid()

    def _location_name(self):
        return self.app.district or (self.app.province.get("name") if isinstance(self.app.province,dict) else None) or (self.app.country.get("name") if self.app.country else "Location")

    def _update_center_card(self):
        name=self._location_name()
        self.center_title.text=f"{name}  •  {self._t(self.layer)}"
        self.center_sub.text=f"{self.lat:.3f}, {self.lon:.3f}"

    def _load_map_worker(self,token):
        """Fetch raw PNG tiles only; Kivy uploads them as GPU textures.

        The old engine decoded/stiched 20-30 images with PIL into one giant
        bitmap. V34 removes that CPU composition step completely.
        """
        try:
            z=max(MAP_MIN_ZOOM,min(MAP_MAX_ZOOM,int(self.zoom)))
            self._target_scale = 2.0 ** (float(self.zoom) - float(z))
            cx_f,cy_f=_lonlat_to_tile(self.lat,self.lon,z)
            cx,cy=int(cx_f),int(cy_f)
            view_w=max(320,int(self.width or 1280)); view_h=max(260,int(self.height or 720))
            # Mobile: 4x3 tiles is enough for a phone-sized viewport. Desktop
            # gets a slightly wider ring. This is the single biggest bandwidth
            # reduction compared with v35's 48-tile worst case.
            if IS_MOBILE_RUNTIME:
                span_x = 4 if view_w <= dp(700) else 5
                span_y = 3 if view_h <= dp(800) else 4
            else:
                span_x=max(5,min(7,(view_w//self.tile_size)+2))
                span_y=max(4,min(6,(view_h//self.tile_size)+2))
            while span_x*span_y > GPU_MAX_TILES:
                if span_x >= span_y: span_x -= 1
                else: span_y -= 1
            left=span_x//2; top=span_y//2
            cache_dir=self.app.cache_dir if hasattr(self.app,'cache_dir') else os.path.join(os.path.expanduser('~'),'.kivy','weather_tiles')
            os.makedirs(cache_dir,exist_ok=True)
            n=2**z
            provider = "esri" if self.layer == "satellite" else "osm"
            tile_template = SATELLITE_TILE_TEMPLATE if self.layer=="satellite" else OSM_TILE_TEMPLATE
            jobs=[]
            for iy in range(span_y):
                dy=iy-top; y=cy+dy
                if y<0 or y>=n: continue
                for ix in range(span_x):
                    dx=ix-left; x=(cx+dx)%n
                    png_path=os.path.join(cache_dir,f"gpu_{provider}_{z}_{x}_{y}.png")
                    legacy_path=os.path.join(cache_dir,f"{provider}_{z}_{x}_{y}.png")
                    jobs.append((ix,iy,x,y,png_path,legacy_path))

            def get_tile(job):
                ix,iy,x,y,png_path,legacy_path=job
                key=("gpu",provider,z,x,y)
                try:
                    with MAP_TILE_MEMORY_LOCK:
                        cached=MAP_TILE_MEMORY.get(key)
                        if cached is not None:
                            MAP_TILE_MEMORY.move_to_end(key)
                            return ix,iy,x,y,cached
                    if os.path.exists(png_path):
                        data=None
                        path=png_path
                    elif os.path.exists(legacy_path):
                        data=None
                        path=legacy_path
                    else:
                        if APP_STORE_BUILD and provider == "esri" and not ESRI_API_KEY:
                            raise RuntimeError("Esri API key missing for Store build")
                        url=_provider_tile_url(tile_template,z,x,y,provider)
                        data=_download_bytes(url,timeout=7,headers={"User-Agent":MAP_USER_AGENT})
                        tmp=png_path+".part"
                        with open(tmp,'wb') as fh: fh.write(data)
                        try: os.replace(tmp,png_path)
                        except Exception:
                            try: os.remove(tmp)
                            except Exception: pass
                        path=png_path
                    if data is None:
                        with open(path,'rb') as fh: data=fh.read()
                    with MAP_TILE_MEMORY_LOCK:
                        MAP_TILE_MEMORY[key]=data
                        MAP_TILE_MEMORY.move_to_end(key)
                        while len(MAP_TILE_MEMORY)>MAP_TILE_MEMORY_LIMIT:
                            MAP_TILE_MEMORY.popitem(last=False)
                    return ix,iy,x,y,data
                except Exception:
                    return ix,iy,x,y,None

            # Submit center/near-center tiles first so the user sees a usable
            # map before the entire ring finishes downloading. This is much more
            # important on mobile networks than shaving a few milliseconds off
            # the total completion time.
            center_ix, center_iy = span_x//2, span_y//2
            jobs.sort(key=lambda j: abs(j[0]-center_ix) + abs(j[1]-center_iy))
            futures=[MAP_TILE_EXECUTOR.submit(get_tile,j) for j in jobs]
            results=[]
            first_batch_size=min(4 if IS_MOBILE_RUNTIME else 6, len(jobs))
            first_sent=False
            first_keys=set()
            for f in as_completed(futures):
                if token != self.map_token:
                    return
                results.append(f.result())
                if not first_sent and len(results) >= first_batch_size:
                    first_sent=True
                    first=sorted(results[:], key=lambda q:(q[1],q[0]))
                    first_keys={(q[1],q[0]) for q in first}
                    Clock.schedule_once(lambda *_: self._begin_gpu_tile_install(first,token,provider,z,cx_f,cy_f),0)
            results.sort(key=lambda q:(q[1],q[0]))
            if token != self.map_token:
                return
            if not first_sent:
                Clock.schedule_once(lambda *_: self._begin_gpu_tile_install(results,token,provider,z,cx_f,cy_f),0)
            elif len(results) > first_batch_size:
                remaining=[q for q in results if (q[1],q[0]) not in first_keys]
                Clock.schedule_once(lambda *_: self._append_gpu_tile_install(remaining,token,provider,z,cx_f,cy_f),0.02)
        except Exception as e:
            print("GPU harita yükleme hatası:",e)

    def _begin_gpu_tile_install(self,results,token,provider,z,cx_f,cy_f):
        if token != self.map_token:
            return
        # A previous batch may have installed a few tiles before a newer pan/zoom
        # request won the race. Remove only those pending widgets; keep the
        # currently visible base tiles until the replacement is complete.
        pending=self._tile_batches.get(self._tile_generation)
        if pending:
            for w in pending.get("new",[]):
                try:self.map_scene.remove_widget(w)
                except Exception:pass
            self._tile_batches.pop(self._tile_generation,None)
        self._tile_generation += 1
        generation=self._tile_generation
        old=self._base_tiles
        self._base_tiles=[]
        self._tile_batches[generation]={
            "results":results,"index":0,"provider":provider,"z":z,
            "cx_f":cx_f,"cy_f":cy_f,"old":old,"new":[]
        }
        if self._tile_install_event:
            try:self._tile_install_event.cancel()
            except Exception:pass
        self._tile_install_event=Clock.schedule_interval(lambda dt:self._install_gpu_tiles_tick(generation),1/120.0)

    def _install_gpu_tiles_tick(self,generation):
        batch=self._tile_batches.get(generation)
        if not batch:
            return False
        if generation != self._tile_generation:
            return False
        results=batch["results"]
        added=0
        while batch["index"] < len(results) and added < GPU_TILE_INSTALL_PER_FRAME:
            ix,iy,x,y,data=results[batch["index"]]
            batch["index"] += 1
            if data:
                path=self._write_gpu_temp_png(data,batch["provider"],batch["z"],x,y)
                # AsyncImage keeps file decoding/texture preparation out of the
                # button/touch callback. The old Image(source=...) path could
                # upload several 256x256 textures in one frame and visibly stall
                # mobile devices during Satellite <-> Standard switches.
                img=AsyncImage(source=path,allow_stretch=True,keep_ratio=False,
                               nocache=False,
                               size=(self.tile_size,self.tile_size),
                               size_hint=(None,None),opacity=0)
                img._map_tile_meta=(ix,iy,x,y,batch["z"],batch["cx_f"],batch["cy_f"])
                self.map_scene.add_widget(img)
                batch["new"].append(img)
                added += 1
        if batch["index"] >= len(results):
            # AsyncImage may still be decoding the last files. Do not remove the
            # old map yet. Wait until all replacement textures are actually ready,
            # then reveal the new set in one lightweight state change.
            if not all(getattr(w, "texture", None) is not None for w in batch["new"]):
                if not batch.get("ready_watch"):
                    batch["ready_watch"] = True
                    Clock.schedule_interval(lambda dt: self._finish_gpu_tile_swap(generation), 1/60.0)
                return False
            self._finish_gpu_tile_swap(generation)
            return False
        return True

    def _finish_gpu_tile_swap(self, generation):
        batch=self._tile_batches.get(generation)
        if not batch or generation != self._tile_generation:
            return False
        new_tiles=batch["new"]
        if not new_tiles or not all(getattr(w, "texture", None) is not None for w in new_tiles):
            return True
        for w in new_tiles:
            w.opacity=1
        for w in batch["old"]:
            try:self.map_scene.remove_widget(w)
            except Exception:pass
        self._base_tiles=list(new_tiles)
        self._loaded_tile_zoom=batch["z"]
        self._loaded_tile_center=(self.lat,self.lon)
        self._loaded_provider=batch["provider"]
        self._last_load_signature=(batch["provider"],batch["z"],int(batch["cx_f"]),int(batch["cy_f"]))
        self._base_provider="satellite" if batch["provider"]=="esri" else "standard"
        self._position_tile_list(self._base_tiles,batch["z"],batch["cx_f"],batch["cy_f"])
        self._tile_batches.pop(generation,None)
        if self._tile_install_event:
            try:self._tile_install_event.cancel()
            except Exception:pass
            self._tile_install_event=None
        if self.layer == "satellite":
            self.attribution.text="Sources: Esri, Earthstar Geographics, and the GIS User Community"
        elif self.layer == "rain":
            self.attribution.text="© OpenStreetMap contributors • Weather data by RainViewer"
        else:
            self.attribution.text="© OpenStreetMap contributors • Weather data by Open-Meteo"
        self._redraw_overlay(getattr(self,"_last_grid",None))
        return False

    def _append_gpu_tile_install(self,results,token,provider,z,cx_f,cy_f):
        """Add late/prefetch tiles without replacing the already visible map."""
        if token != self.map_token or not results:
            return
        generation=self._tile_generation + 1000000
        index=0
        def tick(dt):
            nonlocal index
            if token != self.map_token:
                return False
            added=0
            while index < len(results) and added < GPU_TILE_INSTALL_PER_FRAME:
                ix,iy,x,y,data=results[index]; index += 1
                if not data:
                    continue
                path=self._write_gpu_temp_png(data,provider,z,x,y)
                img=Image(source=path,allow_stretch=True,keep_ratio=False,nocache=False,
                           size=(self.tile_size,self.tile_size),size_hint=(None,None))
                img._map_tile_meta=(ix,iy,x,y,z,cx_f,cy_f)
                try:
                    if img.texture:
                        img.texture.mag_filter="linear"
                        img.texture.min_filter="linear"
                except Exception:
                    pass
                self.map_scene.add_widget(img)
                self._base_tiles.append(img)
                added += 1
            self._position_tile_list(self._base_tiles,z,cx_f,cy_f)
            return index < len(results)
        Clock.schedule_interval(tick,1/120.0)

    def _write_gpu_temp_png(self,data,provider,z,x,y):
        # Reuse the same disk path as the raw tile cache. v35 generated a new
        # upload PNG on every refresh, which created extra I/O and thousands of
        # small files after prolonged use. Stable paths make mobile storage and
        # texture loading much cheaper.
        cache_dir=self.app.cache_dir if hasattr(self.app,'cache_dir') else os.path.join(os.path.expanduser('~'),'.kivy','weather_tiles')
        os.makedirs(cache_dir,exist_ok=True)
        path=os.path.join(cache_dir,f"gpu_{provider}_{z}_{x}_{y}.png")
        if not os.path.exists(path):
            try:
                with open(path,'wb') as fh: fh.write(data)
            except Exception:
                pass
        return path

    def _position_tile_list(self,tiles,z,cx_f=None,cy_f=None,dx=0,dy=0):
        if not tiles:
            return
        if cx_f is None or cy_f is None:
            cx_f,cy_f=_lonlat_to_tile(self.lat,self.lon,z)
        scale=self._visual_scale
        ts=self.tile_size*scale
        center_x=self.center_x+dx
        center_y=self.center_y+dy
        for img in tiles:
            meta=getattr(img,"_map_tile_meta",None)
            if not meta: continue
            ix,iy,x,y,tz,tcx,tcy=meta
            px=center_x+(x-tcx)*ts
            py=center_y+(tcy-y)*ts
            img.pos=(px-ts/2,py-ts/2)
            img.size=(ts,ts)

    def _reposition_gpu_tiles(self):
        # The current geographic center is the reference point. During a drag
        # self._pan_visual is applied as a pure GPU translation so the map never
        # snaps back while the pointer/finger is moving.
        dx,dy=self._pan_visual
        if self._base_tiles:
            z=int(self.zoom); cx,cy=_lonlat_to_tile(self.lat,self.lon,z)
            self._position_tile_list(self._base_tiles,z,cx,cy,dx,dy)
        if self._radar_tiles:
            z=int(self._radar_tile_zoom or self.zoom)
            cx,cy=_lonlat_to_tile(self.lat,self.lon,z)
            self._position_tile_list(self._radar_tiles,z,cx,cy,dx,dy)

    def _translate_gpu_tiles(self,dx,dy):
        for img in self._base_tiles:
            img.pos=(img.x+dx,img.y+dy)
        for img in self._radar_tiles:
            img.pos=(img.x+dx,img.y+dy)

    def _set_radar_tiles_visible(self,visible):
        for img in self._radar_tiles:
            img.opacity=1 if visible else 0

    def _clear_radar_tiles(self):
        if self._radar_install_event:
            try:self._radar_install_event.cancel()
            except Exception:pass
            self._radar_install_event=None
        for img in self._radar_tiles:
            try:self.map_scene.remove_widget(img)
            except Exception:pass
        self._radar_tiles=[]

    def _redraw_overlay(self,grid=None):
        import math
        self.canvas.after.clear()
        self._pulse_ring = None
        self._wind_anim_lines = []
        self._last_grid = grid
        w,h=self.size
        if w<=0 or h<=0:return
        with self.canvas.after:
            # Very subtle cinematic tint; the actual map tiles stay sharp.
            Color(.01,.03,.06,.018 if self.layer!="rain" else .005)
            self.canvas.after.add(Rectangle(pos=self.pos,size=self.size))

            # Location pulse: one lightweight instruction, animated without
            # clearing/rebuilding the whole canvas 30 times per second.
            cx=self.x+w*.5; cy=self.y+h*.5
            Color(1,.62,.10,.98)
            self.canvas.after.add(Ellipse(pos=(cx-dp(6),cy-dp(6)),size=(dp(12),dp(12))))
            self._pulse_ring=Line(circle=(cx,cy,dp(18)),width=1.0)
            Color(1,.62,.10,.35)
            self.canvas.after.add(self._pulse_ring)

            if grid:
                self._draw_grid_points(grid,w,h)

            if self.layer=="wind":
                # 10 animated streamlines. Only their endpoints move on each tick.
                for i in range(10):
                    px=self.x+((i*173+37)%max(1,int(w)))
                    py=self.y+((i*97+53)%max(1,int(h)))
                    Color(.25,.85,1,.34)
                    line=Line(points=[px,py,px+dp(22),py],width=1.0)
                    self.canvas.after.add(line)
                    self._wind_anim_lines.append((line,px,py))

    def _draw_layer_overlay(self,grid=None):
        # Backwards-compatible entry point used by older code.
        self._redraw_overlay(grid)

    def _animate_map(self, dt):
        # GPU tile transform loop. Textures stay on the GPU; only positions/sizes
        # are updated. This is the 60-FPS interaction path.
        if self._base_tiles or self._radar_tiles:
            # Keep normal scale at 1.0 for integer zoom levels, but retain a
            # lerp hook so future fractional zoom can be enabled without a new
            # renderer.
            self._visual_scale += (self._target_scale-self._visual_scale)*GPU_ZOOM_LERP
        self._reposition_gpu_tiles()
        # Defensive guard: Kivy may deliver a scheduled callback during widget
        # teardown or before the first redraw. Never let that callback kill App.
        if not hasattr(self, "_pulse_ring"):
            self._pulse_ring = None
        if not hasattr(self, "_wind_anim_lines"):
            self._wind_anim_lines = []
        self._map_anim_t += float(dt)
        # Do not rebuild the canvas every frame. Update only tiny instructions.
        if self._pulse_ring is not None:
            import math
            cx=self.x+self.width*.5; cy=self.y+self.height*.5
            radius=dp(14.0+6.0*(0.5+0.5*math.sin(self._map_anim_t*2.4)))
            self._pulse_ring.circle=(cx,cy,radius)
            self._pulse_ring.width=1.0
        if self.layer=="wind" and self._wind_anim_lines:
            w=max(1.0,self.width); h=max(1.0,self.height)
            phase=self._map_anim_t*55.0
            for idx,(line,base_x,base_y) in enumerate(self._wind_anim_lines):
                x=self.x+((base_x-self.x+phase+idx*13)%w)
                y=self.y+((base_y-self.y+phase*.22+idx*7)%h)
                line.points=[x,y,x+dp(20),y]

    def _map_pixel(self,lat,lon):
        z=max(MAP_MIN_ZOOM,min(MAP_MAX_ZOOM,int(self.zoom))); x,y=_lonlat_to_tile(lat,lon,z); cx,cy=_lonlat_to_tile(self.lat,self.lon,z)
        return self.x+self.width/2+(x-cx)*self.tile_size, self.y+self.height/2+(cy-y)*self.tile_size

    def _draw_grid_points(self,grid,w,h):
        if not grid:return
        for item in grid:
            px,py=self._map_pixel(item["lat"],item["lon"])
            if px<self.x-dp(20) or px>self.right+dp(20) or py<self.y-dp(20) or py>self.top+dp(20): continue
            if self.layer=="temperature" and item.get("temp") is not None:
                v=max(-10,min(42,float(item["temp"]))); t=(v+10)/52
                # red/blue interpolation without requiring external map tiles
                r=.20+.75*t; b=.90-.65*t; g=.45+.25*(1-abs(t-.5)*2)
                Color(r,g,b,.30); self.canvas.after.add(Ellipse(pos=(px-dp(38),py-dp(38)),size=(dp(76),dp(76))))
            elif self.layer=="clouds" and item.get("cloud") is not None:
                a=.10+.45*float(item["cloud"])/100; Color(.78,.88,1,a); self.canvas.after.add(Ellipse(pos=(px-dp(34),py-dp(20)),size=(dp(68),dp(40))))
            elif self.layer=="wind" and item.get("wind") is not None:
                speed=float(item["wind"]); direction=float(item.get("dir") or 0); import math
                length=dp(18+min(speed,55)*.35); rad=math.radians(direction)
                ex=px+math.sin(rad)*length; ey=py+math.cos(rad)*length
                Color(.20,.82,1,.82); self.canvas.after.add(Line(points=[px,py,ex,ey],width=1.5))
                ah=dp(5); Color(.20,.82,1,.82); self.canvas.after.add(Line(points=[ex,ey,ex-math.sin(rad+.65)*ah,ey-math.cos(rad+.65)*ah],width=1.2)); self.canvas.after.add(Line(points=[ex,ey,ex-math.sin(rad-.65)*ah,ey-math.cos(rad-.65)*ah],width=1.2))
            elif self.layer=="lightning" and item.get("storm"):
                Color(1,.84,.20,.92); self.canvas.after.add(Ellipse(pos=(px-dp(7),py-dp(7)),size=(dp(14),dp(14)))); self.canvas.after.add(Line(circle=(px,py,dp(16)),width=1.1))

    def _update_legend(self):
        if self.layer=="temperature": self.legend_value.text="−10°   0°   15°   30°   40°C"; self.legend_hint.text=self._t("now")
        elif self.layer=="rain": self.legend_value.text="Radar • 10 min"; self.legend_hint.text=self._t("live")
        elif self.layer=="wind": self.legend_value.text="0 → 20 → 50+ km/h"; self.legend_hint.text=self._t("now")
        elif self.layer=="clouds": self.legend_value.text="0% → 50% → 100%"; self.legend_hint.text=self._t("now")
        elif self.layer=="satellite": self.legend_value.text="Live imagery"; self.legend_hint.text=self._t("now")
        else: self.legend_value.text="●"; self.legend_hint.text=self._t("risk")

    def load_live_grid(self, force=False):
        if self.layer=="satellite":
            return
        now = time.monotonic()
        center = self._last_grid_center
        # Keep the map fluid. Re-use the last grid for 20s unless the user has
        # moved far enough that the visible weather field is materially new.
        if not force and center is not None and (now - self._last_grid_fetch_at) < 20.0:
            if abs(center[0]-self.lat) < 2.0 and abs(center[1]-self.lon) < 2.0:
                return
        self._last_grid_fetch_at = now
        self._last_grid_center = (float(self.lat), float(self.lon))
        self.data_token+=1; token=self.data_token
        threading.Thread(target=self._grid_worker,args=(token,),daemon=True).start()

    def _grid_worker(self,token):
        try:
            if IS_MOBILE_RUNTIME:
                offsets=(-1,0,1); step=1.75
            else:
                offsets=(-2,-1,0,1,2); step=1.25
            lats=[]; lons=[]
            for dy in offsets:
                for dx in offsets:
                    lats.append(self.lat+dy*step); lons.append(self.lon+dx*step)
            params={"latitude":",".join(f"{v:.4f}" for v in lats),"longitude":",".join(f"{v:.4f}" for v in lons),"current":"temperature_2m,cloud_cover,wind_speed_10m,wind_direction_10m,weather_code","timezone":"auto","wind_speed_unit":"kmh"}
            r=requests.get(OPEN_METEO_FORECAST_URL,params=_open_meteo_params(params),timeout=12); r.raise_for_status(); data=r.json()
            rows=data if isinstance(data,list) else [data]
            grid=[]
            for i,row in enumerate(rows[:len(lats)]):
                cur=row.get("current",{})
                grid.append({"lat":lats[i],"lon":lons[i],"temp":cur.get("temperature_2m"),"cloud":cur.get("cloud_cover"),"wind":cur.get("wind_speed_10m"),"dir":cur.get("wind_direction_10m"),"storm":int(cur.get("weather_code",0) or 0) in (95,96,99)})
            if token==self.data_token: Clock.schedule_once(lambda *_:self._apply_grid(grid),0)
        except Exception as e: print("Canlı harita veri hatası:",e)

    def _apply_grid(self,grid):
        self._last_grid = grid
        self._redraw_overlay(grid)
        if self.layer=="temperature":
            center=min(grid,key=lambda x:(x["lat"]-self.lat)**2+(x["lon"]-self.lon)**2)
            if center.get("temp") is not None: self.legend_hint.text=f"{self._t('now')}: {center['temp']:.1f}°C"
        elif self.layer=="wind":
            center=min(grid,key=lambda x:(x["lat"]-self.lat)**2+(x["lon"]-self.lon)**2)
            if center.get("wind") is not None: self.legend_hint.text=f"{self._t('now')}: {center['wind']:.1f} km/h"
        elif self.layer=="clouds":
            center=min(grid,key=lambda x:(x["lat"]-self.lat)**2+(x["lon"]-self.lon)**2)
            if center.get("cloud") is not None: self.legend_hint.text=f"{self._t('now')}: {center['cloud']:.0f}%"

    def load_radar(self):
        if APP_STORE_BUILD and not RAINVIEWER_COMMERCIAL_ENABLED:
            self.radar_label.text = self._t("radar") + " • unavailable"
            return
        if self._radar_loading:
            return
        self._radar_loading = True
        threading.Thread(target=self._radar_worker,daemon=True).start()

    def _radar_worker(self):
        try:
            r=requests.get(RAINVIEWER_API,timeout=10,headers={"User-Agent":MAP_USER_AGENT}); r.raise_for_status(); data=r.json(); radar=(data.get("radar") or {}).get("past") or []
            if not radar:
                self._radar_loading = False
                return
            self.radar_host=data.get("host"); self.radar_frames=radar; self.radar_index=len(radar)-1
            def apply(*_):
                self.radar_slider.max=max(1,len(radar)-1); self.radar_slider.value=self.radar_index; self.refresh_labels()
                if self.layer=="rain":self._load_radar_frame(self.radar_index)
            Clock.schedule_once(apply,0)
        except Exception as e: print("Radar metadata hatası:",e)

    def _radar_slider_changed(self,*_):
        if self.layer=="rain" and self.radar_frames:
            self.radar_index=int(self.radar_slider.value); self._load_radar_frame(self.radar_index)

    def _radar_step(self,delta):
        try:
            if not self.radar_frames:
                return
            total=len(self.radar_frames)
            self.radar_index=max(0,min(total-1,int(self.radar_index)+int(delta)))
            # Do not assign Slider.value from a background callback unless the value really changed.
            if abs(float(self.radar_slider.value)-self.radar_index) > 0.001:
                self.radar_slider.value=self.radar_index
            self._load_radar_frame(self.radar_index)
        except Exception as e:
            print("Radar kare ilerletme hatası:",e)
            self.radar_playing=False
            if self.radar_event:
                try:self.radar_event.cancel()
                except Exception:pass
                self.radar_event=None
            self.refresh_labels()

    def _radar_tick(self,dt):
        # Clock callback is deliberately isolated so a failed frame cannot terminate Kivy.
        if not self.radar_playing:
            return
        try:
            if not self.radar_frames:
                self.radar_playing=False
                self.refresh_labels()
                return
            # Loop from the newest frame back to the oldest for a continuous radar animation.
            if self.radar_index >= len(self.radar_frames)-1:
                self.radar_index=-1
            self._radar_step(1)
        except Exception as e:
            print("Radar oynatma hatası:",e)
            self.radar_playing=False
            if self.radar_event:
                try:self.radar_event.cancel()
                except Exception:pass
                self.radar_event=None
            self.refresh_labels()

    def toggle_radar_play(self,*_):
        try:
            if not self.radar_frames:
                # Metadata may still be loading; do not close the app.
                self.load_radar()
                return
            self.radar_playing=not self.radar_playing
            if self.radar_event:
                try:self.radar_event.cancel()
                except Exception:pass
                self.radar_event=None
            if self.radar_playing:
                self.radar_event=Clock.schedule_interval(self._radar_tick,0.85)
            self.refresh_labels()
        except Exception as e:
            print("Radar oynatma başlatma hatası:",e)
            self.radar_playing=False
            self.radar_event=None
            self.refresh_labels()

    def _load_radar_frame(self,index):
        if not self.radar_host or not self.radar_frames:return
        try:index=max(0,min(len(self.radar_frames)-1,int(index)))
        except Exception:return
        frame=self.radar_frames[index]; path=frame.get("path")
        if not path:return
        z=max(MAP_MIN_ZOOM,min(RAINVIEWER_MAX_ZOOM,int(self.zoom))); cx,cy=_tile_to_xy(self.lat,self.lon,z)
        self._radar_frame_token += 1
        token=self._radar_frame_token
        threading.Thread(target=self._radar_tiles_worker,args=(path,z,cx,cy,token),daemon=True).start()

    def _radar_tiles_worker(self,path,z,cx,cy,token):
        try:
            if token != self._radar_frame_token or self.layer != "rain":return
            view_w=max(320,int(self.width or 1280)); view_h=max(260,int(self.height or 720))
            if IS_MOBILE_RUNTIME:
                span_x = 4 if view_w <= dp(700) else 5
                span_y = 3 if view_h <= dp(800) else 4
            else:
                span_x=max(5,min(7,(view_w//self.tile_size)+2)); span_y=max(3,min(6,(view_h//self.tile_size)+2))
            while span_x*span_y > GPU_MAX_TILES:
                if span_x >= span_y: span_x -= 1
                else: span_y -= 1
            n=2**z
            cache_dir=self.app.cache_dir if hasattr(self.app,'cache_dir') else os.path.join(os.path.expanduser('~'),'.kivy','weather_tiles')
            radar_dir=os.path.join(cache_dir,"radar"); os.makedirs(radar_dir,exist_ok=True)
            jobs=[]; left=span_x//2; top=span_y//2
            for iy in range(span_y):
                dy=iy-top; y=cy+dy
                if y<0 or y>=n:continue
                for ix in range(span_x):
                    dx=ix-left; x=(cx+dx)%n
                    jobs.append((ix,iy,x,y))
            def fetch(job):
                ix,iy,x,y=job; key=("radar_gpu",path,z,x,y)
                try:
                    with MAP_TILE_MEMORY_LOCK:
                        cached=MAP_TILE_MEMORY.get(key)
                        if cached is not None:
                            MAP_TILE_MEMORY.move_to_end(key); return ix,iy,x,y,cached
                    safe=hashlib.md5(f"{path}|{z}|{x}|{y}".encode()).hexdigest()
                    raw_path=os.path.join(radar_dir,safe+".png")
                    if os.path.exists(raw_path):
                        with open(raw_path,'rb') as fh:data=fh.read()
                    else:
                        url=f"{self.radar_host}{path}/256/{z}/{x}/{y}/2/1_1.png"
                        data=_download_bytes(url,timeout=7,headers={"User-Agent":MAP_USER_AGENT})
                        tmp=raw_path+".part"
                        with open(tmp,'wb') as fh:fh.write(data)
                        try:os.replace(tmp,raw_path)
                        except Exception:
                            try:os.remove(tmp)
                            except Exception:pass
                    with MAP_TILE_MEMORY_LOCK:
                        MAP_TILE_MEMORY[key]=data; MAP_TILE_MEMORY.move_to_end(key)
                        while len(MAP_TILE_MEMORY)>MAP_TILE_MEMORY_LIMIT:MAP_TILE_MEMORY.popitem(last=False)
                    return ix,iy,x,y,data
                except Exception:return ix,iy,x,y,None
            futures=[MAP_TILE_EXECUTOR.submit(fetch,j) for j in jobs]
            results=[]
            for f in as_completed(futures):
                if token != self._radar_frame_token or self.layer != "rain":return
                results.append(f.result())
            results.sort(key=lambda q:(q[1],q[0]))
            if token != self._radar_frame_token or self.layer != "rain":return
            Clock.schedule_once(lambda *_:self._begin_gpu_radar_install(results,path,z,cx,cy,token),0)
        except Exception as e:print("Radar GPU tile hatası:",e)

    def _begin_gpu_radar_install(self,results,path,z,cx,cy,token):
        if token != self._radar_frame_token or self.layer != "rain":return
        self._radar_generation+=1; generation=self._radar_generation
        self._clear_radar_tiles()
        batch={"results":results,"index":0,"new":[]}
        def tick(dt):
            if token != self._radar_frame_token or self.layer != "rain":
                return False
            added=0
            while batch["index"]<len(results) and added<GPU_TILE_INSTALL_PER_FRAME:
                ix,iy,x,y,data=results[batch["index"]];batch["index"]+=1
                if data:
                    cache_dir=self.app.cache_dir if hasattr(self.app,'cache_dir') else os.path.join(os.path.expanduser('~'),'.kivy','weather_tiles')
                    safe=hashlib.md5(f"{path}|{z}|{x}|{y}".encode()).hexdigest()
                    path2=os.path.join(cache_dir,'radar_gpu_upload',f'{safe}.png')
                    os.makedirs(os.path.dirname(path2),exist_ok=True)
                    if not os.path.exists(path2):
                        try:
                            with open(path2,'wb') as fh:fh.write(data)
                        except Exception:continue
                    img=AsyncImage(source=path2,allow_stretch=True,keep_ratio=False,nocache=False,
                                   size=(self.tile_size,self.tile_size),size_hint=(None,None),opacity=0)
                    img._map_tile_meta=(ix,iy,x,y,z,cx,cy)
                    self.map_scene.add_widget(img);batch["new"].append(img);added+=1
            if batch["index"]>=len(results):
                if not all(getattr(w,"texture",None) is not None for w in batch["new"]):
                    # Poll readiness without blocking the UI thread.
                    return True
                for w in batch["new"]:
                    w.opacity=1 if self.layer=="rain" else 0
                self._clear_radar_tiles()
                self._radar_tiles=batch["new"]
                self._radar_tile_zoom=z;self._radar_tile_center=(self.lat,self.lon)
                self._position_tile_list(self._radar_tiles,z,cx,cy)
                self._set_radar_tiles_visible(self.layer=="rain")
                self._radar_install_event=None
                return False
            return True
        self._radar_install_event=Clock.schedule_interval(tick,1/120.0)


class Card(BoxLayout):

    def __init__(self, **kwargs):

        super().__init__(**kwargs)

        self.padding = dp(8)
        self.spacing = dp(3)

        with self.canvas.before:

            Color(
                0.03,
                0.05,
                0.09,
                0.58
            )

            self.rect = RoundedRectangle(
                pos=self.pos,
                size=self.size,
                radius=[dp(10)]
            )

        self.bind(
            pos=self.sync,
            size=self.sync
        )

    def sync(self, *_):

        self.rect.pos = self.pos
        self.rect.size = self.size


# ============================================================
# ARAMA / SEÇİM PENCERESİ
# ============================================================

class SelectorButton(Button):
    """Popup seçimleri için sade, doğrudan dokunma alanı olan buton."""
    def __init__(self, **kwargs):
        kwargs.setdefault("font_name", FONT_NAME)
        kwargs.setdefault("font_size", "13sp")
        kwargs.setdefault("bold", False)
        kwargs.setdefault("background_normal", "")
        kwargs.setdefault("background_down", "")
        kwargs.setdefault("background_color", get_color_from_hex("#182235"))
        kwargs.setdefault("color", (0.95, 0.97, 1, 1))
        kwargs.setdefault("border", (0, 0, 0, 0))
        super().__init__(**kwargs)

    def on_touch_down(self, touch):
        if self.disabled or not self.collide_point(*touch.pos):
            return super().on_touch_down(touch)
        self.state = "down"
        touch.grab(self)
        return True

    def on_touch_up(self, touch):
        if touch.grab_current is self:
            touch.ungrab(self)
            inside = self.collide_point(*touch.pos)
            self.state = "normal"
            if inside:
                self.dispatch("on_release")
            return True
        return super().on_touch_up(touch)


class SelectorPopup(Popup):

    def __init__(
        self,
        title,
        items,
        callback,
        lang="TR",
        **kwargs
    ):

        self.items = items
        self.callback = callback
        self.lang = lang

        d = LANG_PACKS.get(lang, EN)

        content = BoxLayout(
            orientation="vertical",
            spacing=dp(8),
            padding=dp(10)
        )

        self.search = TextInput(
            hint_text=d["search"],
            multiline=False,
            size_hint_y=None,
            height=dp(42),
            background_color=get_color_from_hex(
                "#121A28"
            ),
            foreground_color=(1, 1, 1, 1),
            cursor_color=(1, 0.6, 0, 1),
            font_name=FONT_NAME,
            font_size="13sp"
        )

        content.add_widget(self.search)

        scroll = ScrollView()

        self.listing = BoxLayout(
            orientation="vertical",
            spacing=dp(4),
            size_hint_y=None
        )

        self.listing.bind(
            minimum_height=self.listing.setter(
                "height"
            )
        )

        scroll.add_widget(self.listing)

        content.add_widget(scroll)

        close_btn = SelectorButton(
            text=d["close"],
            size_hint_y=None,
            height=dp(44),
            background_color=get_color_from_hex("#182235"),
            color=(0.95, 0.97, 1, 1)
        )

        content.add_widget(close_btn)

        super().__init__(
            title=title,
            content=content,
            size_hint=(0.92, 0.86),
            auto_dismiss=True,
            separator_color=get_color_from_hex(
                "#FF9800"
            ),
            background_color=get_color_from_hex(
                "#0B1019"
            )
        )

        self.search.bind(
            text=self.filter_items
        )

        close_btn.bind(
            on_release=lambda *_:
            self.dismiss()
        )

        self.populate(items)

    def populate(self, items):

        self.listing.clear_widgets()

        # 1000 kayıtlık liste.
        # Türkiye ilçeleri 973 olduğu için tamamı sığar.
        for item in items[:1000]:

            if isinstance(item, dict):
                name = item["name"]
            else:
                name = str(item)

            btn = SelectorButton(
                text=str(name),
                size_hint_y=None,
                height=dp(42),
                background_color=get_color_from_hex("#182235"),
                color=(0.95, 0.97, 1, 1)
            )

            btn.bind(
                on_release=lambda _, value=item:
                self.choose(value)
            )

            self.listing.add_widget(btn)

    def filter_items(self, *_):

        query = self.search.text.strip().casefold()

        if not query:
            self.populate(self.items)
            return

        filtered = []

        for item in self.items:

            if isinstance(item, dict):
                name = item["name"]
            else:
                name = str(item)

            if query in name.casefold():
                filtered.append(item)

        self.populate(filtered)

    def choose(self, item):
        try:
            self.callback(item)
        except Exception as exc:
            print("Seçim callback hatası:", exc)
            return
        self.dismiss()


# ============================================================
# İLK AÇILIŞ / ONBOARDING
# ============================================================

class OnboardingOverlay(FloatLayout):
    """Premium ilk açılış akışı. Bir kez tamamlanır; kullanıcı konum izni
    verirse ana ekrana otomatik hava durumuyla geçilir."""
    def __init__(self, app, **kwargs):
        super().__init__(**kwargs)
        self.app = app
        self.page = 0
        self.opacity = 0
        with self.canvas.before:
            Color(0.025, 0.045, 0.08, 0.97)
            self.bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._sync, size=self._sync)

        self.content = BoxLayout(orientation="vertical", padding=(dp(28), dp(40), dp(28), dp(28)), spacing=dp(14))
        self.add_widget(self.content)
        self.eyebrow = ModernLabel(text="WEATHER PRO", font_size="12sp", bold=True,
                                   color=(1, .62, .10, 1), size_hint_y=None, height=dp(28))
        self.icon = ModernLabel(text="☀", font_size="68sp", color=(1,1,1,1), size_hint_y=None, height=dp(95))
        self.title = ModernLabel(text="Dünyanın havasını\ngörün.", font_size="30sp", bold=True,
                                 color=(1,1,1,1), halign="center", valign="middle", size_hint_y=None, height=dp(92))
        self.title.bind(size=lambda *_: setattr(self.title, "text_size", self.title.size))
        self.body = ModernLabel(text="Hava durumuna göre değişen canlı sahneler,\nşehirler ve güvenilir anlık veriler.",
                                font_size="14sp", color=(.78,.84,.92,1), halign="center", valign="middle",
                                size_hint_y=None, height=dp(72))
        self.body.bind(size=lambda *_: setattr(self.body, "text_size", self.body.size))
        self.progress = ModernLabel(text="●  ○  ○", font_size="13sp", color=(1,.62,.10,1),
                                    halign="center", size_hint_y=None, height=dp(28))
        self.action = ModernButton(text="Continue", size_hint_y=None, height=dp(52),
                                   font_size="15sp", background_color=(1,.58,.05,1), color=(.03,.06,.10,1))
        self.action.bind(on_release=self.next)
        self.skip = ModernButton(text="Skip for now", size_hint_y=None, height=dp(38),
                                 font_size="11sp", background_color=(.07,.10,.16,.75), color=(.72,.78,.88,1))
        self.skip.bind(on_release=self.finish)
        for w in (self.eyebrow,self.icon,self.title,self.body): self.content.add_widget(w)
        self.content.add_widget(Widget())
        self.content.add_widget(self.progress); self.content.add_widget(self.action); self.content.add_widget(self.skip)
        self._pages = [
            ("☀", "Dünyanın havasını\\ngörün.", "Hava durumuna göre değişen canlı sahneler,\\nşehirler ve güvenilir anlık veriler.", "Devam Et"),
            ("⌖", "Konumunuza göre\\nhazır olsun.", "Konum izni verirseniz uygulama açılır açılmaz\\nbulunduğunuz yerin havasını getirir.", "Konumumu Kullan"),
            ("◒", "Her gökyüzü\\nbir hikâye.", "Gündüz, gece, yağmur, kar ve fırtına için\\nözel atmosfer ve akıcı hareketler.", "Hava Durumuna Başla"),
        ]

    def on_touch_down(self, touch):
        # Gizli onboarding ekranı ana arayüzün dokunmalarını asla engellemez.
        if self.opacity <= 0.01:
            return False
        return super().on_touch_down(touch)

    def _sync(self, *_): self.bg.pos, self.bg.size = self.pos, self.size
    def show(self):
        self.disabled = False
        self.refresh(); Animation(opacity=1, d=.35, t="out_quad").start(self)
    def refresh(self):
        icon,title,body,button=self._pages[self.page]
        self.icon.text=icon; self.title.text=title.replace('\\n','\n'); self.body.text=body.replace('\\n','\n'); self.action.text=button
        self.progress.text="  ".join("●" if i==self.page else "○" for i in range(3))
        self.skip.text="Skip for now" if self.page < 2 else ""
        self.skip.opacity=1 if self.page < 2 else 0
        self.skip.disabled=self.page >= 2
    def next(self, *_):
        if self.page < 2:
            self.page += 1; self.refresh()
            Animation(opacity=.55,d=.08).start(self.icon)
            Animation(opacity=1,d=.25).start(self.icon)
        else: self.finish_and_location()
    def finish(self, *_): self.finish_and_location()
    def finish_and_location(self):
        try: self.app.store.put("onboarding", completed=True)
        except Exception: pass
        # Fade out and, critically, disable the transparent overlay so it no longer
        # captures touch events from the main screen underneath it.
        Animation(opacity=0,d=.25).start(self)
        def release_touches(*_):
            self.opacity = 0
            self.disabled = True
        Clock.schedule_once(release_touches, .28)
        Clock.schedule_once(lambda *_: self.app.start_auto_location(), .30)


class OfflineOverlay(FloatLayout):
    def __init__(self, app, **kwargs):
        super().__init__(**kwargs); self.app=app; self.opacity=0; self.disabled=True
        with self.canvas.before:
            Color(.02,.035,.06,.96); self.bg=RoundedRectangle(pos=self.pos,size=self.size,radius=[dp(18)])
        self.bind(pos=self._sync,size=self._sync)
        box=BoxLayout(orientation='vertical',padding=dp(28),spacing=dp(12),size_hint=(.88,.56),pos_hint={'center_x':.5,'center_y':.5})
        self.icon=ModernLabel(text="⌁",font_size='54sp',color=(1,.45,.30,1),size_hint_y=None,height=dp(70),halign='center')
        self.title=ModernLabel(text=app.d["no_internet"],font_size='22sp',bold=True,color=(1,1,1,1),halign='center',size_hint_y=None,height=dp(45))
        self.message=ModernLabel(text=app.d["weather_error_detail"],font_size='13sp',color=(.75,.82,.9,1),halign='center',valign='middle',size_hint_y=None,height=dp(65))
        self.retry=ModernButton(text=app.d["retry"],font_size='14sp',size_hint_y=None,height=dp(48),background_color=(1,.58,.05,1),color=(.03,.06,.10,1))
        self.retry.bind(on_release=lambda *_: self.app.retry_weather())
        box.add_widget(self.icon); box.add_widget(self.title); box.add_widget(self.message); box.add_widget(self.retry)
        self.add_widget(box)
    def on_touch_down(self, touch):
        # Gizli hata ekranı ana arayüzün dokunmalarını engellemez.
        if self.opacity <= 0.01:
            return False
        return super().on_touch_down(touch)
    def _sync(self,*_): self.bg.pos,self.bg.size=self.pos,self.size
    def refresh_labels(self):
        self.title.text = self.app.d["no_internet"]
        self.message.text = self.app.d["weather_error_detail"]
        self.retry.text = self.app.d["retry"]
    def show(self): self.refresh_labels(); self.disabled=False; Animation(opacity=1,d=.22).start(self)
    def hide(self):
        self.disabled=True; Animation(opacity=0,d=.18).start(self)


# ============================================================
# ANA UYGULAMA
# ============================================================

class HavaDurumuApp(App):

    def build(self):

        # Yeni kurulumda global başlangıç dili İngilizce.
        self.lang = "EN"
        self.d = LANG_PACKS["EN"]

        self.country_items = self._builtin_country_items()
        self._add_special_regions()
        self.provinces = []
        self.districts = []

        self.country = None
        self.province = None
        self.district = None

        self.lat = None
        self.lon = None

        self.current_code = 0
        self.current_day = True
        self.last_daily = None
        self.last_seasonal = None

        self.card_values = [
            "--",
            "--%",
            "-- hPa",
            "-- km/h",
            "-- km",
            "--%"
        ]

        # ----------------------------------------------------
        # ROOT
        # ----------------------------------------------------

        self.root_layout = FloatLayout()
        self.store = JsonStore(os.path.join(os.path.expanduser("~"), ".havadurumu_pro.json"))
        self._saved_language = None
        try:
            if self.store.exists("preferences"):
                saved = self.store.get("preferences").get("language")
                if saved in LANG_PACKS:
                    self._saved_language = saved
                    self.lang = saved
                    self.d = LANG_PACKS[saved]
        except Exception as e:
            print("Dil tercihi okunamadı:", e)
        self.cache_dir = os.path.join(os.path.expanduser("~"), ".kivy", "weather_tiles")
        os.makedirs(self.cache_dir, exist_ok=True)
        self._auto_location_started = False
        self._location_timer = None
        self._user_language_selected = bool(self._saved_language)
        self._countries_loading = False
        # Her manuel konum değişiminde artar. Eski API cevaplarının yeni konumu ezmesini önler.
        self._location_generation = 0
        self.offline_overlay = OfflineOverlay(self)
        self.onboarding_overlay = OnboardingOverlay(self)

        self.background = WeatherBackground(
            size_hint=(1, 1)
        )
        self.background.set_location("Turkey")

        self.root_layout.add_widget(
            self.background
        )

        # ----------------------------------------------------
        # ANA PANEL
        # ----------------------------------------------------

        self.panel = BoxLayout(
            orientation="vertical",
            padding=dp(12),
            spacing=dp(7)
        )

        # Panel şeffaftır; ana fotoğraf görünmeye devam eder.
        with self.panel.canvas.before:
            Color(0.01, 0.025, 0.06, 0.18)
            self.panel_rect = RoundedRectangle(
                pos=self.panel.pos, size=self.panel.size, radius=[dp(16)]
            )
        self.panel.bind(pos=lambda *_: self._sync_panel(), size=lambda *_: self._sync_panel())

        self.root_layout.add_widget(
            self.panel
        )

        # ----------------------------------------------------
        # BAŞLIK
        # ----------------------------------------------------

        top = BoxLayout(
            size_hint_y=None,
            height=dp(42)
        )

        self.title_label = ModernLabel(
            text=self.d["title"],
            font_size="23sp",
            bold=True,
            color=get_color_from_hex(
                "#FF9800"
            )
        )

        top.add_widget(self.title_label)

        self.lang_btn = ModernButton(
            text=self.lang,
            size_hint_x=None,
            width=dp(62),
            background_color=get_color_from_hex(
                "#F59E0B"
            ),
            color=(0.04, 0.07, 0.12, 1),
            bold=True,
            font_size="12sp",
            size_hint_y=None,
            height=dp(38)
        )

        self.lang_btn.bind(
            on_release=self.open_language_selector
        )

        top.add_widget(
            self.lang_btn
        )

        self.panel.add_widget(top)

        # ----------------------------------------------------
        # ÜLKE
        # ----------------------------------------------------

        self.location_btn = ModernButton(
            text=self.d["select_country"],
            size_hint_y=None,
            height=dp(42),
            bold=True,
            background_color=get_color_from_hex(
                "#111A29"
            )
        )

        self.location_btn.bind(
            on_release=self.select_country
        )

        self.panel.add_widget(
            self.location_btn
        )

        # ----------------------------------------------------
        # İL / İLÇE
        # ----------------------------------------------------

        row = BoxLayout(
            spacing=dp(7),
            size_hint_y=None,
            height=dp(42)
        )

        self.province_btn = ModernButton(
            text=self.d["select_province"],
            bold=True,
            disabled=True,
            background_color=get_color_from_hex(
                "#111A29"
            )
        )

        self.district_btn = ModernButton(
            text=self.d["select_district"],
            bold=True,
            disabled=True,
            background_color=get_color_from_hex(
                "#111A29"
            )
        )

        self.province_btn.bind(
            on_release=self.select_province
        )

        self.district_btn.bind(
            on_release=self.select_district
        )

        row.add_widget(
            self.province_btn
        )

        row.add_widget(
            self.district_btn
        )

        self.panel.add_widget(row)

        # ----------------------------------------------------
        # KONUM
        # ----------------------------------------------------

        self.location_label = ModernLabel(
            text=self.d["location"],
            font_size="11sp",
            color=(0.8, 0.85, 0.9, 0.9),
            size_hint_y=None,
            height=dp(20)
        )

        self.panel.add_widget(
            self.location_label
        )

        # ----------------------------------------------------
        # FOTOĞRAF ÜZERİNDE BÜYÜK ANLIK HAVA
        # ----------------------------------------------------
        hero = Card(orientation="vertical", size_hint_y=None, height=dp(104), spacing=dp(0))

        self.hero_temp = ModernLabel(
            text="-- C", font_size="30sp", bold=True,
            color=(1, 1, 1, 1), size_hint_y=None, height=dp(46)
        )
        self.hero_status = ModernLabel(
            text=self.d["location"], font_size="14sp", bold=True,
            color=(1, 0.72, 0.25, 1), size_hint_y=None, height=dp(26)
        )
        self.hero_feels = ModernLabel(
            text="", font_size="11sp", color=(0.9, 0.94, 1, 0.9),
            size_hint_y=None, height=dp(22)
        )
        hero.add_widget(self.hero_temp)
        hero.add_widget(self.hero_status)
        hero.add_widget(self.hero_feels)
        self.panel.add_widget(hero)

        # ----------------------------------------------------
        # SICAKLIK
        # ----------------------------------------------------

        temp = Card(
            orientation="vertical",
            size_hint_y=None,
            height=dp(70)
        )

        self.max_label = ModernLabel(
            text=f"{self.d['max']}: -- C",
            font_size="16sp",
            bold=True,
            color=get_color_from_hex(
                "#FF5252"
            )
        )

        self.min_label = ModernLabel(
            text=f"{self.d['min']}: -- C",
            font_size="16sp",
            bold=True,
            color=get_color_from_hex(
                "#44D7B6"
            )
        )

        temp.add_widget(
            self.max_label
        )

        temp.add_widget(
            self.min_label
        )

        self.panel.add_widget(
            temp
        )

        # ----------------------------------------------------
        # DETAY BAŞLIĞI
        # ----------------------------------------------------

        self.details_label = ModernLabel(
            text=self.d["details"],
            font_size="12sp",
            bold=True,
            color=get_color_from_hex(
                "#A0AEC0"
            ),
            size_hint_y=None,
            height=dp(20)
        )

        self.panel.add_widget(
            self.details_label
        )

        # ----------------------------------------------------
        # KARTLAR
        # ----------------------------------------------------

        self.grid = GridLayout(
            cols=2,
            spacing=dp(7),
            size_hint_y=None,
            height=dp(184)
        )

        self.panel.add_widget(
            self.grid
        )

        self.update_cards(
            self.card_values
        )

        nav_labels = NAV_TEXT.get(self.lang, NAV_TEXT["EN"])
        for b, label in zip(getattr(self, "nav_buttons", []), nav_labels):
            b.text = label

        # ----------------------------------------------------
        # 30 GÜNLÜK
        # ----------------------------------------------------

        self.forecast_title = ModernLabel(
            text=self.d["forecast"],
            font_size="12sp",
            bold=True,
            color=get_color_from_hex(
                "#A0AEC0"
            ),
            size_hint_y=None,
            height=dp(20)
        )

        self.panel.add_widget(
            self.forecast_title
        )

        self.forecast_scroll = ScrollView()

        self.forecast_box = BoxLayout(
            orientation="vertical",
            spacing=dp(4),
            size_hint_y=None
        )

        self.forecast_box.bind(
            minimum_height=self.forecast_box.setter(
                "height"
            )
        )

        self.forecast_scroll.add_widget(
            self.forecast_box
        )

        self.panel.add_widget(
            self.forecast_scroll
        )

        # ----------------------------------------------------
        # ALT NAVİGASYON - MOCKUP'A BENZER MOBİL MENÜ
        # ----------------------------------------------------
        nav = BoxLayout(orientation="horizontal", spacing=dp(5), size_hint_y=None, height=dp(40))
        self.nav_buttons = []
        nav_actions = [
            lambda *_: None,
            lambda *_: self.city_search_popup(),
            lambda *_: self.show_map_info(),
            lambda *_: self.show_favorites(),
            lambda *_: self.open_language_selector(),
        ]
        nav_labels = NAV_TEXT.get(self.lang, NAV_TEXT["EN"])
        for label, action in zip(nav_labels, nav_actions):
            b = ModernButton(
                text=label,
                font_size="9sp",
                background_color=(0.035, 0.055, 0.09, 0.92),
                color=(0.88, 0.92, 1, 1),
            )
            b.bind(on_release=action)
            self.nav_buttons.append(b)
            nav.add_widget(b)
        self.panel.add_widget(nav)

        # Ülke listesini UI thread'ini kilitlemeden arka planda yükle.
        Clock.schedule_once(lambda *_: self.load_countries_async(), 0)

        # Katmanlar en üstte: onboarding yalnızca ilk açılışta gösterilir.
        self.root_layout.add_widget(self.offline_overlay)
        self.root_layout.add_widget(self.onboarding_overlay)
        if self.store.exists("onboarding") and self.store.get("onboarding").get("completed"):
            self.onboarding_overlay.opacity = 0
            self.onboarding_overlay.disabled = True
            Clock.schedule_once(lambda *_: self.start_auto_location(), .35)
        else:
            Clock.schedule_once(lambda *_: self.onboarding_overlay.show(), .15)

        return self.root_layout

    def _sync_panel(self):
        self.panel_rect.pos = self.panel.pos
        self.panel_rect.size = self.panel.size

        # ========================================================
    # OTOMATİK KONUM / AÇILIŞ
    # ========================================================

    def start_auto_location(self):
        if self._auto_location_started:
            return
        self._auto_location_started = True
        try:
            self.location_label.text = self.d["location_loading"]
            self.title_label.text = self.d["title"]
        except Exception:
            pass

        # Android'de GPS'e geçmeden önce gerçek çalışma zamanı iznini al.
        # İzin verilmezse uygulama tamamen çalışmaya devam eder ve IP konumuna düşer.
        if KIVY_PLATFORM == "android":
            _request_android_location_permission(self._on_location_permission)
        else:
            threading.Thread(target=self._auto_location_thread, daemon=True).start()

    def _on_location_permission(self, granted):
        if granted:
            threading.Thread(target=self._auto_location_thread, daemon=True).start()
        else:
            print("Konum izni reddedildi; IP konumuna geçiliyor.")
            Clock.schedule_once(lambda *_: self._start_ip_location_fallback(), 0)

    def _auto_location_thread(self):
        # Windows'ta IP konumu şehir seviyesinde yaklaşık olabilir. Önce
        # Windows'un kendi Location API'sini deniyoruz; yalnızca başarısız
        # olursa IP fallback'e geçiyoruz. Android'de ise gerçek GPS kullanılır.
        if KIVY_PLATFORM == "win":
            try:
                if self._windows_native_location():
                    return
            except Exception as e:
                print("Windows konum API kullanılamadı, IP konumuna geçiliyor:", e)

        try:
            from plyer import gps
            result = {}
            def on_location(**kwargs):
                result.update(kwargs)
            gps.configure(on_location=on_location, on_status=lambda **kwargs: None)
            gps.start(minTime=1000, minDistance=1)
            for _ in range(12):
                if result.get("lat") is not None and result.get("lon") is not None:
                    break
                time.sleep(1)
            try:
                gps.stop()
            except Exception:
                pass
            if result.get("lat") is not None and result.get("lon") is not None:
                self._reverse_geocode_location(
                    float(result["lat"]), float(result["lon"])
                )
                return
        except Exception as e:
            print("GPS kullanılamadı, IP konumuna geçiliyor:", e)

        self._start_ip_location_fallback()

    def _windows_native_location(self):
        """Windows Location API'den cihazın gerçek konumunu almaya çalışır.

        winrt-Windows.Devices.Geolocation yüklüyse Windows'un konum servislerini
        kullanır. Bu, IP geolocation'a göre çok daha doğru sonuç verir.
        Konum izni/Windows Location Services kapalıysa False döner.
        """
        try:
            from winrt.windows.devices.geolocation import Geolocator
        except Exception as e:
            print("WinRT Geolocation modülü yok:", e)
            return False

        try:
            locator = Geolocator()
            try:
                locator.desired_accuracy_in_meters = 50
            except Exception:
                pass

            # PyWinRT async operation'ı doğrudan bloklayarak tamamlanmasını bekle.
            # Bu kod zaten arka plan thread'inde çalışıyor; Kivy UI kilitlenmez.
            operation = locator.get_geoposition_async()
            try:
                position = operation.get()
            except AttributeError:
                import asyncio
                position = asyncio.run(operation)

            point = position.coordinate.point.position
            lat = float(point.latitude)
            lon = float(point.longitude)
            print("Windows gerçek konum:", lat, lon)
            self._reverse_geocode_location(lat, lon)
            return True
        except Exception as e:
            print("Windows Location API konum alınamadı:", e)
            return False

    def _start_ip_location_fallback(self):
        endpoints = [
            ("https://ipapi.co/json/", lambda d: (d.get("latitude"), d.get("longitude"), d.get("city"), d.get("country_code"))),
            ("https://ipinfo.io/json", lambda d: ((d.get("loc") or ",").split(",")[0], (d.get("loc") or ",").split(",")[1] if "," in str(d.get("loc") or "") else None, d.get("city"), d.get("country"))),
            ("https://ipwho.is/", lambda d: (d.get("latitude"), d.get("longitude"), d.get("city"), d.get("country_code"))),
        ]
        for url, parser in endpoints:
            try:
                r = requests.get(url, timeout=6)
                r.raise_for_status()
                payload = r.json()
                lat, lon, city, country_code = parser(payload)
                if lat is not None and lon is not None:
                    self._apply_auto_location(float(lat), float(lon), city, country_code)
                    return
            except Exception as e:
                print("Konum servisi başarısız:", url, e)
        Clock.schedule_once(lambda *_: self._auto_location_fallback(), 0)

    def _reverse_geocode_location(self, lat, lon):
        # GPS koordinatını gerçek şehir/ülke adına dönüştür. Nominatim başarısız
        # olursa yine koordinat üzerinden hava verisini kullanırız.
        try:
            params = {
                "lat": lat, "lon": lon, "format": "jsonv2",
                "zoom": 10, "addressdetails": 1,
            }
            headers = {"User-Agent": "MetevraWeather/1.0 (weather app)"}
            r = requests.get("https://nominatim.openstreetmap.org/reverse", params=params, headers=headers, timeout=8)
            r.raise_for_status()
            address = r.json().get("address", {}) or {}
            country_code = str(address.get("country_code") or "").upper()
            city = (address.get("city") or address.get("town") or address.get("municipality") or
                    address.get("village") or address.get("suburb") or None)
            state = address.get("state") or address.get("province") or address.get("region")
            self._apply_auto_location(lat, lon, city, country_code, state)
            return
        except Exception as e:
            print("GPS ters geocoding başarısız:", e)
            self._apply_auto_location(lat, lon, None, None, None)

    def _auto_location_fallback(self):
        self.location_label.text = self.d["location"]
        self.title_label.text = self.d["title"]
        self.offline_overlay.hide()

    def _apply_auto_location(self, lat, lon, city=None, country_code=None, state=None):
        """Otomatik konumu uygula; Türkiye'de il + ilçe seçicilerini de hazırla."""
        def apply(*_):
            self._location_generation += 1
            generation = self._location_generation
            self.lat, self.lon = float(lat), float(lon)
            code = str(country_code or "").upper()

            if not self.country_items:
                self.country_items = self._builtin_country_items()
                self._add_special_regions()
            found = next((x for x in self.country_items if x.get("code") == code), None)
            if found:
                self.country = found
            elif code:
                self.country = {"name": code, "code": code}

            country_name = (self.country or {}).get("name", "")
            name = str(city or "Konumunuz")

            # Türkiye'de IP servisleri çoğu zaman state/province alanını vermez.
            # Önce state, sonra şehir adına göre 81 il listesinden eşleştir.
            province_match = None
            if code == "TR":
                provinces = self._builtin_turkish_provinces()
                state_text = str(state or "").strip()
                city_text = name.strip()
                for candidate in provinces:
                    cname = str(candidate.get("name", "")).casefold()
                    if state_text and cname == state_text.casefold():
                        province_match = candidate
                        break
                if province_match is None:
                    for candidate in provinces:
                        cname = str(candidate.get("name", "")).casefold()
                        if cname == city_text.casefold():
                            province_match = candidate
                            break
                # Common administrative-name variants returned by geocoders.
                if province_match is None:
                    normalized = {
                        "istanbul": "İstanbul", "izmir": "İzmir", "ankara": "Ankara",
                        "konya": "Konya", "adana": "Adana", "bursa": "Bursa",
                        "antalya": "Antalya", "gaziantep": "Gaziantep",
                    }
                    alias_name = normalized.get(city_text.casefold())
                    if alias_name:
                        province_match = next(
                            (x for x in provinces if x.get("name") == alias_name), None
                        )

                self.provinces = provinces
                self.province = province_match
                if province_match:
                    self.province_btn.text = province_match["name"]
                    self.province_btn.disabled = False
                    self.district_btn.disabled = False
                    self.district_btn.text = self.d["loading"]
                    # Otomatik konumda şehir ilçe olarak geldiyse önce hava verisini
                    # doğrudan koordinattan göster; ardından ilçe listesi hazır olsun.
                    self.district = name if name.casefold() != province_match["name"].casefold() else None
                    if self.district:
                        self.district_btn.text = self.district
                    threading.Thread(
                        target=self.load_districts,
                        args=(province_match["id"], generation),
                        daemon=True
                    ).start()
                else:
                    self.province = None
                    self.province_btn.text = self.d["select_province"]
                    self.province_btn.disabled = False
                    self.district = name
                    self.district_btn.disabled = False
                    self.district_btn.text = name
            else:
                self.province = None
                self.province_btn.text = self.d["province"]
                self.province_btn.disabled = True
                self.district = name
                self.district_btn.disabled = False
                self.district_btn.text = name

            self.location_btn.text = country_name or self.d["select_country"]
            self.location_label.text = f"{name} / {country_name}" if country_name else name
            self.title_label.text = name.upper()
            self.background.set_location(
                f"{name}, {country_name}" if country_name else name,
                self.lat, self.lon
            )
            self.offline_overlay.hide()
            self.fetch_weather(generation)

        Clock.schedule_once(apply, 0)

    def retry_weather(self):
        self.offline_overlay.hide()
        if self.lat is not None and self.lon is not None:
            self.fetch_weather()
        else:
            self._auto_location_started=False
            self.start_auto_location()

# ========================================================
    # DİL
    # ========================================================

    def open_language_selector(self, *_):
        SelectorPopup(
            self.d.get("language", "Language"),
            LANGUAGE_ITEMS,
            lambda item: self.set_language(item.get("code", "EN")),
            self.lang
        ).open()

    def set_language(self, lang):
        lang = lang if lang in LANG_PACKS else "EN"
        self._user_language_selected = True
        self.lang = lang
        self.d = LANG_PACKS[lang]
        self.lang_btn.text = lang
        try:
            self.store.put("preferences", language=lang)
        except Exception as e:
            print("Dil tercihi kaydedilemedi:", e)
        self.refresh_labels()
        # Harita açıksa üzerindeki tüm metinleri de anında yenile.
        map_view = getattr(self, "_map_view", None)
        if map_view is not None:
            try:
                map_view.refresh_labels()
                map_view._redraw_overlay(getattr(map_view, "_last_grid", None))
            except Exception as e:
                print("Harita dil yenileme hatası:", e)


    def refresh_labels(self):

        if not self.country:
            self.location_btn.text = (
                self.d["select_country"]
            )

        if not self.province:
            self.province_btn.text = (
                self.d["select_province"]
            )

        if not self.district:
            self.district_btn.text = (
                self.d["select_district"]
            )

        self.title_label.text = (
            self.district.upper()
            if self.district
            else self.d["title"]
        )

        self.details_label.text = (
            self.d["details"]
        )

        self.forecast_title.text = (
            self.d["forecast"]
        )

        # Sıcaklık değerlerinin son kısmını koru.
        max_value = (
            self.max_label.text.split(":")[-1].strip()
        )

        min_value = (
            self.min_label.text.split(":")[-1].strip()
        )

        self.max_label.text = (
            f"{self.d['max']}: {max_value}"
        )

        self.min_label.text = (
            f"{self.d['min']}: {min_value}"
        )

        self.update_cards(
            self.card_values
        )

        if self.last_daily:
            try:
                self.build_forecast(self.last_daily, self.last_seasonal)
            except Exception as e:
                print("Dil değişiminde tahmin yenileme hatası:", e)

        if self.current_code is not None:
            self.hero_status.text = weather_text(self.current_code, self.lang)
        try:
            self.offline_overlay.refresh_labels()
        except Exception:
            pass

    # ========================================================
    # TÜM ÜLKELER
    # ========================================================

    def load_countries(self):
        """Tüm ülkeleri API'den alır; pycountry zorunlu değildir."""
        try:
            response = requests.get(
                "https://restcountries.com/v3.1/all",
                params={"fields": "name,cca2"},
                timeout=15
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise ValueError("Ülke servisi liste döndürmedi")

            items = []
            for item in payload:
                if not isinstance(item, dict):
                    continue
                name_obj = item.get("name", {})
                if isinstance(name_obj, dict):
                    name = name_obj.get("common") or name_obj.get("official")
                else:
                    name = str(name_obj)
                code = str(item.get("cca2") or "").upper()
                if name and code:
                    display_name = "Kıbrıs" if code == "CY" else str(name)
                    items.append({"name": display_name, "code": code})

            if not items:
                raise ValueError("Ülke listesi boş")
            self.country_items = [x for x in items if x.get("code") != "AM" and str(x.get("name", "")).casefold() != "armenia"]
            self._add_special_regions()
            self.country_items = sorted(self.country_items, key=lambda x: x["name"].casefold())
            print("Ülke sayısı:", len(self.country_items))
        except Exception as error:
            print("Ülke listesi alınamadı:", error)
            # İnternet/API yoksa bile yaklaşık tüm ISO-3166 bölge/ülke
            # listesini yerleşik olarak kullan. Böylece pycountry kurulumu şart değildir.
            self.country_items = [
                {"name": 'Ascension Island', "code": "AC"},
                {"name": 'Andorra', "code": "AD"},
                {"name": 'United Arab Emirates', "code": "AE"},
                {"name": 'Afghanistan', "code": "AF"},
                {"name": 'Antigua & Barbuda', "code": "AG"},
                {"name": 'Anguilla', "code": "AI"},
                {"name": 'Albania', "code": "AL"},
                {"name": 'Angola', "code": "AO"},
                {"name": 'Antarctica', "code": "AQ"},
                {"name": 'Argentina', "code": "AR"},
                {"name": 'American Samoa', "code": "AS"},
                {"name": 'Austria', "code": "AT"},
                {"name": 'Australia', "code": "AU"},
                {"name": 'Aruba', "code": "AW"},
                {"name": 'Åland Islands', "code": "AX"},
                {"name": 'Azerbaijan', "code": "AZ"},
                {"name": 'Bosnia & Herzegovina', "code": "BA"},
                {"name": 'Barbados', "code": "BB"},
                {"name": 'Bangladesh', "code": "BD"},
                {"name": 'Belgium', "code": "BE"},
                {"name": 'Burkina Faso', "code": "BF"},
                {"name": 'Bulgaria', "code": "BG"},
                {"name": 'Bahrain', "code": "BH"},
                {"name": 'Burundi', "code": "BI"},
                {"name": 'Benin', "code": "BJ"},
                {"name": 'St. Barthélemy', "code": "BL"},
                {"name": 'Bermuda', "code": "BM"},
                {"name": 'Brunei', "code": "BN"},
                {"name": 'Bolivia', "code": "BO"},
                {"name": 'Caribbean Netherlands', "code": "BQ"},
                {"name": 'Brazil', "code": "BR"},
                {"name": 'Bahamas', "code": "BS"},
                {"name": 'Bhutan', "code": "BT"},
                {"name": 'Bouvet Island', "code": "BV"},
                {"name": 'Botswana', "code": "BW"},
                {"name": 'Belarus', "code": "BY"},
                {"name": 'Belize', "code": "BZ"},
                {"name": 'Canada', "code": "CA"},
                {"name": 'Cocos (Keeling) Islands', "code": "CC"},
                {"name": 'Congo - Kinshasa', "code": "CD"},
                {"name": 'Central African Republic', "code": "CF"},
                {"name": 'Congo - Brazzaville', "code": "CG"},
                {"name": 'Switzerland', "code": "CH"},
                {"name": 'Côte d’Ivoire', "code": "CI"},
                {"name": 'Cook Islands', "code": "CK"},
                {"name": 'Chile', "code": "CL"},
                {"name": 'Cameroon', "code": "CM"},
                {"name": 'China', "code": "CN"},
                {"name": 'Colombia', "code": "CO"},
                {"name": 'Clipperton Island', "code": "CP"},
                {"name": 'Sark', "code": "CQ"},
                {"name": 'Costa Rica', "code": "CR"},
                {"name": 'Cuba', "code": "CU"},
                {"name": 'Cape Verde', "code": "CV"},
                {"name": 'Curaçao', "code": "CW"},
                {"name": 'Christmas Island', "code": "CX"},
                {"name": 'Kıbrıs', "code": "CY"},
                {"name": 'Czechia', "code": "CZ"},
                {"name": 'Germany', "code": "DE"},
                {"name": 'Diego Garcia', "code": "DG"},
                {"name": 'Djibouti', "code": "DJ"},
                {"name": 'Denmark', "code": "DK"},
                {"name": 'Dominica', "code": "DM"},
                {"name": 'Dominican Republic', "code": "DO"},
                {"name": 'Algeria', "code": "DZ"},
                {"name": 'Ceuta & Melilla', "code": "EA"},
                {"name": 'Ecuador', "code": "EC"},
                {"name": 'Estonia', "code": "EE"},
                {"name": 'Egypt', "code": "EG"},
                {"name": 'Western Sahara', "code": "EH"},
                {"name": 'Eritrea', "code": "ER"},
                {"name": 'Spain', "code": "ES"},
                {"name": 'Ethiopia', "code": "ET"},
                {"name": 'European Union', "code": "EU"},
                {"name": 'Eurozone', "code": "EZ"},
                {"name": 'Finland', "code": "FI"},
                {"name": 'Fiji', "code": "FJ"},
                {"name": 'Falkland Islands', "code": "FK"},
                {"name": 'Micronesia', "code": "FM"},
                {"name": 'Faroe Islands', "code": "FO"},
                {"name": 'France', "code": "FR"},
                {"name": 'Gabon', "code": "GA"},
                {"name": 'United Kingdom', "code": "GB"},
                {"name": 'Grenada', "code": "GD"},
                {"name": 'Georgia', "code": "GE"},
                {"name": 'French Guiana', "code": "GF"},
                {"name": 'Guernsey', "code": "GG"},
                {"name": 'Ghana', "code": "GH"},
                {"name": 'Gibraltar', "code": "GI"},
                {"name": 'Greenland', "code": "GL"},
                {"name": 'Gambia', "code": "GM"},
                {"name": 'Guinea', "code": "GN"},
                {"name": 'Guadeloupe', "code": "GP"},
                {"name": 'Equatorial Guinea', "code": "GQ"},
                {"name": 'Greece', "code": "GR"},
                {"name": 'South Georgia & South Sandwich Islands', "code": "GS"},
                {"name": 'Guatemala', "code": "GT"},
                {"name": 'Guam', "code": "GU"},
                {"name": 'Guinea-Bissau', "code": "GW"},
                {"name": 'Guyana', "code": "GY"},
                {"name": 'Hong Kong SAR China', "code": "HK"},
                {"name": 'Heard & McDonald Islands', "code": "HM"},
                {"name": 'Honduras', "code": "HN"},
                {"name": 'Croatia', "code": "HR"},
                {"name": 'Haiti', "code": "HT"},
                {"name": 'Hungary', "code": "HU"},
                {"name": 'Canary Islands', "code": "IC"},
                {"name": 'Indonesia', "code": "ID"},
                {"name": 'Ireland', "code": "IE"},
                {"name": 'Israel', "code": "IL"},
                {"name": 'Isle of Man', "code": "IM"},
                {"name": 'India', "code": "IN"},
                {"name": 'British Indian Ocean Territory', "code": "IO"},
                {"name": 'Iraq', "code": "IQ"},
                {"name": 'Iran', "code": "IR"},
                {"name": 'Iceland', "code": "IS"},
                {"name": 'Italy', "code": "IT"},
                {"name": 'Jersey', "code": "JE"},
                {"name": 'Jamaica', "code": "JM"},
                {"name": 'Jordan', "code": "JO"},
                {"name": 'Japan', "code": "JP"},
                {"name": 'Kenya', "code": "KE"},
                {"name": 'Kyrgyzstan', "code": "KG"},
                {"name": 'Cambodia', "code": "KH"},
                {"name": 'Kiribati', "code": "KI"},
                {"name": 'Comoros', "code": "KM"},
                {"name": 'St. Kitts & Nevis', "code": "KN"},
                {"name": 'North Korea', "code": "KP"},
                {"name": 'South Korea', "code": "KR"},
                {"name": 'Kuwait', "code": "KW"},
                {"name": 'Cayman Islands', "code": "KY"},
                {"name": 'Kazakhstan', "code": "KZ"},
                {"name": 'Laos', "code": "LA"},
                {"name": 'Lebanon', "code": "LB"},
                {"name": 'St. Lucia', "code": "LC"},
                {"name": 'Liechtenstein', "code": "LI"},
                {"name": 'Sri Lanka', "code": "LK"},
                {"name": 'Liberia', "code": "LR"},
                {"name": 'Lesotho', "code": "LS"},
                {"name": 'Lithuania', "code": "LT"},
                {"name": 'Luxembourg', "code": "LU"},
                {"name": 'Latvia', "code": "LV"},
                {"name": 'Libya', "code": "LY"},
                {"name": 'Morocco', "code": "MA"},
                {"name": 'Monaco', "code": "MC"},
                {"name": 'Moldova', "code": "MD"},
                {"name": 'Montenegro', "code": "ME"},
                {"name": 'St. Martin', "code": "MF"},
                {"name": 'Madagascar', "code": "MG"},
                {"name": 'Marshall Islands', "code": "MH"},
                {"name": 'North Macedonia', "code": "MK"},
                {"name": 'Mali', "code": "ML"},
                {"name": 'Myanmar (Burma)', "code": "MM"},
                {"name": 'Mongolia', "code": "MN"},
                {"name": 'Macao SAR China', "code": "MO"},
                {"name": 'Northern Mariana Islands', "code": "MP"},
                {"name": 'Martinique', "code": "MQ"},
                {"name": 'Mauritania', "code": "MR"},
                {"name": 'Montserrat', "code": "MS"},
                {"name": 'Malta', "code": "MT"},
                {"name": 'Mauritius', "code": "MU"},
                {"name": 'Maldives', "code": "MV"},
                {"name": 'Malawi', "code": "MW"},
                {"name": 'Mexico', "code": "MX"},
                {"name": 'Malaysia', "code": "MY"},
                {"name": 'Mozambique', "code": "MZ"},
                {"name": 'Namibia', "code": "NA"},
                {"name": 'New Caledonia', "code": "NC"},
                {"name": 'Niger', "code": "NE"},
                {"name": 'Norfolk Island', "code": "NF"},
                {"name": 'Nigeria', "code": "NG"},
                {"name": 'Nicaragua', "code": "NI"},
                {"name": 'Netherlands', "code": "NL"},
                {"name": 'Norway', "code": "NO"},
                {"name": 'Nepal', "code": "NP"},
                {"name": 'Nauru', "code": "NR"},
                {"name": 'Niue', "code": "NU"},
                {"name": 'New Zealand', "code": "NZ"},
                {"name": 'Oman', "code": "OM"},
                {"name": 'Panama', "code": "PA"},
                {"name": 'Peru', "code": "PE"},
                {"name": 'French Polynesia', "code": "PF"},
                {"name": 'Papua New Guinea', "code": "PG"},
                {"name": 'Philippines', "code": "PH"},
                {"name": 'Pakistan', "code": "PK"},
                {"name": 'Poland', "code": "PL"},
                {"name": 'St. Pierre & Miquelon', "code": "PM"},
                {"name": 'Pitcairn Islands', "code": "PN"},
                {"name": 'Puerto Rico', "code": "PR"},
                {"name": 'Palestinian Territories', "code": "PS"},
                {"name": 'Portugal', "code": "PT"},
                {"name": 'Palau', "code": "PW"},
                {"name": 'Paraguay', "code": "PY"},
                {"name": 'Qatar', "code": "QA"},
                {"name": 'Outlying Oceania', "code": "QO"},
                {"name": 'Réunion', "code": "RE"},
                {"name": 'Romania', "code": "RO"},
                {"name": 'Serbia', "code": "RS"},
                {"name": 'Russia', "code": "RU"},
                {"name": 'Rwanda', "code": "RW"},
                {"name": 'Saudi Arabia', "code": "SA"},
                {"name": 'Solomon Islands', "code": "SB"},
                {"name": 'Seychelles', "code": "SC"},
                {"name": 'Sudan', "code": "SD"},
                {"name": 'Sweden', "code": "SE"},
                {"name": 'Singapore', "code": "SG"},
                {"name": 'St. Helena', "code": "SH"},
                {"name": 'Slovenia', "code": "SI"},
                {"name": 'Svalbard & Jan Mayen', "code": "SJ"},
                {"name": 'Slovakia', "code": "SK"},
                {"name": 'Sierra Leone', "code": "SL"},
                {"name": 'San Marino', "code": "SM"},
                {"name": 'Senegal', "code": "SN"},
                {"name": 'Somalia', "code": "SO"},
                {"name": 'Suriname', "code": "SR"},
                {"name": 'South Sudan', "code": "SS"},
                {"name": 'São Tomé & Príncipe', "code": "ST"},
                {"name": 'El Salvador', "code": "SV"},
                {"name": 'Sint Maarten', "code": "SX"},
                {"name": 'Syria', "code": "SY"},
                {"name": 'Eswatini', "code": "SZ"},
                {"name": 'Tristan da Cunha', "code": "TA"},
                {"name": 'Turks & Caicos Islands', "code": "TC"},
                {"name": 'Chad', "code": "TD"},
                {"name": 'French Southern Territories', "code": "TF"},
                {"name": 'Togo', "code": "TG"},
                {"name": 'Thailand', "code": "TH"},
                {"name": 'Tajikistan', "code": "TJ"},
                {"name": 'Tokelau', "code": "TK"},
                {"name": 'Timor-Leste', "code": "TL"},
                {"name": 'Turkmenistan', "code": "TM"},
                {"name": 'Tunisia', "code": "TN"},
                {"name": 'Tonga', "code": "TO"},
                {"name": 'Türkiye', "code": "TR"},
                {"name": 'Trinidad & Tobago', "code": "TT"},
                {"name": 'Tuvalu', "code": "TV"},
                {"name": 'Taiwan', "code": "TW"},
                {"name": 'Tanzania', "code": "TZ"},
                {"name": 'Ukraine', "code": "UA"},
                {"name": 'Uganda', "code": "UG"},
                {"name": 'U.S. Outlying Islands', "code": "UM"},
                {"name": 'United Nations', "code": "UN"},
                {"name": 'United States', "code": "US"},
                {"name": 'Uruguay', "code": "UY"},
                {"name": 'Uzbekistan', "code": "UZ"},
                {"name": 'Vatican City', "code": "VA"},
                {"name": 'St. Vincent & Grenadines', "code": "VC"},
                {"name": 'Venezuela', "code": "VE"},
                {"name": 'British Virgin Islands', "code": "VG"},
                {"name": 'U.S. Virgin Islands', "code": "VI"},
                {"name": 'Vietnam', "code": "VN"},
                {"name": 'Vanuatu', "code": "VU"},
                {"name": 'Wallis & Futuna', "code": "WF"},
                {"name": 'Samoa', "code": "WS"},
                {"name": 'Pseudo-Accents', "code": "XA"},
                {"name": 'Pseudo-Bidi', "code": "XB"},
                {"name": 'Kosovo', "code": "XK"},
                {"name": 'Yemen', "code": "YE"},
                {"name": 'Mayotte', "code": "YT"},
                {"name": 'South Africa', "code": "ZA"},
                {"name": 'Zambia', "code": "ZM"},
                {"name": 'Zimbabwe', "code": "ZW"}
            ]
            self.country_items = [x for x in self.country_items if x.get("code") != "AM" and str(x.get("name", "")).casefold() != "armenia"]
            self._add_special_regions()

    def _add_special_regions(self):
        if not any(x.get("code") == "KKTC" for x in self.country_items):
            self.country_items.append({
                "name": "Kuzey Kıbrıs Türk Cumhuriyeti (KKTC)",
                "code": "KKTC",
                "special": "northern_cyprus"
            })

    def select_country(self, *_):
        # Ağ isteğini UI thread'inde yapma. İlk tıklamada yerleşik listeyi
        # anında aç, tam listeyi arka planda yenile.
        if not self.country_items:
            self.country_items = self._builtin_country_items()
            self._add_special_regions()
            self.country_items = sorted(self.country_items, key=lambda x: x["name"].casefold())
            self.load_countries_async()

        SelectorPopup(
            self.d["country"],
            self.country_items,
            self.country_chosen,
            self.lang
        ).open()

    def load_countries_async(self):
        if self._countries_loading:
            return
        self._countries_loading = True
        threading.Thread(target=self._load_countries_worker, daemon=True).start()

    def _load_countries_worker(self):
        try:
            self.load_countries()
        finally:
            self._countries_loading = False

    def _builtin_country_items(self):
        return [
            {"name":"Türkiye","code":"TR"},{"name":"United States","code":"US"},
            {"name":"United Kingdom","code":"GB"},{"name":"Germany","code":"DE"},
            {"name":"France","code":"FR"},{"name":"Spain","code":"ES"},{"name":"Italy","code":"IT"},
            {"name":"Portugal","code":"PT"},{"name":"Netherlands","code":"NL"},{"name":"Poland","code":"PL"},
            {"name":"Greece","code":"GR"},{"name":"Romania","code":"RO"},{"name":"Bulgaria","code":"BG"},
            {"name":"Serbia","code":"RS"},{"name":"Ukraine","code":"UA"},{"name":"Russia","code":"RU"},
            {"name":"Azerbaijan","code":"AZ"},{"name":"Georgia","code":"GE"},{"name":"United Arab Emirates","code":"AE"},
            {"name":"Saudi Arabia","code":"SA"},{"name":"Qatar","code":"QA"},{"name":"Egypt","code":"EG"},
            {"name":"Canada","code":"CA"},{"name":"Australia","code":"AU"},{"name":"Japan","code":"JP"},
            {"name":"South Korea","code":"KR"},{"name":"China","code":"CN"},{"name":"India","code":"IN"},
            {"name":"Indonesia","code":"ID"},{"name":"Thailand","code":"TH"},{"name":"Vietnam","code":"VN"},
        ]

    def _language_from_system_locale(self):
        try:
            loc = locale.getlocale()[0] or locale.getdefaultlocale()[0] or ""
            lang = str(loc).split("_")[0].lower()
            mapping = {
                "tr":"TR", "en":"EN", "de":"DE", "fr":"FR", "es":"ES",
                "it":"IT", "pt":"PT", "ru":"RU", "ar":"AR", "zh":"ZH",
                "ja":"JA", "ko":"KO", "nl":"NL", "pl":"PL", "el":"EL",
                "ro":"RO", "bg":"BG", "sr":"SR", "uk":"UK", "he":"HE",
                "hi":"HI", "id":"ID", "th":"TH", "vi":"VI", "fa":"FA"
            }
            return mapping.get(lang, "EN")
        except Exception:
            return "EN"

    def country_chosen(self, item):

        # Yeni seçim geldiğinde önceki şehir/ülke isteklerini geçersiz kıl.
        self._location_generation += 1
        generation = self._location_generation

        self.country = item

        # Kullanıcı dili elle seçtiyse ülke değişimi BU SEÇİMİ ASLA EZMEZ.
        # Otomatik ülke->dil eşlemesi yalnızca uygulama ilk kez dil belirlerken kullanılır.
        country_code = str(item.get("code") or "").upper()
        if not getattr(self, "_user_language_selected", False):
            auto_lang = COUNTRY_LANGUAGE_MAP.get(country_code, "EN") if country_code else "EN"
            self.lang = auto_lang if auto_lang in LANG_PACKS else "EN"
            self.d = LANG_PACKS[self.lang]
            self.lang_btn.text = self.lang

        self.province = None
        self.district = None
        self.districts = []
        self.lat = None
        self.lon = None
        self.current_code = 3
        self.last_daily = None
        self.last_seasonal = None
        self.card_values = [
            "--", "--%", "-- hPa", "-- km/h", "-- km", "--%"
        ]

        # Dil, yukarıda seçilen ülkeye göre otomatik ayarlandı.
        self.location_btn.text = item["name"]
        self.province_btn.text = self.d["select_province"]
        self.district_btn.text = self.d["select_district"]
        self.location_label.text = item["name"]
        self.title_label.text = self.d["title"]
        self.hero_temp.text = "-- C"
        self.hero_status.text = self.d["location"]
        self.hero_feels.text = ""
        self.max_label.text = f"{self.d['max']}: -- C"
        self.min_label.text = f"{self.d['min']}: -- C"
        self.update_cards(self.card_values)
        self.refresh_labels()
        self.forecast_box.clear_widgets()
        self.background.set_location(item["name"])
        self.offline_overlay.hide()

        is_turkey = (
            item.get("code") == "TR"
            or str(item.get("name", "")).casefold() in ("turkey", "türkiye")
        )

        if is_turkey:
            self.province_btn.disabled = False
            self.district_btn.disabled = True
            self.province_btn.text = self.d["loading"]
            threading.Thread(
                target=self.load_provinces,
                args=(generation,),
                daemon=True
            ).start()

        elif item.get("code") == "KKTC":
            self.provinces = [
                {"id": "nicosia", "name": "Lefkoşa", "lat": 35.1856, "lon": 33.3823},
                {"id": "famagusta", "name": "Gazimağusa", "lat": 35.1250, "lon": 33.9410},
                {"id": "kyrenia", "name": "Girne", "lat": 35.3410, "lon": 33.3190},
                {"id": "morphou", "name": "Güzelyurt", "lat": 35.1980, "lon": 32.9930},
                {"id": "iskele", "name": "İskele", "lat": 35.2860, "lon": 33.8910},
                {"id": "lefke", "name": "Lefke", "lat": 35.1120, "lon": 32.8500},
            ]
            self.province_btn.disabled = False
            self.district_btn.disabled = True
            self.province_btn.text = self.d["province"] if self.lang == "EN" else "Bölge / İlçe Seç"
            self.location_label.text = item["name"]

        else:
            # Dünya ülkelerinde eyalet/il zorunlu değildir; şehir seçimi doğrudan açılır.
            self.province_btn.text = self.d["province"]
            self.province_btn.disabled = True
            self.district_btn.text = self.d["select_district"]
            self.district_btn.disabled = False

    # ========================================================
    # TÜRKİYE İLLERİ - OFFLINE FALLBACK
    # ========================================================

    def _builtin_turkish_provinces(self):
        pairs = [
            (1,"Adana"),(2,"Adıyaman"),(3,"Afyonkarahisar"),(4,"Ağrı"),(5,"Amasya"),
            (6,"Ankara"),(7,"Antalya"),(8,"Artvin"),(9,"Aydın"),(10,"Balıkesir"),
            (11,"Bilecik"),(12,"Bingöl"),(13,"Bitlis"),(14,"Bolu"),(15,"Burdur"),
            (16,"Bursa"),(17,"Çanakkale"),(18,"Çankırı"),(19,"Çorum"),(20,"Denizli"),
            (21,"Diyarbakır"),(22,"Edirne"),(23,"Elazığ"),(24,"Erzincan"),(25,"Erzurum"),
            (26,"Eskişehir"),(27,"Gaziantep"),(28,"Giresun"),(29,"Gümüşhane"),(30,"Hakkari"),
            (31,"Hatay"),(32,"Isparta"),(33,"Mersin"),(34,"İstanbul"),(35,"İzmir"),
            (36,"Kars"),(37,"Kastamonu"),(38,"Kayseri"),(39,"Kırklareli"),(40,"Kırşehir"),
            (41,"Kocaeli"),(42,"Konya"),(43,"Kütahya"),(44,"Malatya"),(45,"Manisa"),
            (46,"Kahramanmaraş"),(47,"Mardin"),(48,"Muğla"),(49,"Muş"),(50,"Nevşehir"),
            (51,"Niğde"),(52,"Ordu"),(53,"Rize"),(54,"Sakarya"),(55,"Samsun"),
            (56,"Siirt"),(57,"Sinop"),(58,"Sivas"),(59,"Tekirdağ"),(60,"Tokat"),
            (61,"Trabzon"),(62,"Tunceli"),(63,"Şanlıurfa"),(64,"Uşak"),(65,"Van"),
            (66,"Yozgat"),(67,"Zonguldak"),(68,"Aksaray"),(69,"Bayburt"),(70,"Karaman"),
            (71,"Kırıkkale"),(72,"Batman"),(73,"Şırnak"),(74,"Bartın"),(75,"Ardahan"),
            (76,"Iğdır"),(77,"Yalova"),(78,"Karabük"),(79,"Kilis"),(80,"Osmaniye"),(81,"Düzce")
        ]
        return [{"id": code, "name": name} for code, name in pairs]

    def load_provinces(self, generation=None):
        try:
            response = requests.get(
                "https://api.turkiyeapi.dev/v2/provinces?limit=100&fields=id,name",
                timeout=10
            )
            response.raise_for_status()
            payload = response.json()
            rows = payload.get("data", []) if isinstance(payload, dict) else []
            if not isinstance(rows, list):
                raise ValueError("İl API beklenmeyen veri döndürdü")
            provinces = sorted(
                [x for x in rows if isinstance(x, dict) and x.get("id") and x.get("name")],
                key=lambda x: str(x["name"]).casefold()
            )
            if not provinces:
                raise ValueError("İl listesi boş")
        except Exception as error:
            print("İl API hatası, yerleşik liste kullanılıyor:", error)
            provinces = self._builtin_turkish_provinces()

        def apply(*_):
            if generation is not None and generation != self._location_generation:
                return
            if not self.country or self.country.get("code") != "TR":
                return
            self.provinces = provinces
            self.province_btn.disabled = False
            self.province_btn.text = self.d["select_province"]
        Clock.schedule_once(apply, 0)

    def select_province(self, *_):

        if not self.country:
            return

        if self.country.get("code") in ("TR", "KKTC"):
            if self.country.get("code") == "TR" and not self.provinces:
                self.provinces = self._builtin_turkish_provinces()
                self.province_btn.disabled = False
            title = self.d["province"] if self.country.get("code") == "TR" else (
                "KKTC Bölgesi / İlçe" if self.lang == "TR" else "TRNC Region / City"
            )
            SelectorPopup(
                title,
                self.provinces,
                self.province_chosen,
                self.lang
            ).open()

    def province_chosen(self, item):

        self._location_generation += 1
        generation = self._location_generation
        self.province = item
        self.district = None
        self.districts = []

        self.province_btn.text = (
            item["name"]
        )

        if self.country and self.country.get("code") == "KKTC":
            self.district_btn.disabled = True
            self.district_btn.text = "KKTC"
            self.lat = item.get("lat")
            self.lon = item.get("lon")
            self.location_label.text = f"Kuzey Kıbrıs Türk Cumhuriyeti / {item['name']}"
            self.background.set_location(
                f"{item['name']}, Kuzey Kıbrıs Türk Cumhuriyeti",
                self.lat, self.lon
            )
            self.fetch_weather()
            return

        self.district_btn.disabled = False
        self.district_btn.text = self.d["loading"]

        threading.Thread(
            target=self.load_districts,
            args=(item["id"], generation),
            daemon=True
        ).start()

    # ========================================================
    # TÜRKİYE 973 İLÇE
    # ========================================================

    def load_districts(self, province_id, generation=None):
        """Load districts robustly with two documented TurkiyeAPI v2 routes.

        Some deployments/proxies can reject the nested collection query even
        though the API supports it. We therefore try the filtered collection
        endpoint first, then the province include endpoint.
        """
        districts = []
        errors = []
        pid = str(province_id).strip()

        urls = [
            (
                "https://api.turkiyeapi.dev/v2/districts",
                {"provinceId": pid, "fields": "id,name", "limit": 1000, "sort": "name"}
            ),
            (
                f"https://api.turkiyeapi.dev/v2/provinces/{int(province_id)}",
                {"include": "districts", "fields": "id,name"}
            ),
            (
                f"https://api.turkiyeapi.dev/v2/provinces/{int(province_id)}/districts",
                {"fields": "id,name", "limit": 1000, "sort": "name"}
            ),
        ]

        for url, params in urls:
            try:
                response = requests.get(url, params=params, timeout=10)
                response.raise_for_status()
                payload = response.json()
                rows = payload.get("data", []) if isinstance(payload, dict) else []

                # Province detail + include=districts returns a dict.
                if isinstance(rows, dict):
                    rows = rows.get("districts", [])
                if not isinstance(rows, list):
                    raise ValueError("İlçe API veri biçimi beklenmiyor")

                districts = sorted(
                    [
                        x for x in rows
                        if isinstance(x, dict) and x.get("id") is not None and x.get("name")
                    ],
                    key=lambda x: str(x["name"]).casefold()
                )
                if districts:
                    break
                raise ValueError("İlçe listesi boş")
            except Exception as error:
                errors.append(f"{url}: {error}")

        if not districts:
            print("İlçe API hataları:", " | ".join(errors))

        def apply(*_):
            if generation is not None and generation != self._location_generation:
                return
            if not self.country or self.country.get("code") != "TR":
                return
            self.districts = districts
            # İlçe butonu hiçbir zaman kalıcı olarak kilitlenmez.
            self.district_btn.disabled = False
            self.district_btn.text = self.d["select_district"] if districts else self.d["select_district"]
        Clock.schedule_once(apply, 0)

    def _reload_districts_if_needed(self, *_):
        """Retry district loading when the user taps the district button."""
        if self.country and self.country.get("code") == "TR" and self.province:
            generation = self._location_generation
            threading.Thread(
                target=self.load_districts,
                args=(self.province.get("id"), generation),
                daemon=True
            ).start()

    def select_district(self, *_):
        if self.country and self.country.get("code") == "TR":
            if self.districts:
                SelectorPopup(
                    self.d["district"],
                    self.districts,
                    self.district_chosen,
                    self.lang
                ).open()
            elif self.province:
                # API ilk denemede cevap vermediyse buton yine çalışır; tekrar yükler.
                self.district_btn.text = self.d["loading"]
                self._reload_districts_if_needed()
            return

        self.city_search_popup()

    def district_chosen(self, item):

        self._location_generation += 1
        generation = self._location_generation
        self.district = item["name"]

        self.district_btn.text = (
            self.district
        )

        self.location_label.text = (
            f"{self.country['name']} / "
            f"{self.province['name']} / "
            f"{self.district}"
        )
        self.lookup_weather(
            f"{self.district}, "
            f"{self.province['name']}, Turkey",
            "TR",
            generation
        )

    # ========================================================
    # DÜNYA ŞEHİR ARAMA
    # ========================================================

    def city_search_popup(self):
        """Premium, dark search popup. Results are never white and search is debounced."""
        content = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(10))
        search = TextInput(hint_text=self.d["search"], multiline=False, size_hint_y=None, height=dp(44),
                           background_color=get_color_from_hex("#121A28"), foreground_color=(.95,.98,1,1),
                           cursor_color=(1,.60,.05,1), font_name=FONT_NAME, font_size="14sp",
                           padding=(dp(12),dp(10)))
        content.add_widget(search)
        status=ModernLabel(text=self.d["search_min_chars"], font_size="10sp", color=(.58,.68,.8,1), size_hint_y=None, height=dp(22))
        content.add_widget(status)
        results_scroll=ScrollView(); results_box=BoxLayout(orientation="vertical",spacing=dp(5),size_hint_y=None)
        results_box.bind(minimum_height=results_box.setter("height")); results_scroll.add_widget(results_box); content.add_widget(results_scroll)
        close_btn=SelectorButton(text=self.d["close"],size_hint_y=None,height=dp(44),background_color=get_color_from_hex("#182235"),color=(.95,.97,1,1))
        content.add_widget(close_btn)
        popup=Popup(title=self.d["district"],content=content,size_hint=(.92,.82),separator_color=get_color_from_hex("#1FB6FF"),background_color=get_color_from_hex("#080D16"),auto_dismiss=True)
        timer={"event":None}
        def run_search(*_):
            if timer["event"]: timer["event"].cancel()
            timer["event"]=Clock.schedule_once(lambda *_: self._perform_city_search(search.text.strip(),results_box,status,popup),.42)
        search.bind(text=run_search)
        close_btn.bind(on_release=lambda *_: popup.dismiss())
        popup.open()

    def _perform_city_search(self,query,results_box,status,popup):
        if len(query)<2:
            status.text=self.d["search_min_chars"]; results_box.clear_widgets(); return
        status.text=self.d["loading"]; results_box.clear_widgets()
        threading.Thread(target=self.city_search_thread,args=(query,results_box,popup,status),daemon=True).start()

    def city_search_thread(self,query,results_box,popup,status):
        try:
            params={"name":query,"count":20,"language":"en","format":"json"}
            if self.country and self.country.get("code") and len(str(self.country.get("code")))==2: params["countryCode"]=self.country["code"]
            response=requests.get(OPEN_METEO_GEOCODING_URL,params=_open_meteo_params(params),timeout=12); response.raise_for_status()
            results=response.json().get("results",[])
            def show_results(*_):
                results_box.clear_widgets()
                if not results:
                    status.text=self.d["no_data"]; return
                status.text=self.d["results_count"].format(count=len(results))
                for result in results:
                    item={"name":result.get("name","") or "", "latitude":result.get("latitude"), "longitude":result.get("longitude"), "admin1":result.get("admin1","") or "", "country":result.get("country","") or ""}
                    text=f"{item['name']}  •  {item['admin1']}  •  {item['country']}"
                    button=SelectorButton(text=text,size_hint_y=None,height=dp(46),background_color=get_color_from_hex("#111B2B"),color=(.92,.96,1,1),font_size="12sp")
                    button.bind(on_release=lambda _,value=item:(popup.dismiss(),self.use_coords(value)))
                    results_box.add_widget(button)
            Clock.schedule_once(show_results,0)
        except Exception as error:
            print("Şehir arama hatası:",error)
            Clock.schedule_once(lambda *_: setattr(status,"text",self.d["no_internet"]),0)

    def use_coords(self,item):
        """Apply a city-search result without leaving Turkey selectors in a stale state."""
        self._location_generation += 1
        generation = self._location_generation
        self.district = item.get("name") or ""
        self.lat = item.get("latitude")
        self.lon = item.get("longitude")

        country_name = item.get("country") or (self.country or {}).get("name", "")
        is_turkey = (
            (self.country and self.country.get("code") == "TR")
            or str(country_name).casefold() in ("turkey", "türkiye")
        )

        if is_turkey:
            # City search can return Konya/Ankara/etc. without an explicit
            # province selection. Resolve the province locally so the selector
            # remains usable instead of looking disabled/stale.
            self.country = next(
                (x for x in self.country_items if x.get("code") == "TR"),
                {"name": "Türkiye", "code": "TR"}
            )
            self.provinces = self._builtin_turkish_provinces()
            city_name = str(item.get("name") or "").strip()
            admin1 = str(item.get("admin1") or "").strip()
            self.province = next(
                (x for x in self.provinces
                 if str(x.get("name", "")).casefold() in (city_name.casefold(), admin1.casefold())),
                None
            )
            self.province_btn.disabled = False
            if self.province:
                self.province_btn.text = self.province["name"]
                self.district_btn.disabled = False
                # Load the district list in the background if the selected city
                # belongs to a known Turkish province.
                self.districts = []
                threading.Thread(
                    target=self.load_districts,
                    args=(self.province["id"], generation),
                    daemon=True
                ).start()
            else:
                self.province_btn.text = self.d["select_province"]
                self.district_btn.disabled = False
            self.location_label.text = f"Türkiye / {self.district}"
            self.district_btn.text = self.district
            self.background.set_location(f"{self.district}, Türkiye", self.lat, self.lon)
        else:
            self.province = None
            self.province_btn.text = self.d["province"]
            self.province_btn.disabled = True
            self.district_btn.disabled = False
            self.district_btn.text = self.district
            self.location_label.text = f"{country_name} / {self.district}" if country_name else self.district
            self.background.set_location(
                f"{self.district}, {country_name}" if country_name else self.district,
                self.lat, self.lon
            )

        self.fetch_weather(generation)

    # ========================================================
    # GEOCODING
    # ========================================================

    def lookup_weather(
        self,
        query,
        country_code,
        generation=None
    ):

        threading.Thread(
            target=self.geocode_thread,
            args=(query, country_code, generation),
            daemon=True
        ).start()

    def geocode_thread(
        self,
        query,
        country_code,
        generation=None
    ):

        try:

            geo_params = {
                "name": query,
                "count": 10,
                "language": "en",
                "format": "json"
            }
            if country_code and len(str(country_code)) == 2:
                geo_params["countryCode"] = country_code

            response = requests.get(
                OPEN_METEO_GEOCODING_URL,
                params=_open_meteo_params(geo_params),
                timeout=12
            )

            response.raise_for_status()

            results = response.json().get(
                "results",
                []
            )

            if not results:
                raise ValueError(
                    "Konum bulunamadı"
                )

            result = results[0]

            def apply(*_):
                if generation is not None and generation != self._location_generation:
                    return
                self.lat = float(result["latitude"])
                self.lon = float(result["longitude"])
                self.background.set_location(query, self.lat, self.lon)
                self.fetch_weather(generation)
            Clock.schedule_once(apply, 0)

        except Exception as error:

            print(
                "Geocoding hatası:",
                error
            )

            Clock.schedule_once(
                lambda *_:
                self.show_error(),
                0
            )

    # ========================================================
    # HAVA DURUMU
    # ========================================================

    def fetch_weather(self, generation=None):
        if generation is None:
            generation = self._location_generation
        if self.lat is None or self.lon is None:
            return
        lat, lon = float(self.lat), float(self.lon)
        threading.Thread(
            target=self.weather_thread,
            args=(lat, lon, generation),
            daemon=True
        ).start()

    def weather_thread(self, lat, lon, generation):

        try:

            params = {

                "latitude": lat,
                "longitude": lon,

                "current": (
                    "temperature_2m,"
                    "relative_humidity_2m,"
                    "is_day,"
                    "precipitation,"
                    "weather_code,"
                    "surface_pressure,"
                    "wind_speed_10m,"
                    "visibility"
                ),

                # Operasyonel kısa/orta vade.
                # Open-Meteo genel forecast API'si
                # en fazla 16 gün sunuyor.
                "daily": (
                    "weather_code,"
                    "temperature_2m_max,"
                    "temperature_2m_min,"
                    "precipitation_probability_max"
                ),

                "forecast_days": 16,
                "timezone": "auto",
                "wind_speed_unit": "kmh",
                "temperature_unit": "celsius"
            }

            response = requests.get(
                OPEN_METEO_FORECAST_URL,
                params=_open_meteo_params(params),
                timeout=15
            )

            response.raise_for_status()

            data = response.json()

            Clock.schedule_once(
                lambda *_: self.apply_weather(data, generation),
                0
            )

            # 17-30. günler için uzun menzilli
            # ECMWF EC46 / SEAS5 eğilimi.
            try:

                seasonal_response = requests.get(
                    OPEN_METEO_SEASONAL_URL,
                    params=_open_meteo_params({
                        "latitude": lat,
                        "longitude": lon,
                        "daily": (
                            "temperature_2m_max,"
                            "temperature_2m_min,"
                            "precipitation_sum,"
                            "weather_code"
                        ),
                        "forecast_days": 30,
                        "timezone": "auto"
                    }),
                    timeout=20
                )

                if seasonal_response.ok:

                    seasonal_data = (
                        seasonal_response.json()
                    )

                    Clock.schedule_once(
                        lambda *_:
                        self.apply_seasonal(
                            data,
                            seasonal_data,
                            generation
                        ),
                        0
                    )

            except Exception as seasonal_error:

                print(
                    "Uzun vadeli tahmin hatası:",
                    seasonal_error
                )

        except Exception as error:

            print(
                "Weather API hatası:",
                error
            )

            Clock.schedule_once(
                lambda *_:
                self.show_error(),
                0
            )

    # ========================================================
    # ANLIK VERİLER
    # ========================================================

    def apply_weather(self, data, generation=None):

        if generation is not None and generation != self._location_generation:
            return
        self.offline_overlay.hide()
        current = data["current"]
        daily = data["daily"]
        self.last_daily = daily

        raw_code = current.get("weather_code", 3)
        try:
            self.current_code = int(raw_code) if raw_code is not None else 3
        except (TypeError, ValueError):
            self.current_code = 3

        self.current_day = bool(
            current.get(
                "is_day",
                1
            )
        )

        # Hareketli arka planı hava durumuna göre değiştir.
        self.background.set_weather(
            self.current_code,
            self.current_day
        )

        current_temp = current.get("temperature_2m", "--")
        self.hero_temp.text = f"{current_temp} C"
        self.hero_status.text = weather_text(self.current_code, self.lang)
        if self.district:
            hero_location = self.district
        elif isinstance(self.province, dict):
            hero_location = self.province.get("name", "")
        elif self.country:
            hero_location = self.country.get("name", "")
        else:
            hero_location = ""
        self.hero_feels.text = hero_location

        max_list = daily.get("temperature_2m_max") or []
        min_list = daily.get("temperature_2m_min") or []
        max_today = max_list[0] if max_list else None
        min_today = min_list[0] if min_list else None
        self.max_label.text = (
            f"{self.d['max']}: {max_today if max_today is not None else '--'} C"
        )
        self.min_label.text = (
            f"{self.d['min']}: {min_today if min_today is not None else '--'} C"
        )

        visibility = current.get(
            "visibility",
            0
        )

        try:
            visibility_km = round(
                float(visibility) / 1000,
                1
            )
        except Exception:
            visibility_km = 0

        pressure = current.get("surface_pressure")
        wind = current.get("wind_speed_10m")
        rain_list = daily.get("precipitation_probability_max") or [0]
        rain_probability = rain_list[0] if rain_list else 0

        values = [

            weather_text(
                self.current_code,
                self.lang
            ),

            f"{current.get('relative_humidity_2m', '--')}%",

            f"{round(float(pressure))} hPa" if pressure is not None else "-- hPa",

            f"{round(float(wind), 1)} km/h" if wind is not None else "-- km/h",

            f"{visibility_km} km",

            f"{round(float(rain_probability or 0))}%"
        ]

        self.card_values = values

        self.update_cards(values)

        self.build_forecast(
            daily,
            None
        )

    # ========================================================
    # 30 GÜNLÜK VERİ
    # ========================================================

    def apply_seasonal(
        self,
        short_data,
        seasonal_data,
        generation=None
    ):

        if generation is not None and generation != self._location_generation:
            return
        self.last_daily = short_data.get("daily")
        self.last_seasonal = seasonal_data
        self.build_forecast(
            short_data["daily"],
            seasonal_data
        )

    def build_forecast(
        self,
        daily,
        seasonal_data=None
    ):

        self.forecast_box.clear_widgets()

        # İlk 16 gün gerçek kısa/orta vadeli forecast.
        dates = daily.get(
            "time",
            []
        )

        max_values = daily.get(
            "temperature_2m_max",
            []
        )

        min_values = daily.get(
            "temperature_2m_min",
            []
        )

        codes = daily.get(
            "weather_code",
            []
        )

        rain_values = daily.get(
            "precipitation_probability_max",
            []
        )

        for index, date in enumerate(
            dates[:16]
        ):

            max_value = max_values[index] if index < len(max_values) else None
            min_value = min_values[index] if index < len(min_values) else None
            code_value = codes[index] if index < len(codes) else 3

            self.add_forecast_row(
                date,
                max_value,
                min_value,
                weather_text(
                    code_value if code_value is not None else 3,
                    self.lang
                ),
                rain_values[index]
                if index < len(rain_values)
                else 0,
                False,
                index
            )

        # 17-30 gün: uzun vadeli eğilim.
        if seasonal_data:

            seasonal = seasonal_data.get(
                "daily",
                {}
            )

            sdates = seasonal.get(
                "time",
                []
            )

            smax = seasonal.get(
                "temperature_2m_max",
                []
            )

            smin = seasonal.get(
                "temperature_2m_min",
                []
            )

            s_code = seasonal.get(
                "weather_code",
                []
            )

            s_precip = seasonal.get(
                "precipitation_sum",
                []
            )

            for index in range(
                16,
                min(30, len(sdates))
            ):

                max_value = (
                    smax[index]
                    if index < len(smax)
                    else None
                )

                min_value = (
                    smin[index]
                    if index < len(smin)
                    else None
                )

                code = (
                    s_code[index]
                    if index < len(s_code)
                    else 3
                )

                precip = (
                    s_precip[index]
                    if index < len(s_precip)
                    else 0
                )

                self.add_forecast_row(
                    sdates[index],
                    max_value,
                    min_value,
                    self.d["seasonal"],
                    precip,
                    True,
                    index
                )

    def add_forecast_row(
        self,
        date,
        max_temp,
        min_temp,
        status,
        rain,
        long_range,
        index
    ):

        row = Card(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(42),
            spacing=dp(3)
        )

        if index == 0:
            day = self.d["today"]
        else:
            day = date[5:].replace(
                "-",
                "."
            )

        row.add_widget(
            ModernLabel(
                text=str(day),
                size_hint_x=0.22,
                font_size="10sp",
                bold=True
            )
        )

        row.add_widget(
            ModernLabel(
                text=str(status),
                size_hint_x=0.38,
                font_size="10sp"
            )
        )

        row.add_widget(
            ModernLabel(
                text=(
                    f"{max_temp if max_temp is not None else '--'}"
                    f" / "
                    f"{min_temp if min_temp is not None else '--'} C"
                ),
                size_hint_x=0.25,
                font_size="10sp",
                bold=True
            )
        )

        row.add_widget(
            ModernLabel(
                text=f"{round(float(rain or 0))}%",
                size_hint_x=0.15,
                font_size="10sp"
            )
        )

        self.forecast_box.add_widget(
            row
        )

    # ========================================================
    # KARTLAR
    # ========================================================

    def update_cards(self, values):

        self.grid.clear_widgets()

        self.card_values = values

        labels = [
            self.d["status"],
            self.d["humidity"],
            self.d["pressure"],
            self.d["wind"],
            self.d["visibility"],
            self.d["rain"]
        ]

        colors = [
            "#FF9800",
            "#44D7B6",
            "#FFEB3B",
            "#2196F3",
            "#E91E63",
            "#9C27B0"
        ]

        for title, value, color in zip(
            labels,
            values,
            colors
        ):

            card = Card(
                orientation="vertical"
            )

            card.add_widget(
                ModernLabel(
                    text=str(title),
                    font_size="11sp",
                    bold=True,
                    color=get_color_from_hex(
                        "#8B98AC"
                    )
                )
            )

            card.add_widget(
                ModernLabel(
                    text=str(value),
                    font_size="13sp",
                    bold=True,
                    color=get_color_from_hex(
                        color
                    )
                )
            )

            self.grid.add_widget(
                card
            )

    # ========================================================
    # ALT MENÜ YARDIMCILARI
    # ========================================================

    def show_map_info(self, *_):
        """Open the map safely without allowing map errors to kill the app."""
        try:
            map_view = PremiumMapView(self)
            container = BoxLayout(orientation="vertical", spacing=dp(4), padding=dp(2))
            container.add_widget(map_view)
            close_btn = ModernButton(
                text=self.d["close"],
                size_hint_y=None,
                height=dp(38),
                background_color=get_color_from_hex("#111B2B"),
            )
            container.add_widget(close_btn)
            popup = Popup(
                title=map_view._t("title"), content=container,
                size_hint=(0.99, 0.96) if IS_MOBILE_RUNTIME else (0.985, 0.94),
                background_color=get_color_from_hex("#060B13"),
                separator_color=get_color_from_hex("#1FB6FF"),
                auto_dismiss=False,
            )
            close_btn.bind(on_release=lambda *_: popup.dismiss())
            map_view._owner_popup = popup
            self._map_popup = popup
            self._map_view = map_view
            def cleanup(*_):
                if getattr(self, "_map_popup", None) is popup:
                    self._map_popup = None
                    self._map_view = None
            popup.bind(on_dismiss=cleanup)
            popup.open()
            Clock.schedule_once(
                lambda *_: map_view.set_center(self.lat, self.lon)
                if getattr(map_view, "parent", None) is not None else None,
                0.12,
            )
        except Exception as error:
            print("Harita açma hatası:", repr(error))
            content = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(14))
            content.add_widget(ModernLabel(text=f"Harita açılamadı\n\n{error}", halign="center"))
            close = ModernButton(text=self.d["close"], size_hint_y=None, height=dp(42))
            content.add_widget(close)
            err_popup = Popup(title=self.d["title"], content=content, size_hint=(0.82, 0.38), auto_dismiss=True)
            close.bind(on_release=lambda *_: err_popup.dismiss())
            err_popup.open()

    def show_favorites(self):
        favorites=self.store.get("favorites").get("items",[]) if self.store.exists("favorites") else []
        content=BoxLayout(orientation="vertical",spacing=dp(7),padding=dp(10))
        listing=BoxLayout(orientation="vertical",spacing=dp(5),size_hint_y=1)
        if not favorites:
            listing.add_widget(ModernLabel(text=self.d["no_favorites"],font_size="13sp",halign="center"))
        for item in favorites:
            b=SelectorButton(text=f"{item.get('name','')}  •  {item.get('country','')}",size_hint_y=None,height=dp(44),background_color=get_color_from_hex("#111B2B"))
            b.bind(on_release=lambda _,v=item:self.use_favorite(v))
            listing.add_widget(b)
        content.add_widget(listing)
        buttons=BoxLayout(size_hint_y=None,height=dp(44),spacing=dp(6))
        add=SelectorButton(text=self.d["save_current"],background_color=get_color_from_hex("#182235"))
        close=SelectorButton(text=self.d["close"],background_color=get_color_from_hex("#182235"))
        buttons.add_widget(add); buttons.add_widget(close); content.add_widget(buttons)
        popup=Popup(title=self.d["favorites"],content=content,size_hint=(.88,.58),separator_color=get_color_from_hex("#1FB6FF"),background_color=get_color_from_hex("#080D16"))
        add.bind(on_release=lambda *_: (self.save_current_favorite(),popup.dismiss()))
        close.bind(on_release=lambda *_:popup.dismiss())
        popup.open()

    def save_current_favorite(self):
        name=self.district or (self.province.get("name") if isinstance(self.province,dict) else None) or (self.country.get("name") if self.country else None)
        if not name:return
        items=self.store.get("favorites").get("items",[]) if self.store.exists("favorites") else []
        item={"name":name,"country":(self.country or {}).get("name",""),"lat":self.lat,"lon":self.lon}
        if not any(x.get("name")==name and x.get("country")==item["country"] for x in items): items.append(item)
        self.store.put("favorites",items=items[-20:])

    def use_favorite(self,item):
        self._location_generation+=1
        self.district=item.get("name")
        self.lat=item.get("lat"); self.lon=item.get("lon")
        self.district_btn.text=self.district or self.d["select_district"]
        self.location_label.text=f"{item.get('country','')} / {self.district}"
        if self.lat is not None and self.lon is not None:self.fetch_weather(self._location_generation)

    # ========================================================
    # HATA
    # ========================================================

    def show_error(self):
        self.card_values = [
            self.d["no_data"], "--%", "-- hPa", "-- km/h", "-- km", "--%"
        ]
        self.update_cards(self.card_values)
        Clock.schedule_once(lambda *_: self.offline_overlay.show(), 0)


# ============================================================
# BAŞLAT
# ============================================================

if __name__ == "__main__":
    HavaDurumuApp().run()
