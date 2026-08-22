# Frontend

O frontend do AutoFlow é server-rendered e permanece integrado ao Flask:

- templates: `app/templates/`;
- estilos: `app/static/css/`;
- JavaScript: `app/static/js/`.

A tela `app/templates/settings/whatsapp.html` consome a API
`POST /settings/whatsapp/qrcode` por `fetch`, implementado em
`app/static/js/app.js`. O QR Code nunca é incluído no HTML inicial e é obtido
somente por um usuário autenticado com perfil `ADMIN` ou `OWNER`.
