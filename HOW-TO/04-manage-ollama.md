# HOW-TO 04 — Gestire Ollama

Ollama è il server LLM locale che esegue i modelli per la generazione dei documenti. Gira nel container `mate-ollama` (porta `11434`).

---

## Verificare lo stato

```bash
# Stato container
docker compose ps mate-ollama

# Log Ollama
docker compose logs -f mate-ollama

# Test health diretto
curl http://localhost:11434/api/tags
```

---

## Modelli disponibili

Il modello attivo è configurato tramite `OLLAMA_MODEL` nel `.env`.

```bash
# Lista modelli scaricati
curl http://localhost:11434/api/tags | python3 -m json.tool

# Oppure entrando nel container
docker exec -it mate-ollama ollama list
```

---

## Scaricare un modello

```bash
docker exec -it mate-ollama ollama pull llama3.1:8b
docker exec -it mate-ollama ollama pull llama3.2:3b
docker exec -it mate-ollama ollama pull mistral:7b
```

> I modelli vengono salvati nel volume Docker `ollama_data` — persistono tra restart.

---

## Cambiare modello attivo

1. Scarica il nuovo modello (vedi sopra)
2. Modifica `OLLAMA_MODEL` nel `.env`:
   ```dotenv
   OLLAMA_MODEL=llama3.1:8b
   ```
3. Riavvia solo l'integration agent (non serve rebuild):
   ```bash
   docker compose up -d integration-agent
   ```
4. Verifica dalla dashboard: **LLM Settings** → modello corrente

### Cambiare modello senza modificare `.env` (override runtime)

Dalla dashboard → **LLM Settings** → modifica il campo **Model** e salva.
L'override è in memoria — si perde al restart del container.

---

## Parametri di performance

Configura nel `.env` o dalla dashboard **LLM Settings**:

| Parametro | Default | Descrizione |
|-----------|---------|-------------|
| `OLLAMA_NUM_PREDICT` | `1000` | Token massimi per risposta |
| `OLLAMA_TIMEOUT_SECONDS` | `180` | Timeout per chiamata LLM |
| `OLLAMA_TEMPERATURE` | `0.3` | Creatività (0=deterministico, 1=creativo) |

---

## Verifica GPU (istanze EC2 con GPU)

```bash
# Controlla se Ollama usa la GPU
docker exec -it mate-ollama ollama ps

# Verifica utilizzo GPU (se disponibile)
nvidia-smi
```

Se l'istanza non ha GPU, Ollama usa la CPU — la generazione sarà più lenta (~5-10x).

### Istanze consigliate per EC2

| Modello | RAM minima | Istanza EC2 consigliata |
|---------|-----------|------------------------|
| `llama3.2:3b` | 4 GB | `t3.large` (CPU) |
| `llama3.1:8b` | 8 GB | `g4dn.xlarge` (GPU) |
| `mistral:7b` | 8 GB | `g4dn.xlarge` (GPU) |

---

## Problemi comuni

### Timeout durante la generazione
Aumenta il timeout nel `.env`:
```dotenv
OLLAMA_TIMEOUT_SECONDS=300
```
Poi riavvia: `docker compose up -d integration-agent`

### Modello non trovato
```bash
docker exec -it mate-ollama ollama pull <nome-modello>
```

### Container si riavvia in loop
```bash
docker compose logs mate-ollama --tail=50
# Se "out of memory": scegli un modello più piccolo o aumenta la RAM dell'istanza
```

### Eliminare un modello (libera spazio)
```bash
docker exec -it mate-ollama ollama rm llama3.1:8b
```
