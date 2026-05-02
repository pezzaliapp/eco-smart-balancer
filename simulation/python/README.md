# Simulatore Eco-Smart Balancer

Simulatore numerico per validare l'algoritmo di equilibratura **prima**
di costruire l'hardware. Genera segnali sintetici a partire da un modello
fisico realistico (sensori ADXL355, telaio 80 kg, motore 240 rpm) e
verifica che l'algoritmo ricostruisca i pesi di sbilanciamento entro
±0,8 g e ±3°.

## Setup

```bash
cd simulation/python
python -m venv .venv
source .venv/bin/activate            # Linux/Mac
# .\.venv\Scripts\activate           # Windows
pip install -r requirements.txt
```

## Uso

### Lancio singolo (per debug)

```bash
python balance_sim.py --weight-a 20,45 --weight-b 10,200
```

Output:

```
🎯 Imbalance set:
   Plane A (inner):  20.00 g @   45.0°
   Plane B (outer):  10.00 g @  200.0°

📐 Measured by simulator:
   Plane A:          20.09 g @   45.6°
   Plane B:          10.13 g @  200.1°

❗ Errors:
   Plane A: +0.09 g · +0.6°
   Plane B: +0.13 g · +0.1°

✅ PASS — within target ±0.8g · ±3.0°
```

### Sweep completo (1000 test, ~1-2 min)

```bash
python balance_sim.py --sweep --report
```

Genera un report HTML in `reports/<timestamp>/index.html` con grafici,
heatmap, distribuzioni di errore.

### Con rumore "realistico"

Aggiunge picchi a 25 Hz (compressore d'officina) e drift termico:

```bash
python balance_sim.py --sweep --report --realistic-noise
```

### Test unitari

```bash
pytest test/ -v
```

Devono passare tutti (29 test).

## Cosa simula

1. **Sensori MEMS ADXL355** con noise floor 25 µg/√Hz e bandwidth
   limitata a 50 Hz (filtro IIR built-in).
2. **Modello meccanico** del telaio dell'equilibratrice: matrice di
   trasferimento 2×2 complessa con guadagni 0,06 m/s² per N e
   crosstalk 32 % tra i piani.
3. **Pipeline DSP completa**: bandpass IIR 4° ordine, DFT puntuale
   sincrona alla frequenza di rotazione (Goertzel-style — niente
   spectral leakage).
4. **Calibrazione 3-lanci** alla MEC: zero, 50 g sul piano A,
   50 g sul piano B → matrice di influenza identificata.
5. **Solving** invertendo la matrice K, conversione fasori →
   (peso, angolo).

## Risultati attesi

Con configurazione default e noise nominale:

| Metrica | Valore atteso |
|---|---|
| Pass rate (target ±0,8 g) | 88–92% |
| Errore medio peso | 0,3–0,4 g |
| Errore P95 peso | 0,9–1,1 g |
| Errore P95 angolo | <0,5° |

Con `--realistic-noise` il pass rate scende a circa 82-87% — è la
ragione per cui in officina vera serve un filtro 25 Hz (compressore)
robusto e silent-block ben dimensionati.

## Cosa NON simula

- Vibrazioni meccaniche di altre macchine in officina (oltre il
  picco a 25 Hz)
- Scivolamento del cono o gioco mandrino
- Effetti termici sui sensori (drift solo in `--realistic-noise`)
- Asimmetrie geometriche del telaio (oltre la matrice K)
- Quantizzazione ADC (ma a 20-bit ADXL355 è trascurabile)

## Struttura file

```
simulation/python/
├── balance_core.py      # algoritmi DSP + modello fisico
├── balance_sim.py       # CLI driver + sweep + report HTML
├── requirements.txt
├── test/
│   └── test_balance.py  # 29 test pytest
├── reports/             # output dei sweep (.html .csv .json)
└── README.md            # questo file
```

## Dal simulatore al firmware

Lo stesso algoritmo (`balance_core.py`) è la specifica eseguibile
del firmware ESP32. La traduzione segue queste corrispondenze:

| Python | Firmware C++ |
|---|---|
| `extract_first_harmonic` (DFT puntuale) | Goertzel filter |
| `bandpass_filter` (scipy filtfilt) | IIR cascaded biquads (esp-dsp) |
| `identify_K` (np.linalg) | Manual 2x2 complex matrix |
| `solve_imbalance` (np.linalg.solve) | Cramer's rule on 2x2 system |
| `numpy.complex128` | `std::complex<float>` |

I numeri devono corrispondere entro 1e-3. Quando il firmware sarà
pronto, aggiungeremo un test di regressione che genera dati col
simulatore Python e li verifica col binario firmware in modalità
"replay".

## Quando eseguire questo simulatore

- **Prima di acquistare componenti**: verifica che lo schema raggiunga
  il target di precisione.
- **Quando cambi sensore**: passa da ADXL355 a un sensore diverso —
  modifica `SensorConfig` e ri-esegui il sweep.
- **Quando cambi RPM di lancio**: vuoi testare 180 vs 240 vs 300?
  Modifica `--rpm` e confronta i pass rate.
- **Quando cambi geometria meccanica**: nuovo telaio più rigido?
  Modifica `g_aa, g_bb, crosstalk_ratio` in `transfer_K_default`.

## Debugging

Se l'algoritmo non raggiunge il target:

1. **Stampa K_est e confronta con K_true** — se sono diversi,
   è un problema di calibrazione (rumore troppo alto, durata
   acquisizione troppo breve).
2. **Riduci `--noise-floor`** a 0.1 e verifica che con poco rumore
   tutto vada — se anche così fallisce è un bug del solver.
3. **Aumenta `--duration`** a 10s — più sample, meno rumore.
4. **Aumenta `--rpm`** a 300 — la forza scala con omega², SNR migliora.

## Licenza

MIT, vedi `../../LICENSE`.
