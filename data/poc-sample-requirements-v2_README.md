# PoC Sample Requirements v2 – Requisiti testabili (Given/When/Then)

Questa variante v2 contiene **100 requisiti** in formato CSV coerente con l'esempio (ReqID, Source, Target, Category, Description) e rende ogni requisito **verificabile** tramite:
- precondizioni (Given)
- trigger (When)
- esito osservabile (Then)
- criteri di accettazione espliciti

## Come usarlo nel PoC di generazione documenti
1. Raggruppa per `Category` + `Source/Target` per generare sezioni del documento (Overview, Trigger, Data, Error Handling, NFR, Security).
2. Usa i `Criteri di accettazione` per auto-generare una sezione "Test considerations".

## Accorpamento suggerito in documenti di integrazione
- **IFD-01 PLM→PIM Inbound**: REQ-001…REQ-015
- **IFD-02 PIM Enrichment Workflows**: REQ-016…REQ-050
- **IFD-03 DAM→PIM Assets**: REQ-051…REQ-065
- **IFD-04 Pricing/Stock + Visual Merch Tool**: REQ-066…REQ-080
- **IFD-05 Outbound Syndication (Google/Amazon/Magento)**: REQ-081…REQ-100

## Nota
Nel campo `Description` trovi anche la riga `Intento originale:` per verificare che la generazione documentale non perda il significato iniziale.
