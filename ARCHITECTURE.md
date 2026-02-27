# LicitaAI — Arquitetura & Roadmap

## A) Arquitetura — Fluxo End-to-End

```
┌─────────────────────────────────────────────────────────────────────┐
│                        FONTES EXTERNAS                              │
│  ┌──────────────┐  ┌─────────────────────┐  ┌───────────────────┐  │
│  │  PNCP API    │  │ Compras.gov (Dados  │  │ Futuras fontes    │  │
│  │  /v1/contra- │  │  Abertos) API       │  │ (TCE, BEC, etc.)  │  │
│  │  tacoes/     │  │  /modulo-licitacao/  │  │                   │  │
│  └──────┬───────┘  └────────┬────────────┘  └───────────────────┘  │
└─────────┼──────────────────┼───────────────────────────────────────┘
          │                  │
          ▼                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    CELERY BEAT (Scheduler)                           │
│  06:00 UTC → ingest_pncp    06:30 UTC → ingest_compras_gov         │
│  */2h → download_pending    08:00 UTC → check_deadlines             │
└─────────────────────┬───────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     CELERY WORKERS (4 Queues)                       │
│                                                                     │
│  ┌──────────┐  ┌────────────┐  ┌──────────┐  ┌──────────────────┐  │
│  │  ingest  │  │ documents  │  │    ai    │  │  notifications   │  │
│  │          │  │            │  │          │  │                  │  │
│  │ fetch    │  │ download   │  │ extract  │  │ email / webhook  │  │
│  │ normalize│  │ OCR/text   │  │ RAG      │  │ deadline alerts  │  │
│  │ dedup    │  │ chunk      │  │ matching │  │                  │  │
│  │ persist  │  │ embed      │  │ summary  │  │                  │  │
│  └────┬─────┘  └─────┬──────┘  └────┬─────┘  └────────┬─────────┘  │
└───────┼──────────────┼──────────────┼──────────────────┼────────────┘
        │              │              │                  │
        ▼              ▼              ▼                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    PostgreSQL 16 + pgvector                          │
│                                                                     │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌───────────┐  │
│  │ Opportunity  │ │ Document     │ │ DocumentChunk│ │ Client    │  │
│  │ OppItem      │ │ OppDocument  │ │ (+ embedding)│ │ ClientDoc │  │
│  │ ExtReq       │ │              │ │              │ │ Match     │  │
│  │ AISummary    │ │              │ │              │ │ EventNotif│  │
│  └──────────────┘ └──────────────┘ └──────────────┘ └───────────┘  │
└─────────────────────────────────────────────────────────────────────┘
        │                                              │
        ▼                                              ▼
┌────────────────┐                          ┌──────────────────────┐
│  MinIO (S3)    │                          │  Redis               │
│  documents/    │                          │  cache + broker +    │
│  client_docs/  │                          │  celery results      │
└────────────────┘                          └──────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   DJANGO (Web + Admin + DRF)                        │
│                                                                     │
│  /opportunities/       → Lista priorizada + filtros                 │
│  /opportunities/<id>/  → Detalhe com abas (Resumo/Checklist/        │
│                          Riscos/Evidências/Itens/Ações)             │
│  /clients/             → CRUD de clientes + docs                    │
│  /admin/               → Django Admin (backoffice)                  │
│  /api/                 → DRF (futura integração)                    │
│                                                                     │
│  Ações: "Rodar IA" → Celery(ai)                                    │
│         "Rodar Matching" → Celery(ai)                               │
│         Status: novo → em análise → apto → descartado → enviado     │
└─────────────────────────────────────────────────────────────────────┘
```

## Pipeline de Documentos (OCR)

```
Download PDF  →  pdfplumber (texto nativo)
                     │
              chars/page < 100?
                 /         \
               Não         Sim → OCR (pytesseract + pdf2image)
                 │              │
                 ▼              ▼
              Texto final (merge melhor resultado)
                     │
              Chunking (800 tokens, 100 overlap)
                     │
              Embeddings (OpenAI text-embedding-3-small)
                     │
              pgvector (cosine similarity search)
```

## B) Modelos Django

| Modelo               | App           | Campos-chave                                           |
|----------------------|---------------|--------------------------------------------------------|
| Client               | clients       | name, cnpj, regions[], keywords[], min_margin_pct      |
| ClientDocument       | clients       | client FK, doc_type, expires_at, status                |
| Opportunity          | opportunities | source, external_id, dedup_hash (unique), title, modality, entity_*, dates, value, status |
| OpportunityItem      | opportunities | opportunity FK, item_number, description, qty, price   |
| OpportunityDocument  | opportunities | opportunity FK, original_url, file, file_hash, processing_status, extracted_text |
| DocumentChunk        | opportunities | document FK, content, page_number, embedding (vector)  |
| ExtractedRequirement | opportunities | opportunity FK, category, requirement, evidence (JSON) |
| AISummary            | opportunities | opportunity FK, analysis_type, content (JSON), prompt_version, model_name |
| Match                | matching      | opportunity FK, client FK, score (0-100), justification, missing_docs/capabilities |
| EventNotification    | notifications | event_type, channel, recipient, subject, body, delivery_status |

## C) URLs/Views

| URL                              | View                  | Método |
|----------------------------------|-----------------------|--------|
| /                                | → redirect /opportunities/ | GET |
| /accounts/login/                 | Django auth login     | GET/POST |
| /clients/                        | ClientListView        | GET |
| /clients/create/                 | ClientCreateView      | GET/POST |
| /clients/<uuid>/                 | ClientDetailView      | GET |
| /clients/<uuid>/edit/            | ClientUpdateView      | GET/POST |
| /clients/<uuid>/documents/add/   | add_client_document   | POST |
| /opportunities/                  | OpportunityListView   | GET |
| /opportunities/<uuid>/           | OpportunityDetailView | GET |
| /opportunities/<uuid>/run-ai/    | RunAIView             | POST |
| /opportunities/<uuid>/run-matching/ | RunMatchingView    | POST |
| /opportunities/<uuid>/change-status/ | ChangeStatusView  | POST |
| /api/clients/                    | ClientViewSet (DRF)   | CRUD |
| /api/opportunities/              | OpportunityViewSet    | READ |
| /api/opportunities/<id>/run_ai/  | action                | POST |
| /api/opportunities/<id>/run_matching/ | action           | POST |
| /admin/                          | Django Admin          | ALL |

## D) Conectores — Endpoints Reais

### PNCP (pncp.gov.br/api/pncp)
- `GET /v1/contratacoes/publicacao?dataInicial=yyyyMMdd&dataFinal=yyyyMMdd&uf=XX&pagina=1&tamanhoPagina=500`
- `GET /v1/orgaos/{cnpj}/compras/{anoCompra}/{sequencialCompra}/itens`
- `GET /v1/orgaos/{cnpj}/compras/{anoCompra}/{sequencialCompra}/arquivos`
- Público, sem autenticação para leitura

### Compras.gov (dadosabertos.compras.gov.br)
- `GET /modulo-licitacao/v1/licitacoes?dataInicial=yyyy-MM-dd&dataFinal=yyyy-MM-dd&pagina=1`
- Fallback: `GET /modulo-compra/v1/compras` (mesmos params)
- Público, sem autenticação para leitura

### Deduplicação
- **Chave primária**: `dedup_hash = SHA-256(source + ":" + external_id)` → UNIQUE no banco
- **Cross-source**: `object_hash = SHA-256(normalize(título))` → detecta mesmo edital em fontes diferentes
- **Idempotência**: `persist_opportunity()` faz `filter(dedup_hash=...)` antes de INSERT

### Throttling
- `BaseConnector._throttle()` respeita intervalo mínimo entre requests (60 RPM default)
- Cache de 5 minutos via Redis para respostas repetidas
- Retry com backoff exponencial (2s, 4s, 8s) até 3 tentativas

## E) Pipeline IA (RAG)

### Ingestão
1. Download do PDF via `httpx` → MinIO
2. Extração de texto: `pdfplumber` (nativo) → fallback `pytesseract` (OCR se <100 chars/página)
3. Chunking: 800 tokens com overlap de 100
4. Embeddings: `text-embedding-3-small` (1536 dimensões) → `pgvector`

### Prompts (versionados em `apps/ai_engine/prompts.py`)
1. **Extrator** (v1.0): JSON Schema com resumo + checklist (fiscal/jurídica/técnica/econômica) + riscos + campos extraídos. Cada item tem `evidencia: {fonte, trecho, pagina, confianca}`.
2. **Matching** (v1.0): Recebe perfil do cliente + requisitos do edital. Retorna score 0-100 + componentes + documentos faltantes + competências faltantes.
3. **Resumo executivo** (v1.0): Markdown com seções (Objeto, Órgão, Valores, Destaques, Alertas, Go/No-Go).

### Política "não inventar"
- System prompt: "Se não encontrar informação, retorne NÃO ENCONTRADO + sugestão do que procurar"
- Confiança 0.0-1.0 em cada evidência
- Golden files em `tests/golden_files/` para validar formato e cobertura

## F) Celery Tasks & Queues

| Queue          | Tasks                                          | Schedule             |
|----------------|------------------------------------------------|----------------------|
| ingest         | ingest_pncp, ingest_compras_gov                | Diário 06:00/06:30   |
| documents      | download_*, extract_document_text              | A cada 2h + on-demand|
| ai             | run_ai_analysis, run_matching                  | On-demand            |
| notifications  | create_notification, check_critical_deadlines  | Diário 08:00         |

## G) Docker Compose

Serviços: `postgres` (pgvector/pgvector:pg16), `redis` (7-alpine), `minio`, `minio-init` (cria bucket), `web` (Django), `worker` (Celery), `beat` (Celery Beat).

```bash
# Setup completo (1 comando)
cp .env.example .env
docker compose up -d --build
# Ou:
make setup
```

## H) Estrutura de Pastas

```
LicitaAi/
├── .env.example
├── .gitignore
├── ARCHITECTURE.md
├── Dockerfile
├── Makefile
├── docker-compose.yml
├── manage.py
├── pyproject.toml
├── requirements.txt
├── config/
│   ├── __init__.py          # expõe celery_app
│   ├── celery.py            # Celery config + beat schedule
│   ├── urls.py              # Root URL conf
│   ├── wsgi.py / asgi.py
│   └── settings/
│       ├── base.py          # Settings compartilhados
│       ├── development.py
│       └── production.py
├── apps/
│   ├── core/                # Base models, storage, utils
│   ├── clients/             # Client + ClientDocument (models/views/forms/admin/urls)
│   ├── opportunities/       # Opportunity + Items + Docs + Chunks + Reqs + AI (models/views/forms/admin/urls/tasks)
│   ├── connectors/          # PNCP + ComprasGov connectors (base/pncp/compras_gov/normalizer/tasks)
│   ├── ai_engine/           # RAG pipeline (embeddings/prompts/pipeline/rag/tasks)
│   ├── matching/            # Match engine (models/engine/admin/tasks)
│   ├── notifications/       # Alerts (models/notifiers/admin/tasks)
│   └── api/                 # DRF serializers + viewsets
├── templates/
│   ├── base.html
│   ├── registration/login.html
│   ├── opportunities/       # list + detail
│   └── clients/             # list + form + detail
├── static/css/style.css
└── tests/
    ├── conftest.py          # Fixtures compartilhados
    ├── test_models.py       # Unit: models + utils
    ├── test_connectors.py   # Unit: connectors (mocked HTTP)
    ├── test_views.py        # Integration: views (auth + CRUD)
    ├── test_ai.py           # Unit: AI pipeline (mocked LLM)
    └── golden_files/        # Expected AI outputs
        ├── extraction_expected.json
        └── matching_expected.json
```

## I) Plano de Testes

### Unit Tests
- **test_models.py**: Criação, unicidade, relações, utils (normalize, dedup_key, object_hash)
- **test_connectors.py**: PNCPConnector com HTTP mockado, normalização, idempotência
- **test_ai.py**: Chunking, extração com LLM mockado, validação de schema

### Integration Tests
- **test_views.py**: Login obrigatório, CRUD de clientes, listagem de oportunidades
- **Golden files**: `extraction_expected.json` e `matching_expected.json` como referência de formato/qualidade

### Executar
```bash
make test         # pytest -v
make test-cov     # pytest --cov=apps --cov-report=html
```

## J) Roadmap

### Fase 1 — MVP (atual)
- [x] Ingestão PNCP + Compras.gov (coleta diária)
- [x] Modelos de domínio completos
- [x] Download + processamento de documentos (PDF + OCR)
- [x] RAG: chunking + embeddings + pgvector
- [x] Extração IA: checklist + riscos + campos + evidências
- [x] Matching cliente x edital com score
- [x] Dashboard Django (login, list, detail com abas, ações)
- [x] Alertas internos + email + webhook
- [x] Docker Compose (1 comando)
- [x] API DRF base

### Fase 2 — v1.0
- [ ] Mais fontes: BEC-SP, Licitanet, Portal de Compras MG, TCE
- [ ] Busca textual full-text (PostgreSQL FTS + pgvector hybrid)
- [ ] Dashboard com gráficos (volume por UF, por modalidade, timeline)
- [ ] Histórico de preços (análise de preços praticados)
- [ ] Multi-tenant (vários usuários/equipes)
- [ ] Autenticação SSO (OAuth2/SAML)
- [ ] Export PDF/Excel de análises
- [ ] Testes E2E com Playwright
- [ ] CI/CD (GitHub Actions)

### Fase 3 — v2.0
- [ ] SaaS multi-empresa com billing
- [ ] App mobile (PWA ou React Native)
- [ ] Monitoramento de contratos vigentes
- [ ] Predição de resultados (ML com histórico)
- [ ] Integração com sistemas de proposta (ComprasNet, BLL, etc.)
- [ ] Chatbot conversacional sobre editais
- [ ] Análise comparativa de concorrentes
- [ ] API pública para parceiros
