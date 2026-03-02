# Regras de Negocio — Monitoramento de Pregoes

**Projeto:** LicitaAI
**Modulo:** Monitoramento de Pregoes
**Versao:** 1.0
**Data:** 28/02/2026
**Status:** Implementado

---

## 1. Objetivo

O LicitaAI realiza a ingestao diaria de oportunidades de licitacao (PNCP e Compras.gov), porem **nao acompanha mudancas** nos pregoes ja capturados. Este modulo implementa o **monitoramento continuo** das oportunidades rastreadas, detectando movimentacoes relevantes e notificando automaticamente os clientes com interesse comprovado (score de matching).

### 1.1 Problema de Negocio

Empresas que participam de licitacoes perdem prazos e oportunidades porque:

- O status do pregao muda (suspensao, revogacao, reabertura) sem aviso direto ao licitante
- Novos documentos sao publicados (errata, esclarecimentos, impugnacoes)
- Resultados e atas sao publicados e o licitante so descobre dias depois
- Prazos sao alterados (antecipacao ou adiamento) sem ciencia do interessado

### 1.2 Solucao

Polling periodico na API CONSULTA do PNCP para detectar alteracoes e gerar notificacoes proativas via e-mail, WhatsApp e painel interno.

---

## 2. Glossario

| Termo | Definicao |
|-------|-----------|
| Pregao | Modalidade de licitacao publica para aquisicao de bens e servicos comuns |
| PNCP | Portal Nacional de Contratacoes Publicas (pncp.gov.br) |
| API CONSULTA | Endpoint de consulta do PNCP (`pncp.gov.br/api/consulta`) |
| Oportunidade rastreada | Oportunidade ja ingerida no sistema com status ativo (Novo, Em Analise, Apto ou Proposta Enviada) e prazo vigente |
| Evento | Movimentacao detectada em uma oportunidade (mudanca de status, novo documento, resultado, etc.) |
| Match | Associacao entre um cliente e uma oportunidade, com score de aderencia (0-100) |
| Score minimo | Pontuacao minima de match para que o cliente receba notificacoes de monitoramento (padrao: 60) |
| Dedup hash | Hash SHA-256 usado para garantir que o mesmo evento nao seja registrado duas vezes |

---

## 3. Regras de Negocio

### RN-MON-001 — Escopo do Monitoramento

O sistema monitora **exclusivamente** oportunidades que atendem a **todas** as condicoes abaixo:

| # | Condicao | Detalhe |
|---|----------|---------|
| 1 | Fonte PNCP | `source = "pncp"` |
| 2 | Status ativo | `status IN (Novo, Em Analise, Apto, Proposta Enviada)` |
| 3 | Prazo vigente ou indefinido | `deadline > agora` OU `deadline IS NULL` |
| 4 | Apareceu como atualizada | O `external_id` consta no retorno de `/v1/contratacoes/atualizacao` |

**Justificativa:** Oportunidades descartadas ou com prazo vencido nao geram valor ao serem monitoradas. Filtrar antes do detalhamento economiza chamadas a API.

---

### RN-MON-002 — Estrategia de Deteccao em 2 Fases

O monitoramento opera em duas fases para minimizar o consumo de API:

```
FASE 1 — Descoberta (1 request paginado)
  GET /v1/contratacoes/atualizacao?dataInicial=X&dataFinal=Y
  Retorno: lista de compras que sofreram alguma alteracao no periodo
  Resultado: conjunto de external_ids atualizados

FASE 2 — Detalhamento (N requests, so para oportunidades rastreadas)
  Para cada oportunidade rastreada que apareceu na Fase 1:
    GET .../compras/{ano}/{seq}         → detalhe atual
    GET .../compras/{ano}/{seq}/arquivos → documentos atuais
    GET .../compras/{ano}/{seq}/itens/{n}/resultados → resultados
    GET .../compras/{ano}/{seq}/atas    → atas de registro de preco
  Comparar dados frescos com o estado salvo no banco
```

**Justificativa:** A API de atualizacao retorna centenas de compras, mas o sistema so rastreia uma fracao. Buscar detalhes apenas das rastreadas reduz o volume de requests em ~90%.

---

### RN-MON-003 — Tipos de Evento Detectados

O sistema detecta **7 tipos** de evento, comparando o estado salvo (`raw_data`) com os dados frescos da API:

| Codigo | Evento | Como detecta | Prioridade |
|--------|--------|--------------|------------|
| `status_change` | Mudanca de Status | `situacaoCompraId` atual != salvo | Alta |
| `deadline_changed` | Prazo Alterado | `dataEncerramentoProposta` atual != salvo | Alta |
| `value_changed` | Valor Alterado | `valorTotalHomologado` atual != salvo | Media |
| `new_document` | Novo Documento | URL do documento nao existe em `opportunity.documents` | Media |
| `result_published` | Resultado Publicado | Quantidade de resultados por item > quantidade salva | Alta |
| `ata_published` | Ata Publicada | Quantidade de atas > quantidade salva | Media |
| `general_update` | Atualizacao Geral | Reservado para alteracoes nao classificadas acima | Baixa |

---

### RN-MON-004 — Idempotencia de Eventos

Cada evento possui um **hash de deduplicacao** calculado como:

```
dedup_hash = SHA-256( opportunity_id + ":" + event_type + ":" + new_value )
```

| Regra | Comportamento |
|-------|---------------|
| Hash inedito | Evento e criado normalmente |
| Hash ja existe no banco | Evento e ignorado (nao cria duplicata) |

**Justificativa:** O monitoramento roda multiplas vezes ao dia. A mesma alteracao pode aparecer em execucoes consecutivas. O hash garante que cada mudanca gera no maximo 1 registro.

---

### RN-MON-005 — Frequencia de Execucao

| Parametro | Valor | Justificativa |
|-----------|-------|---------------|
| Frequencia | 5x/dia | Horario comercial brasileiro (08:30, 11:30, 14:30, 17:30, 20:30 BRT) |
| Janela de busca | 6 horas para tras | Cobre o intervalo entre execucoes com margem |
| Fila Celery | `ingest` | Compartilha infraestrutura com a ingestao diaria |
| Retentativas | 2 (com intervalo de 5 minutos) | Resiliencia a instabilidades da API PNCP |

**Justificativa:** O PNCP publica atualizacoes ao longo do dia util. 5 verificacoes diarias garantem deteccao em ate ~3 horas sem sobrecarregar a API (respeitando rate limit de 60 RPM).

---

### RN-MON-006 — Regras de Notificacao

Para cada evento detectado, o sistema notifica os clientes que possuem **match ativo** com a oportunidade:

| Condicao | Regra |
|----------|-------|
| Score minimo | Somente clientes com `match.score >= 60` (configuravel via `MONITORING_MIN_MATCH_SCORE`) |
| Canais | E-mail (se `client.notify_email = True`), WhatsApp (se `client.notify_whatsapp = True`), Interno (sempre) |
| Dedup temporal | Se ja existe notificacao do mesmo tipo para o mesmo par (oportunidade + cliente) na ultima 1 hora, nao envia novamente |

#### Mapeamento Evento → Tipo de Notificacao

| Evento do Pregao | Tipo de Notificacao |
|-------------------|---------------------|
| `status_change`, `deadline_changed`, `value_changed`, `general_update` | `pregao_status_change` |
| `new_document` | `pregao_new_document` |
| `result_published`, `ata_published` | `pregao_result` |

---

### RN-MON-007 — Atualizacao do Estado da Oportunidade

Apos a deteccao de eventos, o sistema **atualiza o estado salvo** da oportunidade:

| Campo | Atualizacao |
|-------|-------------|
| `raw_data` | Substituido pelo JSON fresco da API, incluindo metadados `_monitored_results` e `_monitored_atas` para controle de contagem |
| `last_monitored_at` | Atualizado com o timestamp da verificacao |
| `deadline` | Atualizado se `dataEncerramentoProposta` mudou |
| `awarded_value` | Atualizado se `valorTotalHomologado` mudou |

**Justificativa:** Manter o `raw_data` atualizado e essencial para que a proxima execucao compare contra o estado mais recente, evitando re-deteccao de eventos ja processados.

---

### RN-MON-008 — Persistencia de Novos Documentos

Quando um evento do tipo `new_document` e detectado:

1. O sistema cria um registro `OpportunityDocument` com status `Pendente`
2. Dispara automaticamente a task de download do documento
3. O pipeline existente (download → extracao → chunking → embedding) processa o novo documento

**Justificativa:** Novos documentos (erratas, esclarecimentos) podem conter informacoes criticas para a decisao de participacao. O processamento automatico garante que a analise de IA esteja sempre atualizada.

---

## 4. Fluxo Operacional

```
                    Celery Beat (5x/dia)
                           |
                           v
              +---------------------------+
              | Task: monitor_pregoes     |
              | Janela: 6 horas           |
              +---------------------------+
                           |
                    FASE 1 — Descoberta
                           |
                           v
              +---------------------------+
              | GET /contratacoes/        |
              |     atualizacao           |
              | Retorno: [ext_ids]        |
              +---------------------------+
                           |
                    Filtrar: somente
                    oportunidades rastreadas
                    (ativas + prazo vigente)
                           |
                           v
                  Nenhuma rastreada?
                   /              \
                 Sim               Nao
                  |                 |
               FIM (log)     FASE 2 — Detalhamento
                                    |
                           +--------+--------+
                           |        |        |
                           v        v        v
                        Detalhe   Docs   Resultados/Atas
                           |        |        |
                           +--------+--------+
                                    |
                                    v
                       +------------------------+
                       | detect_changes()       |
                       | Compara fresco vs salvo|
                       +------------------------+
                                    |
                           Alguma mudanca?
                            /          \
                          Nao           Sim
                           |             |
                           |             v
                           |   +--------------------+
                           |   | persist_events()   |
                           |   | (dedup por hash)   |
                           |   +--------------------+
                           |             |
                           |             v
                           |   +--------------------+
                           |   | Para cada evento:  |
                           |   | notify_pregao_event|
                           |   +--------------------+
                           |             |
                           v             v
                       +------------------------+
                       | update_opportunity_    |
                       | from_fresh()           |
                       | (raw_data, deadline,   |
                       |  awarded_value,        |
                       |  last_monitored_at)    |
                       +------------------------+
```

---

## 5. Modelo de Dados

### 5.1 OpportunityEvent (novo)

| Campo | Tipo | Descricao |
|-------|------|-----------|
| `id` | UUID | PK auto-gerado |
| `opportunity` | FK → Opportunity | Oportunidade monitorada |
| `event_type` | CharField(30) | Tipo do evento (vide RN-MON-003) |
| `old_value` | TextField | Valor anterior (ex: "Divulgada") |
| `new_value` | TextField | Valor novo (ex: "Homologada") |
| `description` | TextField | Descricao legivel do evento |
| `raw_data` | JSONField | Dados brutos da API para auditoria |
| `dedup_hash` | CharField(64) | SHA-256 para idempotencia (UNIQUE) |
| `detected_at` | DateTimeField | Momento da deteccao (auto) |
| `created_at` | DateTimeField | Timestamp de criacao (herdado) |

### 5.2 Opportunity (campo adicionado)

| Campo | Tipo | Descricao |
|-------|------|-----------|
| `last_monitored_at` | DateTimeField (nullable) | Ultima vez que o monitoramento verificou esta oportunidade |

### 5.3 EventNotification (choices adicionados)

| Event Type | Label |
|------------|-------|
| `pregao_status_change` | Mudanca de Status do Pregao |
| `pregao_new_document` | Novo Documento no Pregao |
| `pregao_result` | Resultado do Pregao |

---

## 6. Integracao com APIs Externas

### 6.1 Endpoints PNCP Utilizados

| Endpoint | Fase | Proposito | Cache |
|----------|------|-----------|-------|
| `GET /v1/contratacoes/atualizacao` | 1 | Listar compras atualizadas no periodo | Nao |
| `GET /v1/orgaos/{cnpj}/compras/{ano}/{seq}` | 2 | Detalhe atualizado da compra | Nao |
| `GET /v1/orgaos/{cnpj}/compras/{ano}/{seq}/arquivos` | 2 | Documentos atuais | Nao |
| `GET /v1/orgaos/{cnpj}/compras/{ano}/{seq}/itens/{n}/resultados` | 2 | Resultados por item | Nao |
| `GET /v1/orgaos/{cnpj}/compras/{ano}/{seq}/atas` | 2 | Atas de registro de preco | Nao |

**Nota:** Todos os requests de monitoramento sao feitos **sem cache** (metodo `_get_nocache`) para garantir dados frescos. O throttle (rate limit) e retry com backoff exponencial sao mantidos.

### 6.2 Consumo Estimado de API

| Cenario | Oportunidades rastreadas | Requests/execucao | Requests/dia (5x) |
|---------|--------------------------|--------------------|--------------------|
| Conservador | 50 | ~1 (fase 1) + ~200 (fase 2) | ~1.005 |
| Medio | 200 | ~2 + ~800 | ~4.010 |
| Alto | 500 | ~5 + ~2.000 | ~10.025 |

**Nota:** Cada oportunidade rastreada gera ate 4 requests na Fase 2 (detalhe + docs + resultados + atas). O rate limit de 60 RPM e respeitado pelo throttle do BaseConnector.

---

## 7. Configuracoes

| Variavel de Ambiente | Padrao | Descricao |
|----------------------|--------|-----------|
| `PNCP_CONSULTA_API_BASE_URL` | `https://pncp.gov.br/api/consulta` | Base URL da API CONSULTA do PNCP |
| `MONITORING_BATCH_SIZE` | 50 | Tamanho do lote por pagina na API de atualizacao |
| `MONITORING_MIN_MATCH_SCORE` | 60 | Score minimo de match para notificar clientes |

---

## 8. Operacao Manual

O monitoramento pode ser executado manualmente via management command:

```bash
# Execucao sincrona (resultado imediato)
python manage.py monitor_pregoes --sync --hours-back=6

# Despacha como task Celery (retorno assincrono)
python manage.py monitor_pregoes --hours-back=24
```

| Argumento | Padrao | Descricao |
|-----------|--------|-----------|
| `--hours-back` | 6 | Horas para tras na busca de atualizacoes |
| `--sync` | False | Executa direto em vez de despachar para Celery |

---

## 9. Observabilidade

### 9.1 Admin Django

| Tela | O que mostra |
|------|--------------|
| Oportunidade > Detalhe | Inline com eventos detectados + campo `last_monitored_at` (somente leitura) |
| Eventos das Oportunidades (listagem) | Filtro por tipo de evento, busca por descricao, hierarquia por data de deteccao |
| Notificacoes | Filtro por `pregao_status_change`, `pregao_new_document`, `pregao_result` |

### 9.2 Logs

| Logger | Nivel | Mensagens |
|--------|-------|-----------|
| `apps.connectors.tasks` | INFO | Inicio/fim do monitoramento, total verificado, eventos criados |
| `apps.connectors.monitoring` | INFO | Cada evento novo detectado com tipo, external_id e descricao |
| `apps.connectors.pncp` | INFO | Requests HTTP (nocache) com URL e params |
| `apps.notifications.tasks` | INFO | Notificacoes criadas por evento |

### 9.3 API REST

O `OpportunityDetailSerializer` agora inclui o campo `events` (lista de eventos) no endpoint de detalhe da oportunidade.

---

## 10. Criterios de Aceite

| # | Criterio | Validacao |
|---|----------|-----------|
| CA-01 | Migration roda sem erro | `python manage.py migrate` |
| CA-02 | Monitoramento detecta mudanca de status | Alterar `situacaoCompraId` no mock e verificar evento `status_change` |
| CA-03 | Monitoramento detecta novo documento | Adicionar URL inedita nos docs frescos e verificar evento `new_document` |
| CA-04 | Monitoramento detecta resultado publicado | Adicionar resultado por item e verificar evento `result_published` |
| CA-05 | Monitoramento detecta alteracao de prazo | Alterar `dataEncerramentoProposta` e verificar evento `deadline_changed` |
| CA-06 | Monitoramento detecta alteracao de valor | Definir `valorTotalHomologado` e verificar evento `value_changed` |
| CA-07 | Eventos sao idempotentes | Executar monitoramento 2x consecutivas — segunda execucao nao cria duplicatas |
| CA-08 | Notificacoes sao enviadas para clientes com score >= 60 | Criar match com score 70 e verificar criacao de EventNotification |
| CA-09 | Notificacoes respeitam dedup temporal (1h) | Executar 2x em menos de 1 hora — segunda execucao nao duplica notificacoes |
| CA-10 | Oportunidade atualiza raw_data e last_monitored_at | Verificar campos apos execucao |
| CA-11 | Novo documento e persistido e download disparado | Verificar criacao de OpportunityDocument com status Pendente |
| CA-12 | Testes automatizados passam | `pytest tests/test_monitoring.py -v` (13 testes) |
| CA-13 | Comando manual funciona | `python manage.py monitor_pregoes --sync --hours-back=1` |

---

## 11. Riscos e Mitigacoes

| Risco | Impacto | Probabilidade | Mitigacao |
|-------|---------|---------------|-----------|
| API PNCP indisponivel | Monitoramento falha por horas | Media | Retry automatico (2x com backoff) + alerta de erro no log |
| Volume alto de oportunidades rastreadas | Excede rate limit da API | Baixa | Throttle no BaseConnector (60 RPM) + batch por pagina |
| Alteracao na estrutura do JSON da API | Deteccao silenciosa de falha | Baixa | Campos ausentes tratados com `.get()` + fallback vazio |
| Falso positivo (evento detectado sem mudanca real) | Notificacao desnecessaria ao cliente | Muito Baixa | Comparacao exata de valores + dedup hash |
| Acumulo de eventos historicos | Crescimento de tabela | Baixa | Futura politica de retencao (ex: arquivar eventos > 90 dias) |

---

## 12. Evolucoes Futuras

| Item | Descricao | Prioridade |
|------|-----------|------------|
| Monitoramento Compras.gov | Estender o polling para oportunidades da fonte Compras.gov | Media |
| Dashboard de eventos | Tela dedicada com timeline de eventos por oportunidade | Alta |
| Configuracao por cliente | Permitir cliente escolher quais tipos de evento receber | Media |
| Webhook para eventos | Disparar webhook com payload do evento para integracoes externas | Baixa |
| Metricas de monitoramento | Painel com volume de eventos/dia, tempo medio de deteccao | Baixa |
| Retencao de eventos | Arquivar ou purgar eventos mais antigos que N dias | Baixa |
