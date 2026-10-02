# Alter Laptop als Server: Einrichtung von Grund auf

Dauer: etwa 2 bis 3 Stunden, davon viel Wartezeit. Am Ende läuft der Bot rund um die Uhr, du bedienst ihn vom Handy.

**Vorweg prüfen:** 64-Bit-Prozessor, mindestens 4 GB Arbeitsspeicher (besser 8), mindestens 30 GB freie Festplatte, LAN-Kabel oder WLAN, ein funktionierender Akku ist von Vorteil (er wirkt wie eine Notstromversorgung). **Die Festplatte wird komplett gelöscht:** Sichere vorher alles, was du behalten willst.

## Variante: Windows 10 oder 11 behalten (Docker Desktop)
Wenn du einen Windows-10- oder -11-PC hast, brauchst du kein Ubuntu. Er muss dann aber **immer laufen**, wenn der Bot handeln soll (Zeitplan im Dashboard, Standard mehrmals am Börsentag).
Hinweis: Für Windows 10 gibt es seit dem 14. Oktober 2025 keine kostenlosen Sicherheitsupdates mehr (außer mit dem kostenpflichtigen Zusatzprogramm). Auf einem Rechner mit deinen Zugangsdaten ist Windows 11 oder Linux besser.
1. **Version prüfen:** Win + R, `winver`. Windows 10 braucht Version **22H2**, sonst erst aktualisieren.
2. **Virtualisierung im BIOS einschalten** (Intel „VT-x“, AMD „SVM/AMD-V“). Ob sie an ist, zeigt der Task-Manager, Reiter Leistung, „Virtualisierung: Aktiviert“.
3. **WSL 2 installieren:** PowerShell **als Administrator** öffnen, `wsl --install` eingeben, neu starten.
4. **Docker Desktop** von docker.com installieren, starten, in den Einstellungen „Start Docker Desktop when you sign in“ anlassen.
5. **Git** von git-scm.com installieren. Dann in PowerShell:
```
git clone https://github.com/cooljiscool/plasnspielboerse.git
cd plasnspielboerse
powershell -ExecutionPolicy Bypass -File start.ps1
```
Das Skript legt `.env` mit einem zufälligen Dashboard-Passwort an (es steht am Ende auf dem Bildschirm, notiere es), baut den Container (10 bis 20 Minuten) und startet ihn. Dashboard: `http://localhost:8080`. (Das Skript ist von mir nicht unter Windows ausprobiert: Meldet es einen Fehler, schick mir den Wortlaut. Alternativ `copy .env.example .env`, in `notepad .env` hinter `DASHBOARD_PASSWORD=` ein langes Passwort setzen und `docker compose up -d --build`.)
6. **Damit er durchläuft:** Energieoptionen auf „Energie sparen: nie“ und bei einem Laptop „Beim Zuklappen: nichts unternehmen“; Windows-Update-„Nutzungszeit“ auf deine Handelszeiten legen (sonst startet er mitten am Tag neu); unter `netplwiz` „Automatisch anmelden“ einrichten, damit Docker Desktop nach einem Neustart von selbst startet.
7. **Handy:** Tailscale für Windows (tailscale.com) installieren, anmelden, App auf dem Handy, dann `http://<Computername>:8080`. Keinen Port im Router freigeben.
8. Weiter wie ab Abschnitt 9 („Im Dashboard einrichten“). Aktualisieren: `git pull`, dann `docker compose up -d --build`.

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

## 2b. Nur WLAN, kein LAN-Kabel
Es geht, ist aber die störanfälligere Variante, weil viele alte Laptops WLAN-Chips haben, für die Linux beim Installieren keinen Treiber mitbringt (vor allem **Broadcom**).
**Vorher prüfen (solange noch Windows läuft):** Geräte-Manager, Netzwerkadapter, Name des WLAN-Adapters ansehen. **Intel, Atheros, Realtek, Ralink/MediaTek** laufen fast immer. Bei **Broadcom** brauchst du für die Einrichtung vorübergehend eine andere Verbindung.
1. **Im Installer:** Auf der Seite „Network connections“ den WLAN-Adapter wählen, „Connect to a Wi-Fi network“, Namen und Passwort deines WLANs eingeben. Erscheint dort kein WLAN-Adapter, fehlt der Treiber: Dann für die Installation ein LAN-Kabel, einen **USB-LAN-Adapter** (ca. 10 €) oder **USB-Tethering vom Handy** (Handy per Kabel anstecken, „USB-Tethering“ einschalten) benutzen.
2. **Nach der Installation, WLAN fest einrichten** (am Laptop direkt, mit Tastatur):
```
ip a
sudo nano /etc/netplan/60-wifi.yaml
```
`ip a` zeigt den Namen des WLAN-Adapters (beginnt meist mit `wl`, z. B. `wlp2s0`). In die Datei (Einrückung mit Leerzeichen, nicht Tab):
```
network:
  version: 2
  wifis:
    wlp2s0:
      dhcp4: true
      access-points:
        "NameDeinesWLAN":
          password: "DeinWLANPasswort"
```
Speichern (Strg + O, Enter, Strg + X), dann:
```
sudo chmod 600 /etc/netplan/60-wifi.yaml
echo "network: {config: disabled}" | sudo tee /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg
sudo netplan apply
ip -4 addr show wlp2s0
```
Es muss eine Adresse wie `192.168.178.42` erscheinen. Fehlt `wpasupplicant` (Meldung), einmal mit Kabel oder Tethering `sudo apt install -y wpasupplicant`.
3. **Broadcom-Chip:** Mit Kabel oder Tethering `sudo apt install -y bcmwl-kernel-source` (oder, wenn das nicht geht, `sudo ubuntu-drivers install`), neu starten, dann Schritt 2. Klappt auch das nicht, ist ein USB-WLAN-Stick (ca. 10 €, mit Linux-Hinweis auf der Packung) die einfachste Lösung.
4. **Feste Adresse:** Im Router die Adresse für das Gerät mit dem WLAN-Adapter reservieren (die Kennung steht im Routermenü unter den verbundenen Geräten).
Im Betrieb reicht WLAN für den Bot völlig, das Datenvolumen ist klein. Stelle den Laptop dorthin, wo das Signal gut ist.

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
5. **Selektoren** (`selectors.json`): Die Datei liegt fertig im Repo (`data/selectors.json`), du musst nichts aufzeichnen (siehe `ANLEITUNG.md`, Schritt 10). Der Browser (Firefox) steckt im Docker-Image.
6. Tab Steuerung: **Selbsttest**, danach **Test-Order** (kauft und verkauft 1 Stück im Trainings-Depot). Alles muss `[ OK ]` zeigen.
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

## Automatisches Update (optional)
Statt jedes Mal `git pull` und `sh start.sh` von Hand einzugeben, kann der Server das selbst erledigen. Das Skript `scripts/auto_update.sh` prüft per Cron regelmäßig, ob es auf dem Branch neue Änderungen gibt, holt sie und baut den Container neu. Den Container tauscht es **nur aus, wenn gerade kein Lauf des Bots arbeitet**, damit nie ein Handelslauf abgebrochen wird.

**Einrichten (einmal, per SSH im Ordner `plasnspielboerse`):**
```
crontab -e
```
Beim ersten Mal fragt Ubuntu nach einem Editor: `1` (nano) wählen. Ans Ende der Datei diese Zeile schreiben (alles in einer Zeile):
```
*/10 * * * * cd /home/jakob/plasnspielboerse && sh scripts/auto_update.sh >> /home/jakob/auto_update.log 2>&1
```
Speichern mit Strg+O, Enter, beenden mit Strg+X. Der Benutzer (hier `jakob`) muss in der Gruppe `docker` sein, das ist nach der Installation nach Anleitung der Fall.

**Prüfen:** `tail -20 ~/auto_update.log` zeigt, was passiert ist (neuer Stand, Build, Austausch oder Fehler).

**Ausschalten:** `crontab -e` und die Zeile löschen oder mit `#` davor auskommentieren.

**Gut zu wissen:**
- Das Skript folgt dem Branch, der gerade ausgecheckt ist (`git branch` zeigt ihn). Wechselst du den Branch, folgt es dem neuen.
- Änderungen von Hand am Server (zum Beispiel im Dashboard bearbeitete `selectors.json` oder eine neu geladene `universe.json`), die auch im Repo geändert wurden, verhindern das automatische Zusammenführen. Dann steht im Log „lokale Änderungen im Weg“, und der Server bleibt auf dem alten Stand, bis du es von Hand löst.
- Jede neue Version geht damit **sofort live**, auch im Wettbewerbsdepot. Solange noch viel gebaut und getestet wird, ist das bequem. Läuft alles stabil, ist es sicherer, das Auto-Update auszuschalten und nur bewusst von Hand zu aktualisieren.
