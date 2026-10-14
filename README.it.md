# ❄️ Template Climate UI

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)
[![License](https://img.shields.io/github/license/dvbit/ha-template-climate-ui?style=for-the-badge)](LICENSE)
[![Release](https://img.shields.io/github/v/release/dvbit/ha-template-climate-ui?style=for-the-badge)](https://github.com/dvbit/ha-template-climate-ui/releases)

<img src="icon.png" alt="icona" width="96" align="right">

Crea **entità clima da template e azioni, interamente da interfaccia**.
Fork di [jcwillox/hass-template-climate](https://github.com/jcwillox/hass-template-climate)
con config flow, options flow e anteprima live — niente YAML.

🇬🇧 [Read in English](README.md) · 📐 [Specifica](SPEC.md)

## Perché

- Unisce sensori, interruttori e script in un'unica card termostato.
- Comanda dispositivi "stupidi" (condizionatori IR, relè) mantenendo uno stato ottimistico.
- Home Assistant 2026.10 include nel core un clima template da UI, ma copre solo modalità HVAC,
  azione HVAC e temperatura. Questa integrazione copre anche **ventola, preset, swing, umidità e
  range caldo/freddo**, con le stesse opzioni dell'integrazione YAML originale.

## Installazione

1. HACS → ⋮ → *Repository personalizzati* → `https://github.com/dvbit/ha-template-climate-ui`,
   tipo **Integrazione**.
2. Installa **Template Climate UI** e riavvia Home Assistant.
3. *Impostazioni → Dispositivi e servizi → Aggiungi integrazione → Template Climate UI*.

Richiede Home Assistant **2026.9.0** o successivo. Può convivere con l'integrazione YAML
originale `climate_template`.

## Configurazione

Un solo form con quattro sezioni. L'anteprima in fondo mostra il clima risultante mentre scrivi.

| Sezione | Contenuto |
|---|---|
| *(in alto)* | Nome, dispositivo esistente (opzionale) a cui collegare l'entità |
| **Template di stato** | temperatura attuale/obiettivo, massima/minima, umidità (attuale, obiettivo, min, max), modalità HVAC, azione HVAC, ventola, preset, swing, temperatura min/max |
| **Azioni** | `set_temperature`, `set_hvac_mode`, `set_fan_mode`, `set_preset_mode`, `set_swing_mode`, `set_humidity` |
| **Modi e limiti** | modalità HVAC, liste ventola/preset/swing (valori personalizzati ammessi), temperatura min/max, passo, precisione |
| **Avanzate** | disponibilità, icona, immagine, attributi aggiuntivi, variabili |

Regole (identiche all'integrazione originale):

- Ciò che resta vuoto funziona in **modalità ottimistica**: l'entità ricorda ciò che imposti.
- Una funzione (ventola, preset, swing, umidità obiettivo, temperatura obiettivo) compare solo
  se è impostato **il suo template o la sua azione**.
- I risultati `unknown`/`unavailable` vengono ignorati; i valori non validi sono scartati e
  registrati nel log.
- In `heat_cool` la card mostra un intervallo minimo/massimo invece di una singola temperatura.

Variabili disponibili nelle azioni:

| Azione | Variabili |
|---|---|
| `set_temperature` | `temperature`, `target_temp_high`, `target_temp_low`, `hvac_mode` |
| `set_hvac_mode` | `hvac_mode` |
| `set_fan_mode` | `fan_mode` |
| `set_preset_mode` | `preset_mode` |
| `set_swing_mode` | `swing_mode` |
| `set_humidity` | `humidity` |

`this` (stato dell'entità) e **Avanzate → Variabili** sono disponibili in ogni template e azione.

Tutto è modificabile in seguito da **Configura** sulla voce dell'integrazione; l'entità si ricarica.

## Esempi

### 1. Condizionatore IR (Broadlink) con sensore di stanza

**Template di stato**

| Campo | Valore |
|---|---|
| Temperatura attuale | `{{ states('sensor.bedroom_temperature') }}` |
| Umidità attuale | `{{ states('sensor.bedroom_humidity') }}` |

Lascia vuoti modalità HVAC, ventola e temperatura obiettivo: restano ottimistici.

**Azioni → Imposta modalità HVAC** (modalità YAML dell'editor azioni):

```yaml
- action: remote.send_command
  target:
    entity_id: remote.bedroom_broadlink
  data:
    device: aircon
    command: "{{ hvac_mode }}"
```

**Azioni → Imposta temperatura**:

```yaml
- action: remote.send_command
  target:
    entity_id: remote.bedroom_broadlink
  data:
    device: aircon
    command: "{{ 'temp_' ~ (temperature | int) }}"
```

**Modi e limiti**: modalità HVAC `off, cool, heat, dry, fan_only`, min 16, max 30, passo 1.

### 2. Unire un termostato esistente con un sensore esterno

| Campo | Valore |
|---|---|
| Temperatura attuale | `{{ states('sensor.living_room_accurate_temp') }}` |
| Modalità HVAC | `{{ states('climate.living_trv') }}` |
| Temperatura obiettivo | `{{ state_attr('climate.living_trv', 'temperature') }}` |
| Azione HVAC | `{{ state_attr('climate.living_trv', 'hvac_action') }}` |

**Imposta modalità HVAC**:

```yaml
- action: climate.set_hvac_mode
  target:
    entity_id: climate.living_trv
  data:
    hvac_mode: "{{ hvac_mode }}"
```

**Imposta temperatura**:

```yaml
- action: climate.set_temperature
  target:
    entity_id: climate.living_trv
  data:
    temperature: "{{ temperature }}"
```

### 3. Nodo ESPHome con disponibilità e interruttore di sicurezza

**Avanzate → Disponibilità**: `{{ is_state('binary_sensor.bedroom_node_status', 'on') }}`

**Avanzate → Variabili** (YAML):

```yaml
node: bedroom_node
```

**Imposta modalità HVAC**:

```yaml
- condition: state
  entity_id: input_boolean.enable_aircon_controller
  state: "on"
- action: "esphome.{{ node }}_aircon_state"
  data:
    operation_mode: "{{ hvac_mode }}"
    temperature: "{{ state_attr(this.entity_id, 'temperature') | int(0) }}"
    fan_mode: "{{ state_attr(this.entity_id, 'fan_mode') }}"
```

### 4. Uso dell'entità in un'automazione

```yaml
automation:
  - alias: "Camera: raffresca la notte"
    triggers:
      - trigger: time
        at: "22:30:00"
    actions:
      - action: climate.set_temperature
        target:
          entity_id: climate.bedroom_aircon
        data:
          hvac_mode: cool
          temperature: 24
```

## Migrazione dall'integrazione YAML

I nomi delle opzioni sono invariati. Copia ogni `*_template` nel campo corrispondente di
**Template di stato**, ogni `set_*` in **Azioni**, `modes`/`fan_modes`/`preset_modes`/`swing_modes`,
`min_temp`, `max_temp`, `temp_step`, `precision` in **Modi e limiti**, e
`availability_template`/`icon_template`/`entity_picture_template`/`attributes`/`variables` in
**Avanzate**. Poi rimuovi la voce YAML e riavvia.

## Log

```yaml
logger:
  logs:
    custom_components.climate_template_ui: debug
```

- **DEBUG**: ogni risultato di template, restore, avvio anteprima.
- **INFO**: entità pronta, azione eseguita, voce creata/aggiornata.
- **WARNING**: template fallito, valore rifiutato, errori di validazione del form.
- **ERROR**: configurazione salvata non più valida, azione fallita.

## Crediti

Lavoro originale di [Joshua Cowie-Willox](https://github.com/jcwillox) — licenza MIT.
Fork con configurazione da UI di [@dvbit](https://github.com/dvbit).
