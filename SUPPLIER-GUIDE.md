# Guida rapida per il fornitore

## 1. Crea il branch di delivery

Da `main`, crea un branch:

```
delivery/<YYYY-MM-DD>-v<versione>
```

Esempio: `delivery/2026-09-17-v1.2.0`

## 2. Aggiungi i file nelle cartelle previste

Metti i file nuovi/modificati sotto una di queste cartelle (in base al contenuto):

| Categoria | Cartella |
|---|---|
| `sources` | `sources/` |
| `docs/technical` | `docs/technical/` |
| `docs/user` | `docs/user/` |
| `configuration` | `configuration/` |
| `evidence` | `evidence/` |
| `compliance` | `compliance/` |
| `artifacts` | `artifacts/` (solo se li tieni in git, non come asset della release) |
| `other` | `other/` (richiede `classificationReason`) |

## 3. Aggiorna `release-manifest.yaml`

- Aggiorna `supplierVersion`, `supplierReleaseDate`, `supersedes`, `description`.
- In `materials.folders`: una voce per **ogni cartella** toccata (non elencare i singoli file):
  ```yaml
  - name: demo-sources
    category: sources
    description: ...
  ```
- In `materials.artifacts`: una voce per **ogni file** che allegherai manualmente alla release. `name` deve essere il **nome file esatto** dell'asset:
  ```yaml
  - name: product-demo-v1.2.0.zip
    category: artifacts
    description: ...
  ```

## 4. Aggiorna `RELEASE-NOTES.md`

Descrivi le novità della versione.

## 5. Push del branch

Al push viene creata/aggiornata in automatico una **draft release** `staging/<versione>`.

## 6. Carica gli asset

Vai sulla draft release (tab **Releases** su GitHub) e carica manualmente ogni file dichiarato in `materials.artifacts`.

## 7. Apri la Pull Request verso `main`

Un workflow valida automaticamente manifest e struttura dei file. Correggi eventuali errori finché il check è verde.

## 8. Merge

- **Mancano asset dichiarati** → il workflow di pubblicazione fallisce volutamente e la release resta **Draft**. Carica i file mancanti e rilancia manualmente il workflow *Publish delivery release* da Actions.
- **Tutto presente** → la release viene pubblicata automaticamente (tag `release/...`) e diventa immutabile.

