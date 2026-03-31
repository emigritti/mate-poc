# HOW-TO — Integration Mate PoC

Guida operativa per l'utilizzo della piattaforma **Integration Mate**.

---

## Indice

| # | Guida | Quando usarla |
|---|-------|---------------|
| 01 | [Deploy su EC2](./01-deploy-ec2.md) | Prima messa in produzione, aggiornamento versione |
| 02 | [Gestire la Knowledge Base](./02-knowledge-base.md) | Aggiungere documenti, URL, sorgenti OpenAPI o HTML |
| 03 | [Generare documenti di integrazione](./03-generate-document.md) | Dal CSV dei requisiti al Technical Design approvato |
| 04 | [Gestire Ollama](./04-manage-ollama.md) | Cambio modello, verifica GPU, performance |
| 05 | [Troubleshooting](./05-troubleshooting.md) | Diagnosi e risoluzione dei problemi più comuni |

---

## Architettura in sintesi

```
Browser → Nginx :8080 → Integration Agent  :4003
                      → Ingestion Platform :4006
                      → n8n               :5678/n8n/
Backing services: MongoDB · ChromaDB · Ollama · MinIO
```

## Porte esposte sull'EC2

| Porta | Servizio |
|-------|---------|
| `8080` | Dashboard web + n8n (via nginx gateway) |
| `4003` | Integration Agent API |
| `4006` | Ingestion Platform API |
| `11434` | Ollama (opzionale — solo debug) |
| `9001` | MinIO Console (opzionale) |
