import * as THREE from "three";

const W = 512;
const H = 1108;
const FONT = '"Segoe UI", Roboto, Helvetica, Arial, sans-serif';

const BG = "#0b141a";
const HEADER_BG = "#1f2c34";
const IN_BG = "#202c33";
const OUT_BG = "#005c4b";
const TEXT_CLR = "#e9edef";
const MUTED_CLR = "#8696a0";
const ACCENT_CLR = "#25d366";
const INPUT_BG_CLR = "#2a3942";
const BORDER_CLR = "#233138";

const STATUS_H = 42;
const HEADER_H = 58;
const TOP = STATUS_H + HEADER_H;
const INPUT_H = 56;

const MESSAGES = [
  { dir: "in", text: "Boa noite. Quero um notebook de até R$ 5.000. Você recomenda algum?", time: "21:42" },
  { dir: "out", text: "Boa noite. Para esse valor, recomendo o IdeaPad Slim i5.", time: "21:42" },
  { dir: "out", text: "Ele tem Intel i5, 16 GB de RAM, SSD de 512 GB e tela de 15,6\". Está por R$ 4.799.", time: "21:43" },
  { dir: "in", text: "Serve para estudar e trabalhar com várias abas abertas?", time: "21:43" },
  { dir: "out", text: "Serve, sim. Os 16 GB de RAM ajudam com navegador, planilhas, chamadas de vídeo e estudos.", time: "21:44" },
  { dir: "in", text: "Tem em estoque? Entrega hoje no Centro?", time: "21:44" },
  { dir: "out", text: "Temos 3 unidades em estoque. Para o Centro, entregamos hoje até as 18h, com frete de R$ 12,00.", time: "21:45" },
  { dir: "out", text: "Se preferir retirar, consigo reservar para retirada na loja às 16h.", time: "21:45" },
];

const roundRect = (ctx, x, y, w, h, r) => {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + w - r, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + r);
  ctx.lineTo(x + w, y + h - r);
  ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  ctx.lineTo(x + r, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
};

const wrapText = (ctx, text, maxW) => {
  const words = text.split(" ");
  const lines = [];
  let line = words[0] || "";
  for (let i = 1; i < words.length; i++) {
    const test = line + " " + words[i];
    if (ctx.measureText(test).width <= maxW) {
      line = test;
    } else {
      lines.push(line);
      line = words[i];
    }
  }
  if (line) lines.push(line);
  return lines;
};

const drawSplash = (ctx) => {
  ctx.fillStyle = BG;
  ctx.fillRect(0, 0, W, H);
  ctx.save();
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.font = `bold 44px ${FONT}`;
  ctx.fillStyle = TEXT_CLR;
  ctx.globalAlpha = 0.6;
  ctx.fillText("AutoFlow", W / 2, H / 2 - 18);
  ctx.font = `18px ${FONT}`;
  ctx.fillStyle = ACCENT_CLR;
  ctx.globalAlpha = 0.4;
  ctx.fillText("Assistente IA", W / 2, H / 2 + 26);
  ctx.restore();
};

const drawStatusBar = (ctx) => {
  ctx.fillStyle = HEADER_BG;
  ctx.fillRect(0, 0, W, STATUS_H);
  ctx.font = `600 17px ${FONT}`;
  ctx.fillStyle = TEXT_CLR;
  ctx.textBaseline = "middle";
  ctx.textAlign = "left";
  ctx.fillText("9:41", 20, STATUS_H / 2);
  ctx.textAlign = "right";
  ctx.fillText("100%", W - 20, STATUS_H / 2);
  ctx.textAlign = "left";
  ctx.textBaseline = "alphabetic";
};

const drawHeader = (ctx) => {
  ctx.fillStyle = HEADER_BG;
  ctx.fillRect(0, STATUS_H, W, HEADER_H);
  ctx.fillStyle = BORDER_CLR;
  ctx.fillRect(0, TOP - 1, W, 1);

  const cy = STATUS_H + HEADER_H / 2;

  ctx.fillStyle = ACCENT_CLR;
  ctx.font = `bold 24px ${FONT}`;
  ctx.textBaseline = "middle";
  ctx.fillText("\u2039", 12, cy);

  const ax = 50;
  const ar = 17;
  ctx.beginPath();
  ctx.arc(ax, cy, ar, 0, Math.PI * 2);
  ctx.fillStyle = ACCENT_CLR;
  ctx.fill();
  ctx.fillStyle = "#fff";
  ctx.font = `bold 13px ${FONT}`;
  ctx.textAlign = "center";
  ctx.fillText("AF", ax, cy + 1);
  ctx.textAlign = "left";

  ctx.fillStyle = TEXT_CLR;
  ctx.font = `bold 19px ${FONT}`;
  ctx.fillText("AutoFlow", 76, cy - 8);

  ctx.fillStyle = MUTED_CLR;
  ctx.font = `14px ${FONT}`;
  ctx.fillText("Assistente online", 76, cy + 12);
  ctx.textBaseline = "alphabetic";
};

const drawMessages = (ctx, opacities) => {
  const pad = 14;
  const bPad = 12;
  const maxBW = W * 0.78;
  const fontSize = 20;
  const lineH = 27;
  const timeFS = 13;
  const timeH = 18;
  const gap = 5;
  let y = TOP + 12;

  for (let i = 0; i < MESSAGES.length; i++) {
    const op = opacities[i];
    if (op <= 0) continue;

    const msg = MESSAGES[i];
    const isOut = msg.dir === "out";

    ctx.save();
    ctx.globalAlpha = op;
    ctx.font = `${fontSize}px ${FONT}`;

    const textMaxW = maxBW - bPad * 2 - 6;
    const lines = wrapText(ctx, msg.text, textMaxW);
    const widths = lines.map((l) => ctx.measureText(l).width);
    const maxLW = Math.max(...widths);
    const bw = Math.min(maxBW, maxLW + bPad * 2 + 8);
    const bh = lines.length * lineH + timeH + bPad * 2 - 2;
    const bx = isOut ? W - pad - bw : pad;

    roundRect(ctx, bx, y, bw, bh, 10);
    ctx.fillStyle = isOut ? OUT_BG : IN_BG;
    ctx.fill();

    ctx.fillStyle = TEXT_CLR;
    ctx.font = `${fontSize}px ${FONT}`;
    for (let li = 0; li < lines.length; li++) {
      ctx.fillText(lines[li], bx + bPad, y + bPad + (li + 1) * lineH - 5);
    }

    ctx.fillStyle = MUTED_CLR;
    ctx.font = `${timeFS}px ${FONT}`;
    ctx.textAlign = "right";
    ctx.fillText(msg.time, bx + bw - bPad, y + bh - bPad + 2);
    ctx.textAlign = "left";

    ctx.restore();
    y += bh + gap;
  }
};

const drawInputBar = (ctx) => {
  const barY = H - INPUT_H;

  ctx.fillStyle = HEADER_BG;
  ctx.fillRect(0, barY, W, INPUT_H);
  ctx.fillStyle = BORDER_CLR;
  ctx.fillRect(0, barY, W, 1);

  ctx.fillStyle = MUTED_CLR;
  ctx.font = `26px ${FONT}`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText("+", 28, barY + INPUT_H / 2);

  roundRect(ctx, 52, barY + 10, W - 108, 36, 18);
  ctx.fillStyle = INPUT_BG_CLR;
  ctx.fill();

  ctx.fillStyle = MUTED_CLR;
  ctx.font = `15px ${FONT}`;
  ctx.textAlign = "left";
  ctx.fillText("Mensagem", 70, barY + INPUT_H / 2 + 1);

  ctx.beginPath();
  ctx.arc(W - 30, barY + INPUT_H / 2, 14, 0, Math.PI * 2);
  ctx.fillStyle = ACCENT_CLR;
  ctx.fill();

  ctx.textAlign = "left";
  ctx.textBaseline = "alphabetic";
};

const draw = (ctx, showChat, opacities) => {
  ctx.clearRect(0, 0, W, H);

  if (!showChat) {
    drawSplash(ctx);
    return;
  }

  ctx.fillStyle = BG;
  ctx.fillRect(0, 0, W, H);
  drawStatusBar(ctx);
  drawHeader(ctx);
  drawMessages(ctx, opacities);
  drawInputBar(ctx);
};

export const createScreenTexture = () => {
  const canvas = document.createElement("canvas");
  canvas.width = W;
  canvas.height = H;
  const ctx = canvas.getContext("2d");

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.flipY = false;
  texture.minFilter = THREE.LinearFilter;
  texture.magFilter = THREE.LinearFilter;

  let lastKey = "";

  draw(ctx, false, new Array(MESSAGES.length).fill(0));

  return {
    texture,
    messageCount: MESSAGES.length,
    update(showChat, opacities) {
      const key = (showChat ? 1 : 0) + "|" + opacities.map((v) => (v * 50) | 0).join(",");
      if (key === lastKey) return false;
      lastKey = key;
      draw(ctx, showChat, opacities);
      texture.needsUpdate = true;
      return true;
    },
  };
};
