# Eco-Smart Balancer 🛞☀️

> **Equilibratrice ruote auto/SUV open-hardware ad alta precisione e basso consumo, alimentabile da pannello solare.**

**Progetto ideato e sviluppato da [Alessandro Pezzali](https://alessandropezzali.it) — [@pezzaliapp](https://github.com/pezzaliapp)**

[![License: CERN-OHL-S v2](https://img.shields.io/badge/license-CERN--OHL--S--v2-blue)](LICENSE)
[![Firmware MIT](https://img.shields.io/badge/firmware-MIT-green)]()
[![Status](https://img.shields.io/badge/status-draft%20v0.1-orange)]()
[![Author](https://img.shields.io/badge/author-pezzaliapp-orange)](https://github.com/pezzaliapp)

---

## 🎯 Il progetto in 30 secondi

Un'equilibratrice ruote auto/SUV pensata per superare le specifiche delle macchine professionali standard, con due differenze chiave:

- **±0,8 g** di precisione grazie a 2 accelerometri MEMS digitali ADXL355
- **3–5 Wh** di consumo per lancio (target di drastica riduzione rispetto alle macchine convenzionali)
- Alimentazione **solare 150 W + batteria LiFePO4 + rete come backup**, gestione automatica con priorità configurabile
- Frenatura **rigenerativa** che recupera ~6 Wh per ciclo
- Costo materiali contenuto, sotto fascia di mercato delle macchine professionali equivalenti
- **Open hardware** (CERN-OHL-S v2) — schemi, BOM, firmware tutti pubblici

> ⚠️ **Stato attuale: progetto concettuale (v0.1).** Non è ancora un prodotto. Non è ancora certificato CE. Vedi roadmap in `docs/`.

---

## 🏗️ Architettura

```
[Solare 150W] → MPPT → [Batteria 24V/50Ah LiFePO4] ← AC/DC ← [Rete 230V]
                              ↓
                       Bus DC 24V comune (gestito da ESP32)
                              ↓
       ┌──────────────┬──────────────┬──────────────┐
       ↓              ↓              ↓              ↓
  Motor BLDC     ESP32-S3      Display 7"    PCB sensori
  + ODrive       (FFT/DSP)      LVGL UI      2x ADXL355
  (regen ON)                                  + encoder 14-bit
       ↓
  Mandrino Ø40mm + flangia + ruota
```

Dettagli in [`docs/00-architecture.md`](docs/00-architecture.md).

---

## 📦 Cosa c'è in questo repo

| Cartella | Contenuto |
|---|---|
| `docs/` | Specifiche, architettura, calibrazione, sicurezza |
| `hardware/mechanical/` | CAD parametrici (CadQuery), STEP, tavole 2D |
| `hardware/electrical/` | Schemi KiCad, PCB, gerber, BOM |
| `hardware/enclosure/` | Parti stampate 3D (carter, cover sensori) |
| `firmware/` | PlatformIO ESP32-S3: FFT, motor, UI, safety |
| `simulation/python/` | Simulatore algoritmo per validazione pre-build |
| `companion-app/` | App mobile (opzionale, archivio cliente) |
| `assembly-guide/` | Guida montaggio passo-passo con foto |
| `tools/` | Script calibrazione, log analyzer, render Blender |

---

## 🚀 Quickstart

### Per chi vuole solo capire se l'algoritmo funziona

```bash
git clone https://github.com/pezzaliapp/eco-smart-balancer
cd eco-smart-balancer/simulation/python
pip install -r requirements.txt
python balance_sim.py --sweep
# apri reports/<timestamp>/index.html nel browser
```

### Per chi vuole flashare il firmware

```bash
cd firmware/
pio run -e esp32-s3-devkit -t upload
pio device monitor
```

### Per chi vuole costruirlo davvero

1. Leggi [`docs/01-mechanical-design.md`](docs/01-mechanical-design.md)
2. Apri [`hardware/mechanical/`](hardware/mechanical/) e rigenera CAD coi tuoi parametri
3. Manda gli STEP a fabbro/torneria con le tavole 2D in `drawings/`
4. Ordina la BOM elettrica da [`hardware/electrical/bom.csv`](hardware/electrical/bom.csv)
5. Segui [`assembly-guide/step-by-step.md`](assembly-guide/step-by-step.md)

⏱️ **Tempo stimato self-build:** 80–120 ore di officina + componenti elettronici e meccanici standard.

---

## 📊 Performance attese

| Metrica | Valore target |
|---|---|
| Precisione bilanciamento | ±0,8 g |
| Consumo per lancio | 3–5 Wh |
| Tempo lancio | 5–7 s |
| Compatibilità coni Ø40mm | ✅ |
| Funzionamento solare puro | ✅ |
| Recupero in frenata | ✅ |
| Open hardware | ✅ |

> Le specifiche sopra sono target di progetto basati sulla simulazione numerica (vedi cartella `simulation/python`). I valori reali andranno confermati sul prototipo fisico nelle fasi F1–F6.

---

## 🛣️ Roadmap

- [x] **F0** — Studio fattibilità + simulatore Python validato
- [ ] **F1** — Prototipo banco di prova (mandrino + sensori + ESP32)
- [ ] **F2** — Algoritmo calibrato e validato a banco
- [ ] **F3** — Telaio definitivo + carter sicurezza
- [ ] **F4** — Sistema energetico ibrido completo
- [ ] **F5** — UI touch e firmware completo
- [ ] **F6** — Test campo (100 ruote)
- [ ] **F7** — Certificazione CE (richiede Organismo Notificato)

Tempi indicativi: 5 mesi part-time per arrivare a F6.

---

## 🤝 Contribuire

Issue e PR benvenute! Per modifiche grandi, apri prima una issue per discutere.

Aree dove serve aiuto in priorità:

- 🔧 Validazione meccanica del telaio (analisi FEM)
- 📐 Tavole 2D in formato workshop-friendly
- 🧪 Test su ruote reali con risultati certificati
- 🌍 Traduzioni della UI (per ora solo IT/EN)
- 📚 Documentazione di calibrazione

---

## 👤 Autore

**Alessandro Pezzali**

- 🌐 Sito personale: [alessandropezzali.it](https://alessandropezzali.it)
- 💻 GitHub: [@pezzaliapp](https://github.com/pezzaliapp)
- 📧 Issue tracker del progetto: [GitHub Issues](https://github.com/pezzaliapp/eco-smart-balancer/issues)

Eco-Smart Balancer è un progetto personale di ricerca e sviluppo nel dominio dell'attrezzatura per officina. Concetto, architettura, simulazione, documentazione: tutto a cura dell'autore. Contributi esterni benvenuti tramite Pull Request.

---

## ⚖️ Licenza

- **Hardware** (CAD, schemi, PCB, BOM): [CERN Open Hardware Licence v2 — Strongly Reciprocal](https://cern-ohl.web.cern.ch/)
- **Firmware e software**: [MIT](LICENSE) — © 2026 Alessandro Pezzali
- **Documentazione**: [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) — © 2026 Alessandro Pezzali

L'autore mantiene la paternità intellettuale del progetto. La licenza permette riuso, modifica e ridistribuzione con attribuzione e mantenimento delle stesse condizioni.

---

## 🙋 FAQ veloci

**Posso venderlo?**
Sì, la licenza CERN-OHL-S lo permette, ma devi rilasciare le tue modifiche con la stessa licenza e marcare CE a tuo nome (con tutti gli oneri del caso). L'attribuzione all'autore originale ([Alessandro Pezzali](https://alessandropezzali.it)) deve essere mantenuta in modo chiaro nella documentazione.

**Funziona davvero solo a luce solare?**
In Italia centro-nord, in officina con tetto a 30° esposto a sud, un pannello da 150 W produce in media 0,5–0,7 kWh/giorno. Con 30–50 lanci/giorno (consumo 150–250 Wh) il bilancio è positivo. La batteria copre i picchi e le ore notturne. La rete elettrica entra solo come backup di emergenza.

**Perché albero orizzontale e non verticale?**
Analizzato e scartato per ruote auto: footprint troppo grande, carter complesso, sensori asimmetrici a basso RPM. Vedi [`docs/00-architecture.md`](docs/) per l'analisi completa di trade-off.

**Compatibilità con accessori standard?**
Sì, l'attacco mandrino Ø40 mm è compatibile con il parco accessori standard (coni, flange, pinze 4/5 fori) presente sul mercato europeo.

**E la sicurezza?**
Il progetto include carter dual-channel cat. 3 PLd EN ISO 13849-1, fungo emergenza cat. 4 PLe, watchdog hardware, abort su over-vibration. Ma la marcatura CE finale richiede sempre Organismo Notificato.

---

*Built with ☀️ in Italy by [Alessandro Pezzali](https://alessandropezzali.it) — © 2026*
