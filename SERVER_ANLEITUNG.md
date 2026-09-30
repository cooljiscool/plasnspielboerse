# Alter Laptop als Server: Einrichtung von Grund auf

Dauer: etwa 2 bis 3 Stunden, davon viel Wartezeit. Am Ende läuft der Bot rund um die Uhr, du bedienst ihn vom Handy.

**Vorweg prüfen:** 64-Bit-Prozessor, mindestens 4 GB Arbeitsspeicher (besser 8), mindestens 30 GB freie Festplatte, LAN-Kabel oder WLAN, ein funktionierender Akku ist von Vorteil (er wirkt wie eine Notstromversorgung). **Die Festplatte wird komplett gelöscht:** Sichere vorher alles, was du behalten willst.

## 1. Installationsstick erstellen (am normalen PC)
1. Lade **Ubuntu Server 24.04 LTS** herunter (ubuntu.com/download/server).
2. Stecke einen USB-Stick (mindestens 8 GB, wird gelöscht) an, lade **balenaEtcher** (etcher.balena.io), wähle die ISO-Datei und den Stick, klicke auf Flash.

## 2. Installieren (am Laptop)
1. Laptop an den Strom, LAN-Kabel anstecken (WLAN geht, LAN ist zuverlässiger), Stick einstecken, Laptop starten und sofort die Boot-Menü-Taste drücken (meist F12, F2, Esc oder Entf, je nach Hersteller). Den Stick wählen.
2. Im Installer: Sprache **English** (macht später Fehlermeldungen leichter googlebar), Tastaturlayout **German**.
3. Installationsart **Ubuntu Server** (nicht „minimized“). Netzwerk: die Standardvorgabe übernehmen (DHCP).
4. Proxy und Spiegelserver: Standard lassen. Speicher: **Use an entire disk** (Standardvorschlag übernehmen, ohne LVM-Verschlüsselung).
5. Profil: Name, Servername (z. B. `boersenbot`), Benutzername (z. B. `bot`) und ein **langes Passwort** (du brauchst es für den Zugriff).
6. **„Install OpenSSH server“ ankreuzen.** Keine zusätzlichen Pakete (Snaps) auswählen.
7. Installation abwarten, dann „Reboot Now“ und den Stick ziehen, wenn die Meldung kommt.

## 3. Erster Start und Updates
1. Melde dich am Laptop mit Benutzername und Passwort an.
2. Zeitzone und Updates:
```
sudo timedatectl set-timezone Europe/Berlin
sudo apt update && sudo apt full-upgrade -y
```
(Das Passwort wird beim Tippen nicht angezeigt. Das ist normal.)
3. Notiere die Adresse des Laptops im Heimnetz: `ip -4 addr show | grep inet`. Gesucht ist eine Adresse wie `192.168.178.42` (nicht `127.0.0.1`).
4. **Feste Adresse:** Reserviere diese Adresse im Router für den Laptop (Menü „Heimnetz“, „Netzwerk“, Gerät auswählen, „immer dieselbe IPv4-Adresse“), damit sie sich nicht ändert.

## 4. Den Laptop serverfest machen
Der Laptop soll weiterlaufen, wenn der Deckel zu ist, und nie einschlafen.
```
sudo sed -i 's/^#\?HandleLidSwitch=.*/HandleLidSwitch=ignore/; s/^#\?HandleLidSwitchExternalPower=.*/HandleLidSwitchExternalPower=ignore/; s/^#\?HandleLidSwitchDocked=.*/HandleLidSwitchDocked=ignore/' /etc/systemd/logind.conf
sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
sudo reboot
```
Tipps: Im BIOS/UEFI (beim Start F2 oder Entf) die Option „AC Power Recovery“ oder „Restore on AC Power Loss“ auf **On** stellen, falls vorhanden: Dann startet der Laptop nach einem Stromausfall selbst. Stelle den Laptop aufgeklappt oder mit Abstand hin, damit er Luft bekommt. Ist der Akku aufgebläht, nimm ihn heraus und betreibe den Laptop nur am Netzteil.

## 5. Von deinem PC aus steuern (SSH)
Ab jetzt brauchst du am Laptop weder Tastatur noch Bildschirm.
1. Auf Windows: PowerShell öffnen (Startmenü). Auf Mac/Linux: Terminal.
2. `ssh bot@192.168.178.42` (Benutzername und Adresse ersetzen). Beim ersten Mal mit `yes` bestätigen, dann das Passwort eingeben.

Alle folgenden Befehle tippst du in dieser Verbindung.

## 6. Docker und Git installieren
```
sudo apt install -y git curl
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
exit
```
Verbinde dich danach erneut per SSH (Schritt 5) und prüfe: `docker run --rm hello-world` muss „Hello from Docker!“ zeigen. Docker startet künftig bei jedem Hochfahren von selbst.

## 7. Den Bot holen und starten
```
git clone https://github.com/cooljiscool/plasnspielboerse.git
cd plasnspielboerse
sh start.sh
```
Das Bauen dauert auf einem alten Laptop 10 bis 20 Minuten. Am Ende steht **das Dashboard-Passwort** auf dem Bildschirm (auch in der Datei `.env`). Notiere es. Test im Browser deines PCs: `http://192.168.178.42:8080`.

## 8. Vom Handy erreichen (auch unterwegs)
**Nicht** im Router den Port 8080 freigeben. Benutze Tailscale (kostenlos):
```
curl -fsSL https://tailscale.com/install.sh | sudo sh
sudo tailscale up
```
Der Befehl zeigt einen Link: Im Browser öffnen und mit einem Konto anmelden (Google, Microsoft oder Apple). Installiere dann die App **Tailscale** auf dem Handy und melde dich mit demselben Konto an. Im Handy-Browser öffnest du `http://boersenbot:8080` (der Servername aus Schritt 2) oder die Tailscale-Adresse des Laptops aus der App. Über „Zum Startbildschirm hinzufügen“ wird daraus eine App.

## 9. Im Dashboard einrichten
Melde dich mit dem Dashboard-Passwort an.
1. **Claude-Token:** `claude setup-token` ausführen, am einfachsten am normalen PC (Claude Code muss dort installiert sein: `curl -fsSL https://claude.ai/install.sh | bash`). Im Browser freigeben, das Token (beginnt mit `sk-ant-oat01-`) kopieren und im Dashboard unter **Einstellungen, Claude-Abo-Token** einfügen. Das Token ist wie ein Passwort.
2. **Planspiel-Login** (Benutzername/E-Mail und Passwort) im Tab Einstellungen eintragen. Optional Name und E-Mail für die SEC-Insiderdaten.
3. **Strategie** im Tab Einstellungen wählen (Empfehlung: `breit` oder `sicher`).
4. Tab Steuerung: **Wertpapierliste des Planspiels laden** (1 bis 2 Minuten).
5. **Selektoren** (`selectors.json`): Das Aufzeichnen mit `playwright codegen` braucht einen Bildschirm und geschieht deshalb am normalen PC (siehe `ANLEITUNG.md`, Schritt 10). Die fertige Datei fügst du im Dashboard im Tab Einstellungen bei `selectors.json` ein.
6. Tab Steuerung: **Selbsttest**. Alles muss `[ OK ]` zeigen.
7. **Start** drücken (Trockenlauf). Live schaltest du erst nach einigen Tagen um, zuerst im Test-Depot (siehe `ANLEITUNG.md`, Schritt 13).

## 10. Neustart-Test
```
sudo reboot
```
Nach zwei Minuten muss das Dashboard wieder erreichbar sein. Das Hochfahren startet den Container selbst (`restart: unless-stopped`), der Zeitplan läuft weiter, sobald Start gedrückt ist.

## 11. Sicherheit
- Keine Portweiterleitung im Router. Das Dashboard ist nur im Heimnetz und über Tailscale erreichbar.
- Ein langes Dashboard-Passwort (steht in `.env`).
- Ubuntu installiert Sicherheitsupdates automatisch. Zusätzlich etwa einmal im Monat: `sudo apt update && sudo apt upgrade -y`, danach `sudo reboot`.
- Hinweis: Die Firewall `ufw` schützt Docker-Ports nicht zuverlässig, deshalb zählt vor allem, dass der Port nicht ins Internet freigegeben ist.

## 12. Laufender Betrieb
- **Bot aktualisieren:** `cd ~/plasnspielboerse && git pull && docker compose up -d --build`
- **Logs ansehen:** `docker compose logs --tail 100 dashboard` im Ordner `plasnspielboerse`.
- **Status:** `docker compose ps`. **Neu starten:** `docker compose restart`.
- **Platz prüfen:** `df -h /` (wird es voll: `docker system prune -f`).
- **Sicherung** (etwa wöchentlich) vom normalen PC aus: `scp -r bot@192.168.178.42:plasnspielboerse/state bot@192.168.178.42:plasnspielboerse/data bot@192.168.178.42:plasnspielboerse/logs .` Im Ordner `state` liegen deine Zugangsdaten, bewahre die Kopie sicher auf.

## 13. Wenn etwas nicht klappt
- **Laptop startet nicht vom Stick:** Im BIOS Secure Boot testweise ausschalten, Bootreihenfolge prüfen.
- **Kein Netz nach der Installation:** LAN-Kabel prüfen, `ip a` zeigt, ob eine Adresse da ist. Bei WLAN: `sudo nano /etc/netplan/*.yaml` und die WLAN-Daten eintragen, dann `sudo netplan apply` (oder besser LAN nutzen).
- **`permission denied` bei docker:** Abmelden und neu anmelden (Schritt 6).
- **Dashboard nicht erreichbar:** `docker compose ps` im Ordner `plasnspielboerse`, `docker compose logs dashboard`.
- **Baut sehr langsam oder bricht ab:** Weniger als 4 GB Arbeitsspeicher. `free -h` prüfen, ggf. eine Auslagerungsdatei anlegen: `sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile`.
- **Laptop wird heiß oder laut:** Luftzufuhr prüfen, Staub entfernen, Standfläche nicht weich.
