# HOW-TO 01 — Deploy su EC2

## Prerequisiti

- Istanza EC2 con Docker e Docker Compose installati (Amazon Linux 2 / Ubuntu)
- Security Group con le porte `8080`, `4003`, `4006` aperte in ingresso
- Git installato sull'istanza
- Chiave SSH per accedere all'istanza

---

## 1. Clonare il repository

```bash
ssh -i <your-key.pem> ec2-user@<EC2_PUBLIC_IP>
git clone https://github.com/<org>/my-functional-integration-mate-poc.git
cd my-functional-integration-mate-poc
```

---

## 2. Creare il file .env

Il file `.env` **non è versionato** — va creato manualmente.

**Opzione A — copia da locale:**
```bash
# Da locale
scp -i <your-key.pem> .env ec2-user@<EC2_PUBLIC_IP>:~/my-functional-integration-mate-poc/.env
```

**Opzione B — crea direttamente sull'EC2:**
```bash
nano .env
```

Contenuto minimo obbligatorio (sostituisci i valori `YOUR_*`):

```dotenv
COMPOSE_PROJECT_NAME=integration-mate
EC2_PUBLIC_IP=<EC2_PUBLIC_IP>

# Auth
JWT_SECRET=<stringa-random-min-32-char>
JWT_ALGORITHM=HS256
JWT_EXPIRY_HOURS=24
API_KEY=

# Anthropic (per HTML scraping)
ANTHROPIC_API_KEY=<tua-api-key>

# MongoDB
MONGO_HOST=mate-mongodb
MONGO_PORT=27017
MONGO_DB=integration_mate
MONGO_URI=mongodb://mate-mongodb:27017

# ChromaDB
CHROMA_HOST=mate-chromadb
CHROMA_PORT=8000

# MinIO
S3_ENDPOINT=http://mate-minio:9000
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin
S3_REGION=us-east-1
S3_BUCKET_PLM=plm-assets
S3_BUCKET_PIM=pim-media
S3_BUCKET_DAM_ORIGINALS=dam-originals
S3_BUCKET_DAM_RENDITIONS=dam-renditions

# Ollama
OLLAMA_HOST=http://mate-ollama:11434
OLLAMA_MODEL=llama3.2:3b
OLLAMA_TIMEOUT_SECONDS=180
OLLAMA_NUM_PREDICT=1000

# CORS
CORS_ORIGINS=http://localhost:8080,http://<EC2_PUBLIC_IP>:8080

# URL interni Docker (non modificare)
PLM_API_URL=http://mate-plm-mock:3001
PIM_API_URL=http://mate-pim-mock:3002
DAM_API_URL=http://mate-dam-mock:3005
SECURITY_MW_URL=http://mate-security-middleware:3000
ENGINE_URL=http://mate-integration-agent:3003
CATALOG_URL=http://mate-catalog-generator:3004
INTEGRATION_AGENT_URL=http://mate-integration-agent:3003

# n8n
N8N_ENCRYPTION_KEY=<stringa-random-min-32-char>
N8N_PATH=/n8n/
WEBHOOK_URL=http://<EC2_PUBLIC_IP>:8080/n8n/
N8N_EDITOR_BASE_URL=http://<EC2_PUBLIC_IP>:8080/n8n/
```

---

## 3. Avviare i servizi

```bash
# Prima avvio (scarica immagini + build)
docker compose up -d

# Verifica che tutti i container siano up
docker compose ps
```

Attendi ~2 minuti per il download del modello Ollama al primo avvio.

---

## 4. Verifica

Apri nel browser: `http://<EC2_PUBLIC_IP>:8080`

Controlla i log se qualcosa non parte:
```bash
docker compose logs -f integration-agent
docker compose logs -f ingestion-platform
```

---

## 5. Aggiornare la versione

```bash
git pull origin main
docker compose build web-dashboard integration-agent ingestion-platform
docker compose up -d
```

> Per un aggiornamento solo della dashboard (modifiche React):
> ```bash
> docker compose build web-dashboard && docker compose up -d web-dashboard
> ```

---

## 6. Stop e cleanup

```bash
# Stop senza rimuovere dati
docker compose stop

# Stop + rimozione container (i volumi MongoDB/ChromaDB restano)
docker compose down

# Stop + rimozione completa (ATTENZIONE: cancella tutti i dati)
docker compose down -v
```
