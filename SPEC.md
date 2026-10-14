# Template Climate UI — specifica consolidata v2.0.0

Fork di [jcwillox/hass-template-climate](https://github.com/jcwillox/hass-template-climate)
(MIT) reso configurabile interamente da interfaccia tramite config flow.

Repository: https://github.com/dvbit/ha-template-climate-ui
Istanza di collaudo: generico (nessuna istanza dedicata).

## 1. Contesto

- 1.1 Dominio `climate_template_ui`: coesiste con l'integrazione upstream `climate_template`.
- 1.2 Solo UI: nessun supporto YAML, nessun import.
- 1.3 Parità funzionale completa con l'upstream (tutti i template e tutte le azioni `set_*`).
- 1.4 Requisito minimo: Home Assistant 2026.9.0.
- 1.5 Nota: HA 2026.10 introduce un helper Template Climate nel core, che in UI espone solo
  modalità HVAC, azione HVAC e temperatura; questa integrazione copre anche ventola, preset,
  swing, umidità e range di temperatura.

## 2. Config flow

- 2.1 Una config entry per climate. Un solo step (`user`) con nome, device e quattro sezioni;
  il nome diventa il titolo dell'entry e il nome dell'entità.
- 2.2 Device esistente opzionale (selettore device); l'entità viene mostrata sotto quel device.
  Non sono ammessi device compositi (stessa regola degli helper template del core).
- 2.3 Options flow (`init`): stesso form senza nome, tutti i campi modificabili, reload automatico.
- 2.4 Anteprima live dello stato sia nel config flow sia nell'options flow
  (websocket `climate_template_ui/start_preview`, protocollo dell'anteprima generica del frontend).
- 2.5 Validazione (errori mostrati sopra la sezione interessata, con campo e dettaglio):
  - sintassi dei template (già dal TemplateSelector; per gli attributi: `invalid_template`);
  - azioni come per script/automazioni (`invalid_action`);
  - almeno una modalità HVAC (`no_hvac_modes`);
  - lista fan/preset/swing non vuota se il relativo template o azione è impostato (`empty_mode_list`);
  - temperatura minima < massima (`min_max_temp`);
  - attributi = mappa nome → template (`invalid_attributes`); variabili valide (`invalid_variables`).

## 3. Opzioni (sezioni del form)

### 3.1 Template di stato (`state_templates`)
`current_temperature_template`, `current_humidity_template`, `target_temperature_template`,
`target_temperature_high_template`, `target_temperature_low_template`, `target_humidity_template`,
`min_humidity_template`, `max_humidity_template`, `hvac_mode_template`, `hvac_action_template`,
`fan_mode_template`, `preset_mode_template`, `swing_mode_template`, `min_temp_template`,
`max_temp_template`. Nomi identici all'upstream.

### 3.2 Azioni (`actions`)
| Azione | Variabili |
|---|---|
| `set_temperature` | `temperature`, `target_temp_high`, `target_temp_low`, `hvac_mode` |
| `set_hvac_mode` | `hvac_mode` |
| `set_fan_mode` | `fan_mode` |
| `set_preset_mode` | `preset_mode` |
| `set_swing_mode` | `swing_mode` |
| `set_humidity` | `humidity` |

Sempre disponibili: `this` (stato dell'entità) e le variabili della sezione avanzata.

### 3.3 Modi e limiti (`modes_limits`)
- `modes` (multi-selezione tra tutte le modalità HVAC), default upstream
  `auto, off, cool, heat, dry, fan_only`.
- `fan_modes` (default `auto, low, medium, high`), `preset_modes`
  (default `eco, away, boost, comfort, home, sleep, activity`), `swing_modes` (default `on, off`):
  multi-selezione con valori personalizzati.
- `min_temp` 7, `max_temp` 35 (sovrascritti dai rispettivi template), `temp_step` 1,
  `precision` opzionale (0.1 / 0.5 / 1.0; vuoto = default per unità).

### 3.4 Avanzate (`advanced`)
`availability` (disponibile solo se il template restituisce true), `icon`, `picture`,
`attributes` (nome → template), `variables` (nome → valore o template).

## 4. Comportamento dell'entità (parità upstream)

- 4.1 Valori ottimistici iniziali: hvac `off`, fan `low`, preset `comfort`, swing `off`,
  temperatura obiettivo 21. In `heat_cool` è esposto il range (high/low) e non la temperatura
  singola; viceversa negli altri modi.
- 4.2 I risultati `unknown`/`unavailable`/vuoti vengono ignorati; valori non numerici o fuori
  lista vengono scartati con WARNING mantenendo il valore precedente. Template con testo
  identico su più campi aggiornano tutti i campi.
- 4.3 Una funzione esiste solo se c'è il suo template **o** la sua azione
  (ventola, preset, swing, umidità obiettivo, temperatura obiettivo). TURN_ON/TURN_OFF e
  range di temperatura con la stessa logica dell'upstream.
- 4.4 Restore dello stato precedente al riavvio; tracciamento dei template all'avvio di HA.
- 4.5 Comandi: aggiornamento ottimistico se manca il template, poi esecuzione dell'azione.
  `set_temperature` con `hvac_mode` cambia anche la modalità. `turn_on` usa la logica di HA e,
  se non applicabile, la prima modalità diversa da `off`.

## 5. Logging

- DEBUG: opzioni ricevute, parsing, ogni risultato di template, restore, avvio tracciamento/anteprima.
- INFO: entità pronta (n. template, azioni), entry creata/aggiornata/scaricata, azione eseguita.
- WARNING: template fallito, valore non valido, configurazione rifiutata nel form.
- ERROR: opzioni salvate non più valide (entry in errore), azione fallita.

## 6. Localizzazione

en / it / fr / es / de: form, sezioni, descrizioni campi, errori, etichette delle modalità,
eccezioni.

## 7. Packaging

- Repository HACS, `custom_components/climate_template_ui/`, `hacs.json`, `manifest.json` 2.0.0 (prima versione del fork: major sopra l'ultimo tag upstream v1.4.2).
- Icona `brand/` (HA 2026.3+) + `icon.png` in root.
- README EN e IT con esempi, questa specifica, licenza MIT con credito all'autore originale.
- Workflow CI in `ci/` (hassfest, HACS, lint, test): da copiare in `.github/workflows/`.

## 8. Verifiche eseguite (v2.0.0)

- 23 test pytest su HA reale **2026.10.1** e **2026.9.0**: passati (flow, errori, options,
  anteprima config/options, ottimistico, template, azioni con variabili, heat_cool, disponibilità,
  turn_on, restore, device, entry non valida, esempi README).
- hassfest (core 2026.10.1) sull'integrazione: nessun errore.
- ruff (E,F,W,I,UP,B,SIM,D) su codice e test: pulito.
- API verificate nel sorgente di entrambe le versioni: `section`, selettori, `OptionsFlowWithReload`,
  `async_track_template_result`, `Script`, `ScriptVariables`, `TemplateStateFromEntityId`,
  `_async_calculate_state` (anteprima), collegamento device via `device_entry`, protocollo
  anteprima generica del frontend.
