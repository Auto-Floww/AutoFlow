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

- Python 3.12, Flask e Blueprints, usando application factory;
- SQLAlchemy e Flask-Migrate/Alembic sobre MySQL 8;
- Flask-Login, CSRF, CORS, rate limiting e isolamento por `company_id`;
- templates Jinja2 e assets HTML5/CSS3/JavaScript ES6+;
- Groq API para IA e tool calling, sem acesso direto da IA ao banco;
- WhatsApp Cloud API oficial da Meta;
- Celery, Redis e transactional outbox para processamento assíncrono durável;
- Pytest com SQLite em memória para testes isolados;
- Gunicorn e Docker Compose para execução em contêineres.

O fluxo principal responde rapidamente ao webhook e transfere o trabalho
demorado ao worker:

```text
WhatsApp -> Flask webhook -> banco + outbox -> Celery -> Groq/tools -> WhatsApp
```

## Requisitos

- Python 3.12 ou superior;
- MySQL 8 ou superior;
- Redis 7 ou superior;
- uma conta e chave da Groq;
- um aplicativo da Meta com WhatsApp Cloud API, para integração real;
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
| `WHATSAPP_ACCESS_TOKEN` | Token da WhatsApp Cloud API |
| `WHATSAPP_PHONE_NUMBER_ID` | ID do número remetente na Meta |
| `WHATSAPP_BUSINESS_ACCOUNT_ID` | ID da conta WhatsApp Business |
| `WHATSAPP_VERIFY_TOKEN` | Valor definido por você para validar o webhook |
| `WHATSAPP_APP_SECRET` | App secret usado para verificar a assinatura dos POSTs |
| `META_GRAPH_VERSION` | Versão da Graph API usada pelo serviço |
| `SMTP_HOST`, `SMTP_PORT` | Servidor SMTP usado pelo worker para recuperação de senha |
| `SMTP_USERNAME`, `SMTP_PASSWORD` | Credenciais SMTP; mantenha-as somente no backend |
| `MAIL_FROM` | Remetente dos e-mails transacionais |
| `APP_URL` | URL pública do painel, sem barra final |
| `LANDING_PAGE_URL` | URL da Landing Page externa, quando fornecida |
| `CORS_ORIGINS` | Origens permitidas, separadas por vírgula |

Nunca exponha as chaves Groq, Meta, banco, criptografia ou `SECRET_KEY` em templates,
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

### WhatsApp Cloud API

No painel da Meta:

1. adicione o produto WhatsApp ao aplicativo;
2. configure o número, o access token e os IDs no `.env`;
3. escolha um `WHATSAPP_VERIFY_TOKEN` secreto;
4. publique `https://seu-dominio/webhooks/whatsapp` como callback;
5. assine os campos de mensagens e teste a verificação `GET`;
6. configure `WHATSAPP_APP_SECRET` para validar `X-Hub-Signature-256` nos POSTs.

O endpoint persiste/idempotentiza o evento e enfileira o processamento. As
cotas por empresa e remetente são verificadas transacionalmente antes de criar
dados ou consumir capacidade da IA; excedentes recebem HTTP `429` com
`Retry-After`. Em
desenvolvimento, a Meta precisa alcançar uma URL HTTPS pública; use um túnel
somente em ambiente controlado.

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
9. valide assinatura e idempotência do webhook da Meta;
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
