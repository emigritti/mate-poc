# AWS Deployment Guide — Functional Integration Mate PoC

Approccio: **EC2 Lift & Shift con Docker Compose**.
Tutti i container girano su una singola istanza EC2, identici all'ambiente locale,
senza riscrivere l'infrastruttura. Ideale per un PoC.

---

## Panoramica architettura su AWS

```
Internet
   │
   ▼
┌──────────────────────────────────────────┐
│  EC2 (Elastic IP pubblica)               │
│                                          │
│  :8080  → web-dashboard  (nginx)         │
│  :4000  → security-middleware            │
│  :4001  → plm-mock                       │
│  :4002  → pim-mock                       │
│  :4003  → integration-agent  ←── LLM    │
│  :4004  → catalog-generator              │
│  :4005  → dam-mock                       │
│                                          │
│  Interno (non esposto):                  │
│    MongoDB  :27017                       │
│    ChromaDB :8000                        │
│    Ollama   :11434                       │
│    MinIO    :9000/:9001                  │
└──────────────────────────────────────────┘
```

**Modifiche al codice già applicate (non devi fare nulla):**
- `services/web-dashboard/js/api.js` — URL dinamici via `window.location.hostname`
- `docker-compose.yml` — `CORS_ORIGINS` iniettato da env var
- `docker-compose.yml` — ChromaDB pinnato a `0.5.3` (allineato al client Python)

---

## Prerequisiti

- Account AWS attivo con permessi EC2
- AWS CLI installato e configurato (`aws configure`)
  oppure accesso alla AWS Console web
- Terminale con SSH (macOS/Linux: built-in; Windows: PuTTY o WSL)
- Il codice del progetto su Git (o pronto per SCP)

---

## Step 1 — Scegliere il tipo di istanza EC2

| Istanza | vCPU | RAM | Ollama performance | Costo/ora* |
|---------|------|-----|--------------------|-----------|
| `t3.large` | 2 | 8 GB | Lenta (possibili OOM) | ~$0.08 |
| **`t3.xlarge`** | **4** | **16 GB** | **OK per PoC (consigliata)** | **~$0.17** |
| `t3.2xlarge` | 8 | 32 GB | Buona | ~$0.33 |
| `g4dn.xlarge` | 4 | 16 GB + GPU T4 | Molto veloce | ~$0.53 |

> *Prezzi us-east-1, soggetti a variazione. Ferma l'istanza quando non la usi.

**Raccomandazione PoC: `t3.xlarge`** (4 vCPU, 16 GB).
Il modello `llama3.1:8b` richiede ~8 GB RAM solo per sé; gli altri
container ne usano altri ~3-4 GB.

---

## Step 2 — Creare la Key Pair SSH

1. Vai su **AWS Console → EC2 → Key Pairs → Create key pair**
2. Nome: `mate-poc-key`
3. Tipo: `RSA`, formato: `.pem`
4. Scarica e salva il file `.pem`

```bash
# macOS/Linux: imposta i permessi corretti
chmod 400 ~/Downloads/mate-poc-key.pem
```

---

## Step 3 — Creare il Security Group

1. **EC2 → Security Groups → Create security group**
2. Nome: `mate-poc-sg`
3. Aggiungi le seguenti **Inbound rules**:

| Type | Protocol | Port range | Source | Descrizione |
|------|----------|------------|--------|-------------|
| SSH | TCP | 22 | My IP | Accesso amministrativo |
| Custom TCP | TCP | 8080 | 0.0.0.0/0 | Web Dashboard |
| Custom TCP | TCP | 4000 | 0.0.0.0/0 | Security Middleware |
| Custom TCP | TCP | 4001 | 0.0.0.0/0 | PLM Mock API |
| Custom TCP | TCP | 4002 | 0.0.0.0/0 | PIM Mock API |
| Custom TCP | TCP | 4003 | 0.0.0.0/0 | Integration Agent |
| Custom TCP | TCP | 4004 | 0.0.0.0/0 | Catalog Generator |
| Custom TCP | TCP | 4005 | 0.0.0.0/0 | DAM Mock API |

> **Nota sicurezza PoC**: aprire le porte a `0.0.0.0/0` va bene per un PoC
> temporaneo. In produzione, limitare le porte backend al solo IP del
> frontend/ALB.

4. Outbound: lascia tutto aperto (default)
5. **Create security group**

---

## Step 4 — Lanciare l'istanza EC2

1. **EC2 → Launch Instance**
2. **Name**: `mate-poc-server`
3. **AMI**: Ubuntu Server 24.04 LTS (HVM) — cerca "Ubuntu 24.04"
   (oppure Amazon Linux 2023 — i comandi della guida sono per Ubuntu)
4. **Instance type**: `t3.xlarge`
5. **Key pair**: seleziona `mate-poc-key`
6. **Network settings → Edit**:
   - VPC: default
   - Auto-assign public IP: **Enable**
   - Security group: seleziona `mate-poc-sg`
7. **Configure storage**: cambia da 8 GB a **50 GB** (gp3)
   - 50 GB copre: Docker images (~5 GB) + Ollama model llama3.1:8b (~5 GB) + dati
8. **Launch instance**

---

## Step 5 — Allocare un Elastic IP (IP statico)

Senza Elastic IP, l'IP cambia ad ogni riavvio dell'istanza.

1. **EC2 → Elastic IPs → Allocate Elastic IP address**
2. **Allocate**
3. Seleziona il nuovo IP → **Actions → Associate Elastic IP address**
4. Instance: seleziona `mate-poc-server` → **Associate**
5. Nota l'IP pubblico (es. `54.123.45.67`) — ti servirà in seguito

---

## Step 6 — Connettersi via SSH

```bash
ssh -i ~/Downloads/mate-poc-key.pem ubuntu@<ELASTIC-IP>

# Esempio:
ssh -i ~/Downloads/mate-poc-key.pem ubuntu@54.123.45.67
```

---

## Step 7 — Installare Docker e Docker Compose

```bash
# Aggiorna il sistema
sudo apt-get update -y && sudo apt-get upgrade -y

# Installa dipendenze
sudo apt-get install -y \
    ca-certificates curl gnupg lsb-release git

# Aggiungi il repository Docker ufficiale
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
    sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update -y
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Aggiungi l'utente al gruppo docker (no sudo richiesto)
sudo usermod -aG docker ubuntu

# Applica il gruppo senza logout/login
newgrp docker

# Verifica
docker --version
docker compose version
```

---

## Step 8 — Copiare il progetto sull'EC2

### Opzione A — Git (consigliata se il repo è su GitHub/GitLab)

```bash
# Sull'EC2
git clone https://github.com/TUO-USERNAME/my-functional-integration-mate-poc.git
cd my-functional-integration-mate-poc
```

### Opzione B — SCP dal tuo computer locale

```bash
# Dal tuo computer locale (non dall'EC2)
scp -i ~/Downloads/mate-poc-key.pem -r \
    "C:/Project/Agentic/my-functional-integration-mate-poc" \
    ubuntu@54.123.45.67:~/my-functional-integration-mate-poc

# Poi torna sull'EC2
ssh -i ~/Downloads/mate-poc-key.pem ubuntu@54.123.45.67
cd ~/my-functional-integration-mate-poc
```

---

## Step 9 — Creare il file `.env` per AWS

```bash
# Dall'EC2, nella directory del progetto
nano .env
```

Incolla e **sostituisci `54.123.45.67` con il tuo Elastic IP**:

```env
# ── AWS: sostituisci con il tuo Elastic IP ──────────────────────
CORS_ORIGINS=http://54.123.45.67:8080

# ── Storage ─────────────────────────────────────────────────────
S3_ACCESS_KEY=minioadmin-poc
S3_SECRET_KEY=minioadmin-poc-secret

# ── Security ─────────────────────────────────────────────────────
# Genera un secret casuale: openssl rand -hex 32
JWT_SECRET=cambia-questo-con-un-valore-sicuro-openssl-rand-hex-32
```

Salva con `Ctrl+O`, `Enter`, `Ctrl+X`.

> **Perché solo CORS_ORIGINS?**
> Le variabili `OLLAMA_HOST`, `CHROMA_HOST`, `MONGO_URI` usano già i
> nomi interni Docker (`mate-ollama`, `mate-chromadb`, ecc.) che
> funzionano invariati sulla stessa rete bridge anche su EC2.

---

## Step 10 — Aumentare la Swap (precauzione per Ollama)

Su t3.xlarge con 16 GB RAM, llama3.1:8b usa ~8-9 GB. Aggiungere swap
evita OOM killer durante il caricamento del modello.

```bash
sudo fallocate -l 8G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

# Rendi la swap permanente
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# Verifica
free -h
```

---

## Step 11 — Build e avvio dei container

```bash
# Dalla directory del progetto
cd ~/my-functional-integration-mate-poc

# Build di tutte le immagini (richiede 5-10 minuti la prima volta)
docker compose build

# Avvia tutti i servizi in background
docker compose up -d

# Monitora lo stato dei container
docker compose ps
```

Attendi che tutti i container abbiano `Status: Up`. I primi 2-3 minuti
vedrai errori di retry (ChromaDB, MongoDB, Ollama — normale, si aspettano
a vicenda).

```bash
# Controlla i log in tempo reale
docker compose logs -f integration-agent
```

---

## Step 12 — Scaricare il modello LLM (Ollama)

Il container Ollama parte senza modelli. Devi scaricarlo esplicitamente.
Il download di `llama3.1:8b` è ~4.7 GB — richiede qualche minuto.

```bash
# Esegui il pull del modello dentro il container Ollama
docker exec -it mate-ollama ollama pull llama3.1:8b

# Verifica che il modello sia disponibile
docker exec -it mate-ollama ollama list
```

Output atteso:
```
NAME            ID              SIZE    MODIFIED
llama3.1:8b     ...             4.7 GB  Just now
```

---

## Step 13 — Verificare che tutto funzioni

```bash
# Health check di tutti i servizi chiave
curl -s http://localhost:4003/health | python3 -m json.tool
```

Risposta attesa:
```json
{
    "status": "healthy",
    "service": "integration-agent",
    "chromadb": "connected",
    "mongodb": "connected"
}
```

```bash
# Health check degli altri servizi
curl -s http://localhost:4001/health  # PLM
curl -s http://localhost:4002/health  # PIM
curl -s http://localhost:4004/health  # Catalog Generator
curl -s http://localhost:4000/health  # Security Middleware
```

---

## Step 14 — Aprire il browser

Apri: **`http://<ELASTIC-IP>:8080`**

Esempio: `http://54.123.45.67:8080`

Il dashboard dovrebbe caricarsi. I pallini nel sidebar mostreranno
lo stato di salute dei servizi.

---

## Gestione costi: fermare l'istanza quando non è in uso

```bash
# Dal tuo computer locale
aws ec2 stop-instances --instance-ids <INSTANCE-ID>

# Per riavviarla
aws ec2 start-instances --instance-ids <INSTANCE-ID>
```

L'**Elastic IP** rimane associato e non cambia. I dati nei volumi Docker
(MongoDB, ChromaDB, MinIO) **persistono** tra i restart dell'istanza.

> Attenzione: un Elastic IP non associato a un'istanza in esecuzione
> costa ~$0.005/ora. Libera l'IP se elimini l'istanza.

---

## Troubleshooting

### ChromaDB: "Could not connect to tenant default_tenant"

```bash
# Rimuovi il volume e riavvia
docker compose stop chromadb integration-agent
docker volume rm my-functional-integration-mate-poc_chroma-data
docker compose up -d chromadb
sleep 15
docker compose up -d integration-agent
```

### Ollama: out of memory / modello non caricato

```bash
# Verifica RAM disponibile
free -h

# Verifica swap
swapon --show

# Riprova il pull del modello
docker exec -it mate-ollama ollama pull llama3.1:8b
```

### Integration Agent non si connette a ChromaDB/MongoDB

```bash
# Controlla che i container siano tutti Up
docker compose ps

# Guarda i log dell'agent
docker compose logs --tail=50 integration-agent

# Riavvia solo l'agent (dopo che gli altri sono pronti)
docker compose restart integration-agent
```

### CORS errors nel browser (console F12)

Verifica che in `.env` il tuo Elastic IP sia corretto:
```bash
cat .env | grep CORS_ORIGINS
# Deve essere: CORS_ORIGINS=http://<TUO-IP>:8080
```

Poi ricrea i container per applicare le env vars:
```bash
docker compose down
docker compose up -d
```

### Il dashboard non risponde alle API

Apri la console del browser (F12 → Network) e verifica che le
chiamate vadano a `http://<TUO-IP>:4003` (non `localhost`).
Se vedi ancora `localhost`, svuota la cache del browser (Ctrl+Shift+R).

### Vedere tutti i log

```bash
# Tutti i servizi
docker compose logs -f

# Solo un servizio
docker compose logs -f integration-agent
docker compose logs -f chromadb
docker compose logs -f ollama
```

---

## Riepilogo modifiche al codice

| File | Modifica | Motivo |
|------|----------|--------|
| `services/web-dashboard/js/api.js` | URL dinamici via `window.location.hostname` | La SPA usa l'host della pagina invece di `localhost` hardcoded |
| `docker-compose.yml` | `CORS_ORIGINS` letto da env var | Permette di sovrascrivere i CORS con l'IP dell'EC2 via `.env` |
| `docker-compose.yml` | `chromadb/chroma:0.5.3` (da `latest`) | Allinea server e client Python alla stessa versione |

---

*Guida generata per il progetto Functional Integration Mate PoC — 2026-03-06*
