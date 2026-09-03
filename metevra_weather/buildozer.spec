[app]

title = Metevra Weather
package.name = weather
package.domain = com.metevra

source.dir = .
source.main = MetevraWeather.py

source.include_exts = py,png,jpg,jpeg,otf,ico,txt,webp
source.exclude_dirs = .venv,.git,dist,build,__pycache__,bin,.buildozer
source.exclude_patterns = *.pyc,*.pyo

version = 1.0.0

requirements = python3,kivy==2.3.1,requests,pillow

orientation = landscape
fullscreen = 0

icon.filename = assets/app_icon.png

presplash.filename = assets/splash.png
presplash.color = #07111F

android.api = 36
android.minapi = 23

android.ndk = 25b
android.archs = arm64-v8a,armeabi-v7a

android.allow_backup = True

android.debug_artifact = apk
android.release_artifact = aab

android.numeric_version = 10000

android.permissions = INTERNET,ACCESS_COARSE_LOCATION,ACCESS_FINE_LOCATION

android.no-byte-compile-python = False


# =========================================================
# PYTHON-FOR-ANDROID
# =========================================================

p4a.source_dir = /home/runner/work/MetevraWeather/MetevraWeather/python-for-android


[buildozer]

log_level = 2
warn_on_root = 1
