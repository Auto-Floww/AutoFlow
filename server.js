const crypto = require("crypto");
const path = require("path");

require("dotenv").config({ path: path.join(__dirname, ".env") });

const bcrypt = require("bcryptjs");
const express = require("express");
const mysql = require("mysql2/promise");

const app = express();
const port = Number(process.env.PORT || 3000);
const cookieName = "autoflow_session";
const skipAuth = ["true", "1", "yes"].includes(
  String(process.env.SKIP_AUTH || "").trim().toLowerCase()
);
const demoUser = {
  id: 1,
  nome: "Usuario Teste",
  email: "teste@autoflow.local",
  empresa: "AutoFlow Demo",
};

const db = mysql.createPool({
  host: process.env.DB_HOST || "localhost",
  port: Number(process.env.DB_PORT || 3306),
  user: process.env.DB_USER || "root",
  password: process.env.DB_PASSWORD || "",
  database: process.env.DB_NAME || "autoflow",
  waitForConnections: true,
  connectionLimit: 10,
  namedPlaceholders: true,
});

const isProduction = process.env.NODE_ENV === "production";
const eightHours = 1000 * 60 * 60 * 8;
const thirtyDays = 1000 * 60 * 60 * 24 * 30;
const sessionDurations = {
  default: eightHours,
  remember: thirtyDays,
};

function normalizeEmail(email) {
  return String(email || "").trim().toLowerCase();
}

function isValidEmail(email) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}

function hashToken(token) {
  return crypto.createHash("sha256").update(token).digest("hex");
}

function parseCookies(header = "") {
  return header.split(";").reduce((cookies, item) => {
    const [rawName, ...rawValue] = item.trim().split("=");
    if (!rawName) return cookies;
    cookies[rawName] = decodeURIComponent(rawValue.join("="));
    return cookies;
  }, {});
}

function getSessionToken(req) {
  return parseCookies(req.headers.cookie || "")[cookieName];
}

function publicUser(user) {
  return {
    id: user.id,
    nome: user.nome,
    email: user.email,
    empresa: user.empresa,
  };
}

async function findUserBySession(req) {
  if (skipAuth) return demoUser;

  const token = getSessionToken(req);
  if (!token) return null;

  const tokenHash = hashToken(token);
  const [rows] = await db.execute(
    `SELECT u.id, u.nome, u.email, u.empresa
       FROM sessoes_login s
       JOIN usuarios u ON u.id = s.usuario_id
      WHERE s.token_hash = :tokenHash
        AND s.expira_em > NOW()
        AND u.ativo = 1
      LIMIT 1`,
    { tokenHash }
  );

  if (!rows.length) return null;

  await db.execute(
    "UPDATE sessoes_login SET ultimo_uso_em = NOW() WHERE token_hash = :tokenHash",
    { tokenHash }
  );

  return rows[0];
}

function setSessionCookie(res, token, remember) {
  const options = {
    httpOnly: true,
    sameSite: "lax",
    secure: isProduction,
    path: "/",
  };

  if (remember) {
    options.maxAge = thirtyDays;
  }

  res.cookie(cookieName, token, options);
}

function clearSessionCookie(res) {
  res.clearCookie(cookieName, {
    httpOnly: true,
    sameSite: "lax",
    secure: isProduction,
    path: "/",
  });
}

async function createSession(res, userId, remember = false) {
  const token = crypto.randomBytes(32).toString("hex");
  const tokenHash = hashToken(token);
  const sessionDuration = remember ? sessionDurations.remember : sessionDurations.default;
  const expiresAt = new Date(Date.now() + sessionDuration);

  await db.execute(
    `INSERT INTO sessoes_login (usuario_id, token_hash, expira_em)
     VALUES (:usuarioId, :tokenHash, :expiresAt)`,
    {
      usuarioId: userId,
      tokenHash,
      expiresAt,
    }
  );

  setSessionCookie(res, token, remember);
  return expiresAt;
}

app.use(express.json());

app.post("/api/register", async (req, res) => {
  if (skipAuth) {
    return res.status(201).json({
      user: publicUser(demoUser),
      remember: true,
      expiresAt: new Date(Date.now() + thirtyDays).toISOString(),
      demo: true,
    });
  }

  const nome = String(req.body.nome || "").trim();
  const empresa = String(req.body.empresa || "").trim() || null;
  const email = normalizeEmail(req.body.email);
  const senha = String(req.body.senha || "");

  if (!nome || !email || !senha) {
    return res.status(400).json({ message: "Informe nome, e-mail e senha." });
  }

  if (nome.length < 2) {
    return res.status(400).json({ message: "Informe um nome valido." });
  }

  if (!isValidEmail(email)) {
    return res.status(400).json({ message: "Informe um e-mail valido." });
  }

  if (senha.length < 6) {
    return res.status(400).json({ message: "A senha precisa ter pelo menos 6 caracteres." });
  }

  try {
    const senhaHash = await bcrypt.hash(senha, 12);
    const [result] = await db.execute(
      `INSERT INTO usuarios (nome, email, senha_hash, empresa)
       VALUES (:nome, :email, :senhaHash, :empresa)`,
      {
        nome,
        email,
        senhaHash,
        empresa,
      }
    );

    const user = {
      id: result.insertId,
      nome,
      email,
      empresa,
    };
    const expiresAt = await createSession(res, user.id, true);

    return res.status(201).json({
      user: publicUser(user),
      remember: true,
      expiresAt: expiresAt.toISOString(),
    });
  } catch (error) {
    if (error && error.code === "ER_DUP_ENTRY") {
      return res.status(409).json({ message: "Este e-mail ja esta cadastrado." });
    }

    console.error("Register error:", error);
    return res.status(500).json({ message: "Nao foi possivel criar a conta agora." });
  }
});

app.post("/api/login", async (req, res) => {
  if (skipAuth) {
    return res.json({
      user: publicUser(demoUser),
      remember: true,
      expiresAt: new Date(Date.now() + thirtyDays).toISOString(),
      demo: true,
    });
  }

  const email = normalizeEmail(req.body.email);
  const senha = String(req.body.senha || "");
  const lembrar = Boolean(req.body.lembrar);

  if (!email || !senha) {
    return res.status(400).json({ message: "Informe e-mail e senha." });
  }

  try {
    const [users] = await db.execute(
      `SELECT id, nome, email, empresa, senha_hash
         FROM usuarios
        WHERE email = :email
          AND ativo = 1
        LIMIT 1`,
      { email }
    );

    const user = users[0];
    const validPassword = user && (await bcrypt.compare(senha, user.senha_hash));

    if (!validPassword) {
      return res.status(401).json({ message: "E-mail ou senha invalidos." });
    }

    const expiresAt = await createSession(res, user.id, lembrar);
    return res.json({
      user: publicUser(user),
      remember: lembrar,
      expiresAt: expiresAt.toISOString(),
    });
  } catch (error) {
    console.error("Login error:", error);
    return res.status(500).json({ message: "Nao foi possivel entrar agora." });
  }
});

app.get("/api/me", async (req, res) => {
  try {
    const user = await findUserBySession(req);
    if (!user) {
      return res.status(401).json({ message: "Sessao expirada." });
    }

    return res.json({ user: publicUser(user) });
  } catch (error) {
    console.error("Session check error:", error);
    return res.status(500).json({ message: "Nao foi possivel verificar a sessao." });
  }
});

app.post("/api/logout", async (req, res) => {
  if (skipAuth) {
    clearSessionCookie(res);
    return res.json({ ok: true, demo: true });
  }

  const token = getSessionToken(req);

  try {
    if (token) {
      await db.execute("DELETE FROM sessoes_login WHERE token_hash = :tokenHash", {
        tokenHash: hashToken(token),
      });
    }

    clearSessionCookie(res);
    return res.json({ ok: true });
  } catch (error) {
    console.error("Logout error:", error);
    clearSessionCookie(res);
    return res.status(500).json({ message: "Nao foi possivel sair agora." });
  }
});

app.get("/dashboard.html", async (req, res) => {
  try {
    const user = await findUserBySession(req);
    if (!user) {
      return res.redirect("/login.html");
    }

    return res.sendFile(path.join(__dirname, "dashboard.html"));
  } catch (error) {
    console.error("Dashboard auth error:", error);
    return res.status(500).send("Nao foi possivel abrir o painel agora.");
  }
});

app.use(express.static(__dirname));

app.get("*", (req, res) => {
  res.sendFile(path.join(__dirname, "index.html"));
});

app.listen(port, () => {
  console.log(`AutoFlow rodando em http://localhost:${port}`);
});

module.exports = app;
