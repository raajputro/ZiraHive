// Document scanning in the browser: find the paper, straighten it, clean it up.
// Plain canvas and typed arrays; nothing is sent anywhere until you press Save.

export interface Pt { x: number; y: number }
export type Filter = "color" | "enhance" | "gray" | "bw";

const MAX_SOURCE = 3000;   // longest side kept from the camera picture
const MAX_PAGE = 2480;     // longest side of the finished page (A4 at 300 dpi)

export async function loadPicture(file: Blob): Promise<HTMLCanvasElement> {
  const bmp = await createImageBitmap(file, { imageOrientation: "from-image" });
  const scale = Math.min(1, MAX_SOURCE / Math.max(bmp.width, bmp.height));
  const c = document.createElement("canvas");
  c.width = Math.round(bmp.width * scale);
  c.height = Math.round(bmp.height * scale);
  c.getContext("2d")!.drawImage(bmp, 0, 0, c.width, c.height);
  bmp.close();
  return c;
}

export function fullFrame(c: HTMLCanvasElement): Pt[] {
  const m = Math.round(Math.min(c.width, c.height) * 0.02);
  return [{ x: m, y: m }, { x: c.width - m, y: m }, { x: c.width - m, y: c.height - m }, { x: m, y: c.height - m }];
}

/** Corners of the paper (top-left, top-right, bottom-right, bottom-left), or the whole picture. */
export function detectCorners(src: HTMLCanvasElement): Pt[] {
  const scale = Math.min(1, 320 / Math.max(src.width, src.height));
  const w = Math.max(8, Math.round(src.width * scale)), h = Math.max(8, Math.round(src.height * scale));
  const small = document.createElement("canvas");
  small.width = w; small.height = h;
  const ctx = small.getContext("2d", { willReadFrequently: true })!;
  ctx.drawImage(src, 0, 0, w, h);
  const px = ctx.getImageData(0, 0, w, h).data;
  let gray = new Float32Array(w * h);
  for (let i = 0; i < w * h; i++) gray[i] = 0.299 * px[i * 4] + 0.587 * px[i * 4 + 1] + 0.114 * px[i * 4 + 2];
  for (let pass = 0; pass < 2; pass++) gray = boxBlur(gray, w, h, 2);

  // Otsu: the threshold that best splits bright paper from the background
  const hist = new Array(256).fill(0);
  for (const g of gray) hist[Math.min(255, Math.max(0, Math.round(g)))]++;
  let sum = 0;
  for (let i = 0; i < 256; i++) sum += i * hist[i];
  let sumB = 0, wB = 0, best = 0, threshold = 128;
  for (let t = 0; t < 256; t++) {
    wB += hist[t];
    if (!wB) continue;
    const wF = w * h - wB;
    if (!wF) break;
    sumB += t * hist[t];
    const mB = sumB / wB, mF = (sum - sumB) / wF;
    const between = wB * wF * (mB - mF) ** 2;
    if (between > best) { best = between; threshold = t; }
  }

  // the biggest connected bright area is the paper
  const label = new Int32Array(w * h).fill(-1);
  let bestArea = 0, bestLabel = -1, next = 0;
  const stack: number[] = [];
  for (let start = 0; start < w * h; start++) {
    if (label[start] !== -1 || gray[start] <= threshold) continue;
    let area = 0;
    label[start] = next;
    stack.push(start);
    while (stack.length) {
      const i = stack.pop()!;
      area++;
      const x = i % w, y = (i / w) | 0;
      for (const j of [x > 0 ? i - 1 : -1, x < w - 1 ? i + 1 : -1, y > 0 ? i - w : -1, y < h - 1 ? i + w : -1]) {
        if (j >= 0 && label[j] === -1 && gray[j] > threshold) { label[j] = next; stack.push(j); }
      }
    }
    if (area > bestArea) { bestArea = area; bestLabel = next; }
    next++;
  }
  const share = bestArea / (w * h);
  if (bestLabel < 0 || share < 0.12 || share > 0.97) return fullFrame(src);

  let tl = { s: Infinity, x: 0, y: 0 }, br = { s: -Infinity, x: 0, y: 0 };
  let tr = { s: -Infinity, x: 0, y: 0 }, bl = { s: -Infinity, x: 0, y: 0 };
  for (let i = 0; i < w * h; i++) {
    if (label[i] !== bestLabel) continue;
    const x = i % w, y = (i / w) | 0;
    if (x + y < tl.s) tl = { s: x + y, x, y };
    if (x + y > br.s) br = { s: x + y, x, y };
    if (x - y > tr.s) tr = { s: x - y, x, y };
    if (y - x > bl.s) bl = { s: y - x, x, y };
  }
  return [tl, tr, br, bl].map((p) => ({ x: p.x / scale, y: p.y / scale }));
}

function boxBlur(src: Float32Array, w: number, h: number, r: number): Float32Array {
  const tmp = new Float32Array(w * h), out = new Float32Array(w * h);
  for (let y = 0; y < h; y++) {
    let acc = 0;
    for (let x = -r; x <= r; x++) acc += src[y * w + Math.min(w - 1, Math.max(0, x))];
    for (let x = 0; x < w; x++) {
      tmp[y * w + x] = acc / (2 * r + 1);
      acc += src[y * w + Math.min(w - 1, x + r + 1)] - src[y * w + Math.max(0, x - r)];
    }
  }
  for (let x = 0; x < w; x++) {
    let acc = 0;
    for (let y = -r; y <= r; y++) acc += tmp[Math.min(h - 1, Math.max(0, y)) * w + x];
    for (let y = 0; y < h; y++) {
      out[y * w + x] = acc / (2 * r + 1);
      acc += tmp[Math.min(h - 1, y + r + 1) * w + x] - tmp[Math.max(0, y - r) * w + x];
    }
  }
  return out;
}

const dist = (a: Pt, b: Pt) => Math.hypot(a.x - b.x, a.y - b.y);

/** 3x3 matrix taking the 4 `from` points to the 4 `to` points. */
function homography(from: Pt[], to: Pt[]): number[] {
  const A: number[][] = [];
  for (let i = 0; i < 4; i++) {
    const { x, y } = from[i], { x: u, y: v } = to[i];
    A.push([x, y, 1, 0, 0, 0, -u * x, -u * y, u]);
    A.push([0, 0, 0, x, y, 1, -v * x, -v * y, v]);
  }
  for (let c = 0; c < 8; c++) {  // Gaussian elimination with partial pivoting
    let p = c;
    for (let r = c + 1; r < 8; r++) if (Math.abs(A[r][c]) > Math.abs(A[p][c])) p = r;
    [A[c], A[p]] = [A[p], A[c]];
    for (let r = 0; r < 8; r++) {
      if (r === c) continue;
      const f = A[r][c] / A[c][c];
      for (let k = c; k < 9; k++) A[r][k] -= f * A[c][k];
    }
  }
  return [...A.map((row, i) => row[8] / row[i]), 1];
}

/** The paper inside `corners`, straightened into a flat page. */
export function straighten(src: HTMLCanvasElement, corners: Pt[]): HTMLCanvasElement {
  const [tl, tr, br, bl] = corners;
  let W = Math.max(dist(tl, tr), dist(bl, br)), H = Math.max(dist(tl, bl), dist(tr, br));
  const k = Math.min(1, MAX_PAGE / Math.max(W, H));
  W = Math.max(1, Math.round(W * k)); H = Math.max(1, Math.round(H * k));
  const m = homography([{ x: 0, y: 0 }, { x: W, y: 0 }, { x: W, y: H }, { x: 0, y: H }], corners);
  const sctx = src.getContext("2d", { willReadFrequently: true })!;
  const sp = sctx.getImageData(0, 0, src.width, src.height).data;
  const sw = src.width, sh = src.height;
  const out = document.createElement("canvas");
  out.width = W; out.height = H;
  const octx = out.getContext("2d")!;
  const img = octx.createImageData(W, H);
  const op = img.data;
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      const d = m[6] * x + m[7] * y + m[8];
      const fx = (m[0] * x + m[1] * y + m[2]) / d, fy = (m[3] * x + m[4] * y + m[5]) / d;
      const x0 = Math.max(0, Math.min(sw - 2, Math.floor(fx))), y0 = Math.max(0, Math.min(sh - 2, Math.floor(fy)));
      const ax = Math.min(1, Math.max(0, fx - x0)), ay = Math.min(1, Math.max(0, fy - y0));
      const i00 = (y0 * sw + x0) * 4, i10 = i00 + 4, i01 = i00 + sw * 4, i11 = i01 + 4;
      const o = (y * W + x) * 4;
      for (let c = 0; c < 3; c++) {
        op[o + c] = (sp[i00 + c] * (1 - ax) + sp[i10 + c] * ax) * (1 - ay) + (sp[i01 + c] * (1 - ax) + sp[i11 + c] * ax) * ay;
      }
      op[o + 3] = 255;
    }
  }
  octx.putImageData(img, 0, 0);
  return out;
}

export function rotate(src: HTMLCanvasElement, quarterTurns: number): HTMLCanvasElement {
  const q = ((quarterTurns % 4) + 4) % 4;
  if (!q) return src;
  const c = document.createElement("canvas");
  c.width = q % 2 ? src.height : src.width;
  c.height = q % 2 ? src.width : src.height;
  const ctx = c.getContext("2d")!;
  ctx.translate(c.width / 2, c.height / 2);
  ctx.rotate((q * Math.PI) / 2);
  ctx.drawImage(src, -src.width / 2, -src.height / 2);
  return c;
}

/** Colour as is, auto-levels ("enhanced"), grey, or crisp black and white for text. */
export function applyFilter(src: HTMLCanvasElement, f: Filter): HTMLCanvasElement {
  if (f === "color") return src;
  const w = src.width, h = src.height;
  const c = document.createElement("canvas");
  c.width = w; c.height = h;
  const ctx = c.getContext("2d", { willReadFrequently: true })!;
  ctx.drawImage(src, 0, 0);
  const img = ctx.getImageData(0, 0, w, h);
  const p = img.data, n = w * h;
  if (f === "enhance") {
    for (let ch = 0; ch < 3; ch++) {
      const hist = new Uint32Array(256);
      for (let i = 0; i < n; i++) hist[p[i * 4 + ch]]++;
      let lo = 0, hi = 255, acc = 0;
      while (lo < 255 && (acc += hist[lo]) < n * 0.02) lo++;
      acc = 0;
      while (hi > 0 && (acc += hist[hi]) < n * 0.02) hi--;
      const span = Math.max(1, hi - lo);
      for (let i = 0; i < n; i++) p[i * 4 + ch] = Math.max(0, Math.min(255, ((p[i * 4 + ch] - lo) * 255) / span));
    }
  } else {
    const g = new Float32Array(n);
    for (let i = 0; i < n; i++) g[i] = 0.299 * p[i * 4] + 0.587 * p[i * 4 + 1] + 0.114 * p[i * 4 + 2];
    if (f === "bw") {
      // compare each pixel with its neighbourhood (integral image), so shadows don't turn black
      const I = new Float64Array((w + 1) * (h + 1));
      for (let y = 0; y < h; y++) {
        let row = 0;
        for (let x = 0; x < w; x++) { row += g[y * w + x]; I[(y + 1) * (w + 1) + x + 1] = I[y * (w + 1) + x + 1] + row; }
      }
      const r = Math.max(8, Math.round(Math.max(w, h) / 40));
      for (let y = 0; y < h; y++) {
        const y0 = Math.max(0, y - r), y1 = Math.min(h, y + r + 1);
        for (let x = 0; x < w; x++) {
          const x0 = Math.max(0, x - r), x1 = Math.min(w, x + r + 1);
          const mean = (I[y1 * (w + 1) + x1] - I[y0 * (w + 1) + x1] - I[y1 * (w + 1) + x0] + I[y0 * (w + 1) + x0]) / ((y1 - y0) * (x1 - x0));
          g[y * w + x] = g[y * w + x] < mean * 0.86 ? 0 : 255;
        }
      }
    }
    for (let i = 0; i < n; i++) p[i * 4] = p[i * 4 + 1] = p[i * 4 + 2] = g[i];
  }
  ctx.putImageData(img, 0, 0);
  return c;
}

export function toJpeg(c: HTMLCanvasElement, quality = 0.85): Promise<Blob> {
  return new Promise((res, rej) => c.toBlob((b) => (b ? res(b) : rej(new Error("encode"))), "image/jpeg", quality));
}
