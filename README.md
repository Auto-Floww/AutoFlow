# AutoFlow

O AutoFlow é um sistema SaaS multiempresa para atendimento e vendas pelo
WhatsApp com IA. Ele reúne painel operacional, CRM, produtos e estoque,
entrega, agenda, base de conhecimento e atendimento híbrido entre IA e equipe
humana. A interface é servida pelo Flask com Jinja2, HTML, CSS e JavaScript
puro.

> **Escopo visual e Landing Page:** este repositório contém exclusivamente o
> painel SaaS. A Landing Page já existe em outro repositório e não foi
> recriada. Como a URL/repositório dela não foi fornecida, ainda não foi
> possível conferir a identidade visual nem alterar os CTAs **Quero
> automatizar** e **Começar agora**. Quando essa URL for disponibilizada, os
> CTAs devem apontar para `${APP_URL}/register` e `${APP_URL}/login`.

## Arquitetura

- Python 3.12, Flask, Blueprints e Controllers em classes, usando application factory;
- SQLAlchemy e Flask-Migrate/Alembic sobre MySQL 8;
- Flask-Login, CSRF, CORS, rate limiting e isolamento por `company_id`;
- templates Jinja2 e assets HTML5/CSS3/JavaScript ES6+;
- Groq API para IA e tool calling, sem acesso direto da IA ao banco;
- Evolution API v2 encapsulada em Service externo e executada em stack Docker isolada;
- Celery, Redis e transactional outbox para processamento assíncrono durável;
- Pytest com SQLite em memória para testes isolados;
- Gunicorn e Docker Compose para execução em contêineres.

O fluxo principal responde rapidamente ao webhook e transfere o trabalho
demorado ao worker:

```text
WhatsApp -> Flask webhook -> banco + outbox -> Celery -> Groq/tools -> WhatsApp
```

Para os casos de uso novos, a separação adotada é:

```text
backend/controllers/   # classes que traduzem HTTP e chamam um Service
backend/services/      # uma classe por ação/caso de uso
backend/models/        # exportação das entidades de domínio
backend/repositories/  # apenas consultas especiais; não duplica CRUD simples
frontend/              # documentação e fronteira do frontend
app/models/            # Models SQLAlchemy e persistência convencional
app/templates/         # páginas Jinja2
app/static/            # JavaScript e CSS que consomem as APIs
```

A geração do QR Code é a implementação de referência: o frontend chama
`POST /settings/whatsapp/qrcode`; `WhatsAppQrCodeController` interpreta a
requisição; `GenerateWhatsAppQrCodeService` executa somente esse caso de uso;
e `WhatsAppService` encapsula a comunicação HTTP com a Evolution API. Como o
acesso ao banco é uma consulta simples por empresa, não foi criado um
Repository redundante.

## Funcionalidades Implementadas

1. Cadastrar cliente
2. Listar clientes
3. Atualizar cliente
4. Arquivar cliente
5. Cadastrar produto
6. Listar produtos
7. Atualizar produto e suas variações
8. Arquivar produto
9. Registrar movimentação de estoque
10. Consultar histórico de movimentações de estoque

## Requisitos

- Python 3.12 ou superior;
- MySQL 8 ou superior;
- Redis 7 ou superior;
- uma conta e chave da Groq;
- Evolution API v2 acessível pelo backend, localmente ou em Docker;
- Docker com Compose v2, opcional para subir toda a infraestrutura.

## Instalação local

No PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

No Linux/macOS:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

Edite `.env` e troque todos os valores vazios ou de desenvolvimento. O arquivo
real `.env` contém segredos e não deve ser versionado.

## Configuração

Variáveis principais:

| Variável | Finalidade |
| --- | --- |
| `FLASK_ENV` | `development`, `testing` ou `production` |
| `SECRET_KEY` | Assinatura das sessões e tokens; use valor longo e aleatório |
| `CREDENTIAL_ENCRYPTION_KEY` | Chave Fernet para credenciais por tenant; gere e armazene separadamente |
| `DATABASE_URL` | URL SQLAlchemy do MySQL com driver PyMySQL |
| `REDIS_URL` | Broker e backend de resultados do Celery |
| `RATELIMIT_STORAGE_URI` | Redis compartilhado pelo rate limiter; vazio reutiliza `REDIS_URL` em produção |
| `OUTBOX_IMMEDIATE_DISPATCH` | Tenta publicar a task logo após o commit, sem substituir a garantia no banco |
| `OUTBOX_DISPATCH_INTERVAL_SECONDS` | Intervalo do Celery beat para recuperar tasks pendentes |
| `OUTBOX_BATCH_SIZE` | Máximo de registros recuperados por rodada do dispatcher |
| `AI_INBOUND_HOURLY_LIMIT` | Cota horária de mensagens recebidas por empresa antes de acionar IA |
| `AI_SENDER_MINUTE_LIMIT` | Cota por minuto para um mesmo remetente dentro da empresa |
| `GROQ_API_KEY` | Chave secreta usada somente pelo backend |
| `GROQ_MODEL` | Modelo habilitado na conta Groq |
| `GROQ_API_URL` | Base compatível com OpenAI da Groq, normalmente `https://api.groq.com/openai/v1` |
| `EVOLUTION_API_URL` | URL interna da Evolution API; no Compose use `http://evolution-api:8080` |
| `EVOLUTION_API_KEY` | Chave enviada somente pelo backend no cabeçalho `apikey` |
| `EVOLUTION_REQUEST_TIMEOUT` | Timeout das chamadas HTTP para a Evolution API |
| `EVOLUTION_WEBHOOK_URL` | Callback do AutoFlow acessível pelo contêiner da Evolution |
| `SMTP_HOST`, `SMTP_PORT` | Servidor SMTP usado pelo worker para recuperação de senha |
| `SMTP_USERNAME`, `SMTP_PASSWORD` | Credenciais SMTP; mantenha-as somente no backend |
| `MAIL_FROM` | Remetente dos e-mails transacionais |
| `APP_URL` | URL pública do painel, sem barra final |
| `LANDING_PAGE_URL` | URL de uma Landing Page externa opcional; por padrão, a página integrada responde em `/` |
| `CORS_ORIGINS` | Origens permitidas, separadas por vírgula |

Nunca exponha as chaves Groq, Evolution, banco, criptografia ou `SECRET_KEY` em templates,
JavaScript, logs ou imagens Docker.

Gere uma chave Fernet para `CREDENTIAL_ENCRYPTION_KEY` com:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Para rotacioná-la sem perder credenciais já cifradas, mantenha temporariamente
as chaves nova e antiga separadas por vírgula, com a nova primeiro; recifre os
segredos e então remova a antiga.

### MySQL

Crie um banco e um usuário com permissões limitadas ao banco AutoFlow. Uma
URL local típica é:

```env
DATABASE_URL=mysql+pymysql://autoflow:senha_forte@127.0.0.1:3306/autoflow?charset=utf8mb4
```

Use `utf8mb4` e mantenha backups antes de aplicar migrações em produção. O
SQLite existe apenas na configuração de testes; não substitui o MySQL do
produto.

### Redis e Celery

Para desenvolvimento, inicie o Redis localmente na porta `6379` e configure:

```env
REDIS_URL=redis://localhost:6379/0
```

O Redis atua como broker e backend do Celery. Não exponha a porta sem senha em
um servidor público. Cada intenção de task crítica é gravada antes no
transactional outbox, na mesma transação dos dados de negócio. A publicação
imediata é uma tentativa curta: se o Redis estiver indisponível, o webhook
continua podendo responder `200` depois do commit, e o Celery beat recupera a
linha pendente. Mantenha worker e beat ativos; o banco, não o broker, é a fonte
durável dessas intenções.

### Recuperação de senha por e-mail

Configure `SMTP_HOST`, `SMTP_PORT`, `MAIL_FROM` e, quando exigido pelo provedor,
`SMTP_USERNAME` e `SMTP_PASSWORD`. O endpoint de recuperação sempre responde de
forma genérica e persiste uma task assíncrona, inclusive um no-op equivalente
para endereços inexistentes. O link é construído exclusivamente a partir de
`APP_URL`; use a URL HTTPS pública correta em produção. O token em texto puro
não é devolvido pela API nem gravado em logs ou no outbox.

### Groq

Crie uma chave no console da Groq e defina `GROQ_API_KEY` e `GROQ_MODEL`. A
aplicação chama a API exclusivamente no backend. As tools consultam dados já
isolados pela empresa; o modelo nunca recebe credenciais nem executa SQL.

### WhatsApp via Evolution API

Configure `EVOLUTION_API_URL`, `EVOLUTION_API_KEY` e
`EVOLUTION_WEBHOOK_URL` no `.env`. No AutoFlow:

1. abra **Configurações → WhatsApp**;
2. salve um nome exclusivo para a instância;
3. gere o QR Code — se necessário, o AutoFlow cria a instância Evolution;
4. leia o QR Code pelo celular;
5. configure o callback `/webhooks/evolution` e habilite `MESSAGES_UPSERT`.

O endpoint persiste/idempotentiza o evento e enfileira o processamento. As
cotas por empresa e remetente são verificadas transacionalmente antes de criar
dados ou consumir capacidade da IA; excedentes recebem HTTP `429` com
`Retry-After`. Em desenvolvimento com Docker, o callback pode usar
`http://host.docker.internal:5000/webhooks/evolution`.

Para executar a Evolution separadamente, copie `.env.evolution.example` para
`.env.evolution` e use `docker compose -f docker-compose.evolution.yml up -d`.
No Compose combinado deste repositório, a aplicação usa automaticamente
`http://evolution-api:8080`; `http://localhost:8080` é a URL a ser aberta no
host e não deve ser usada entre contêineres.

## Migrações

Com o MySQL ativo e `.env` configurado:

```bash
flask --app "app:create_app()" db upgrade
```

Ao alterar modelos:

```bash
flask --app "app:create_app()" db migrate -m "descreva a alteracao"
flask --app "app:create_app()" db upgrade
```

Revise o arquivo gerado em `migrations/versions/`; a geração automática não
entende todos os renomes ou migrações de dados. Em produção, execute `upgrade`
uma vez antes de disponibilizar a nova versão da aplicação.

## Execução

Servidor Flask de desenvolvimento:

```bash
flask --app "app:create_app('development')" run --debug
```

Worker Celery, em outro terminal com o mesmo `.env`:

```bash
celery -A celery_worker.celery worker --loglevel=INFO
```

Agendador que recupera o outbox pendente, em um terceiro terminal:

```bash
celery -A celery_worker.celery beat --loglevel=INFO
```

Abra `http://localhost:5000`. O endpoint `GET /health` pode ser usado por
health checks.

## Docker Compose

Preencha `.env` e execute:

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f web worker beat
```

O Compose inicia MySQL, Redis, Flask/Gunicorn, um worker Celery e um Celery beat.
O serviço web aguarda os health checks, aplica `flask db upgrade` e então inicia
o Gunicorn. O beat republica periodicamente as tasks pendentes do outbox. Os
volumes nomeados preservam MySQL, Redis e imagens de produtos entre reinícios.

Para parar os contêineres sem apagar dados:

```bash
docker compose down
```

Não use `docker compose down -v` em um ambiente com dados que devam ser
preservados.

### Evolution API v2 (opcional)

O AutoFlow usa a Evolution API v2 para enviar e receber mensagens do WhatsApp.
Para subir a Evolution ao lado do SaaS, há uma stack isolada em
`docker-compose.evolution.yml`, com PostgreSQL, Redis e volumes próprios. Isso
evita compartilhar sessões, cache ou dados de mensageria com os serviços do
AutoFlow.

1. copie o arquivo de exemplo e substitua **todos** os segredos e URIs de exemplo:

   ```powershell
   Copy-Item .env.evolution.example .env.evolution
   ```

2. confira que `DATABASE_CONNECTION_URI` e `CACHE_REDIS_URI` possuem as mesmas
   senhas definidas no arquivo, codificadas para URL quando contiverem caracteres
   reservados (`@`, `:`, `/`, `?`, `#` etc.);
3. inicie a API juntamente com a infraestrutura principal:

   ```powershell
   docker compose -f docker-compose.yml -f docker-compose.evolution.yml up -d --build
   docker compose -f docker-compose.yml -f docker-compose.evolution.yml ps
   ```

Por padrão, a Evolution fica disponível somente em
`http://127.0.0.1:8080`. Para expô-la atrás de um proxy HTTPS, mantenha esse
bind local e configure a URL pública em `SERVER_URL` no `.env.evolution`; o
proxy deve restringir o acesso e não registrar o header `apikey`.

A imagem está fixada em `evoapicloud/evolution-api:v2.3.6`, a versão v2 mais
recente antes da exigência de ativação introduzida na v2.4. O endpoint e a
chave configurados em `.env` são usados pelo backend. Ao executar o Compose
combinado, o backend acessa a API por `http://evolution-api:8080` e a Evolution
entrega eventos em `http://web:5000/webhooks/evolution`; as URLs `localhost`
continuam sendo usadas somente pelo navegador e por processos executados no
host. Configure o evento `MESSAGES_UPSERT` na instância.

Referências: [instalação Docker da Evolution API v2](https://github.com/evolution-foundation/docs-evolution/blob/main/v2/en/install/docker.mdx)
e [release v2.3.6](https://github.com/evolution-foundation/evolution-api/releases/tag/2.3.6).

## Testes

A configuração `testing` usa a factory `create_app('testing')`, SQLite em
memória, Celery eager, CSRF e rate limiting desabilitados. Nenhuma API externa
deve ser chamada pela suíte.

```bash
pytest
pytest --cov=app --cov-report=term-missing
```

Os testes cobrem autenticação, isolamento multiempresa, clientes, produtos,
estoque, conversas, tools da IA, agendamentos e webhook do WhatsApp com mocks,
incluindo falha do broker e recuperação posterior do outbox.

## Deploy

Para um ambiente de produção:

1. publique uma imagem imutável e execute como usuário sem privilégios;
2. use MySQL e Redis gerenciados, privados, autenticados e com backup;
3. injete segredos por um cofre/secret manager, nunca pela imagem;
4. termine TLS em um proxy ou load balancer e encaminhe cabeçalhos seguros;
5. aplique as migrações uma única vez antes de escalar web e workers;
6. execute web e worker como serviços independentes e escaláveis e mantenha uma
   única instância do Celery beat por agenda;
7. limite CORS ao domínio real, habilite cookies seguros e rotacione tokens;
8. configure logs, métricas, alertas e health checks;
9. valide a chave da Evolution API e a idempotência do webhook;
10. rode a suíte de testes antes de promover a versão.

Exemplo de processo web fora do Compose:

```bash
gunicorn --workers 3 --threads 2 --timeout 90 --bind 0.0.0.0:5000 run:app
```

## Multi-tenancy e segurança

Dados empresariais pertencem a `Company` por `company_id`. O tenant vem do
usuário autenticado e nunca de um campo enviado pelo cliente. Consultas,
alterações e tools precisam aplicar esse filtro, inclusive para IDs válidos de
outra empresa. Senhas são armazenadas apenas como hash; formulários usam CSRF;
entradas são validadas; e operações sensíveis geram trilha de auditoria.

## Licença

Defina a licença do projeto antes da distribuição externa.
