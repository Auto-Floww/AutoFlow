# Arquitetura da aplicação

O AutoFlow usa uma separação em camadas orientada a casos de uso. A direção das
dependências é sempre:

```text
HTTP -> Routes -> Controllers -> Services -> Models -> Banco
                                  |
                                  +-> gateways externos (Groq, SMTP, Evolution)
```

## Responsabilidade de cada camada

### `app/routes`

Contém somente módulos finos de registro e compatibilidade dos Blueprints. Não
há regra de negócio nem acesso ao banco nessa pasta. Os handlers registrados
pertencem às classes em `app/controllers`.

### `app/controllers`

Interpreta `request`, autenticação e autorização; converte dados HTTP; chama o
caso de uso apropriado; e transforma o retorno ou um `DomainError` em resposta
HTML/JSON. Cada domínio tem sua classe Controller e mantém os nomes históricos
dos endpoints para não quebrar templates nem clientes da API.

### `app/services/<dominio>`

Cada funcionalidade é uma classe própria, declarada em um único arquivo e com
um único ponto de entrada público chamado `execute()`. Casos de uso do mesmo
domínio ficam juntos. Exemplo:

```text
app/services/products/
  create_product_service.py       # CreateProductService.execute(...)
  list_products_service.py        # ListProductsService.execute(...)
  update_product_service.py       # UpdateProductService.execute(...)
  archive_product_service.py      # ArchiveProductService.execute(...)
```

Um Service recebe dados já extraídos do protocolo HTTP, aplica a regra de
negócio, coordena Models e gateways e define o limite transacional. Ele não lê
`request`, não renderiza templates e não cria respostas Flask.

### `app/models`

As entidades SQLAlchemy mantêm a persistência básica pelo `CrudMixin`. Todas
expõem o mesmo contrato:

- criação: `criar()` / `create()`;
- persistência: `salvar()` / `save()`;
- leitura: `buscar_por_id()` / `get_by_id()` e `listar_todos()` / `get_all()`;
- alteração: `atualizar()` / `update()`;
- remoção: `deletar()` / `delete()`.

`id`, `company_id`, `created_at` e `updated_at` não podem ser alterados por
mass assignment. Em entidades multiempresa, casos de uso devem usar
`for_company`, `get_for_company` ou `tenant_get`; os métodos globais de leitura
existem para o contrato CRUD, mas não substituem a barreira de tenant.

Arquivamento funcional (`is_active=False`, `status=INACTIVE` etc.) deve ser
feito pelo Service específico. `delete()` é remoção física e só deve ser usado
quando a regra do domínio realmente permitir.

## Transações

Operações compostas chamam CRUD com `commit=False` e confirmam uma única vez ao
final do caso de uso. Isso preserva atomicidade em fluxos como produto +
variantes + estoque, mensagem + outbox e agendamento + notificação.

## Regras para novas funcionalidades

1. Criar uma classe `NomeDoCasoService` em
   `app/services/<dominio>/nome_do_caso_service.py`.
2. Expor a funcionalidade por `execute()`; não acrescentar outra ação pública à
   mesma classe.
3. Chamar o Service a partir de um método do Controller do domínio.
4. Manter o módulo de rota limitado ao wiring do Blueprint.
5. Usar os métodos CRUD da Model e consultas sempre delimitadas por tenant.
6. Adicionar testes de comportamento e manter os contratos estruturais em
   `tests/test_model_crud.py` e `tests/test_service_structure.py`.

Não existe um segundo pacote `backend`: toda a aplicação Python reside sob
`app`, evitando duas árvores concorrentes para o mesmo sistema.
