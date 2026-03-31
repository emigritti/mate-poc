# HOW-TO 05 — Troubleshooting

Riferimento rapido per i problemi più comuni.

---

## Comandi diagnostici generali

```bash
# Stato di tutti i container
docker compose ps

# Log di un servizio specifico (ultimi 100 righe)
docker compose logs --tail=100 <service-name>

# Log in tempo reale
docker compose logs -f <service-name>

# Utilizzo risorse
docker stats --no-stream
```

**Nomi servizi disponibili:**
`mate-integration-agent`, `mate-ingestion-platform`, `mate-web-dashboard`,
`mate-mongodb`, `mate-chromadb`, `mate-ollama`, `mate-minio`,
`mate-gateway`, `mate-n8n`, `mate-plm-mock`, `mate-pim-mock`

---

## Dashboard non raggiungibile (porta 8080)

**Sintomi:** browser mostra "Connection refused" o timeout.

```bash
# Verifica che il gateway nginx sia up
docker compose ps mate-gateway

# Controlla i log nginx
docker compose logs mate-gateway

# Riavvia il gateway
docker compose restart mate-gateway
```

Verifica anche che la porta `8080` sia aperta nel **Security Group AWS**.

---

## Integration Agent non risponde

**Sintomi:** spinner infinito, errori "Failed to connect" nella dashboard.

```bash
docker compose logs mate-integration-agent --tail=50

# Riavvio pulito
docker compose restart mate-integration-agent

# Health check diretto
curl http://localhost:4003/health
```

**Causa frequente:** Ollama non ancora pronto al boot → l'agent va in retry.
Attendi 60 secondi e riprova.

---

## Generazione documenti bloccata / timeout

**Sintomi:** il log dell'agente si ferma, nessun documento generato.

```bash
docker compose logs mate-integration-agent -f
# Cerca errori tipo: "Connection timeout", "Model not found", "OOM"
```

**Soluzioni:**
1. Aumenta `OLLAMA_TIMEOUT_SECONDS` nel `.env` (default 180 → prova 300)
2. Verifica che il modello sia scaricato: `docker exec -it mate-ollama ollama list`
3. Se RAM insufficiente: switcha a `llama3.2:3b`

---

## ChromaDB errori / indice corrotto

**Sintomi:** errori `Collection not found`, retrieval restituisce 0 risultati.

```bash
docker compose logs mate-chromadb --tail=50

# Reset ChromaDB dalla dashboard
# Admin → Reset Tools → Reset ChromaDB
```

Oppure via API:
```bash
curl -X DELETE http://localhost:4003/api/v1/admin/reset/chromadb \
  -H "X-API-Key: <API_KEY>"
```

> Dopo il reset devi re-uplodare i documenti KB o ri-triggerare le ingestion.

---

## MongoDB non si connette

```bash
docker compose logs mate-mongodb --tail=30

# Verifica connessione
docker exec -it mate-mongodb mongosh --eval "db.adminCommand('ping')"

# Riavvio
docker compose restart mate-mongodb
```

**Verifica `MONGO_URI` nel `.env`** — deve usare il nome container `mate-mongodb`, non `localhost`.

---

## Ingestion Platform non indicizza

**Sintomi:** `POST /api/v1/ingest/html/<id>` restituisce 202 ma i chunk non appaiono in KB.

```bash
docker compose logs mate-ingestion-platform -f

# Controlla lo stato dell'ultimo run
curl http://localhost:4006/api/v1/sources/<source_id>
```

**Cause frequenti:**
- `ANTHROPIC_API_KEY` mancante → Claude non disponibile, nessun chunk estratto
- Sito con JS rendering → le pagine risultano vuote dopo il clean
- Dominio esterno non raggiungibile dal container EC2

---

## n8n non si avvia o perde le credenziali

```bash
docker compose logs mate-n8n --tail=50
```

**`N8N_ENCRYPTION_KEY` cambiata** — le credenziali crittografate diventano illeggibili.
Non cambiare mai `N8N_ENCRYPTION_KEY` su un'istanza con workflow configurati.

Per reset completo n8n:
```bash
docker compose down mate-n8n
docker volume rm integration-mate_n8n_data
docker compose up -d mate-n8n
```

---

## MinIO / upload file non funziona

```bash
docker compose logs mate-minio --tail=30

# Verifica che i bucket esistano
docker exec -it mate-minio mc ls local/
```

Se i bucket mancano al primo avvio:
```bash
docker compose restart mate-minio
# Attendi 30s, poi riavvia l'agente
docker compose restart mate-integration-agent
```

---

## Reset completo della piattaforma

> **ATTENZIONE:** cancella tutti i dati (KB, documenti, approvazioni).

```bash
# Via dashboard: Admin → Reset Tools → Reset All
# Via API:
curl -X DELETE http://localhost:4003/api/v1/admin/reset/all \
  -H "X-API-Key: <API_KEY>"
```

Per un reset Docker completo (volumi inclusi):
```bash
docker compose down -v
docker compose up -d
```

---

## Log utili per il supporto

Quando apri una segnalazione, allega sempre:

```bash
docker compose ps > stato_servizi.txt
docker compose logs mate-integration-agent --tail=200 > log_agent.txt
docker compose logs mate-ingestion-platform --tail=100 > log_ingestion.txt
```
