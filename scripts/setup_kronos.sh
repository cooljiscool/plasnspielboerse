#!/bin/sh
# Richtet Kronos (Basismodell für Kerzendaten) ein: PyTorch (nur CPU), Abhängigkeiten und den Kronos-Code (MIT-Lizenz).
# Danach im Dashboard "Kronos-Prognose" einschalten oder BOT_KRONOS=1 setzen. Die Modellgewichte lädt der Bot beim ersten Lauf
# von Hugging Face (Kronos-small ca. 100 MB).
set -e
cd "$(dirname "$0")/.."
pip install -r requirements-kronos.txt
if [ ! -d vendor/Kronos ]; then
  git clone --depth 1 https://github.com/shiyu-coder/Kronos vendor/Kronos
fi
python3 -c "import torch; print('PyTorch', torch.__version__, 'bereit')"
