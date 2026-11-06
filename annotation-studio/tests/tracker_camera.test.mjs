// The camera estimate behind "the box follows the camera zoom": a real zoom is measured, a pan is not a zoom, and
// water moving in different directions (live 0112: breaking waves on a static shot shrank the box ~1.5% per step)
// is not taken for a zoom.
import test from 'node:test';
import assert from 'node:assert/strict';
import { _camera } from '../web/js/tracker.js';
const { cameraMotion, smallGray } = _camera;
const W = 320, H = 180;
const tex = (x, y) => 60 * Math.sin(x * 0.21 + Math.sin(y * 0.05) * 3) + 50 * Math.sin(y * 0.17 + x * 0.03) + 30 * Math.sin((x + y) * 0.11);
const frame = fn => { const f = new Float32Array(W * H); for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) f[y * W + x] = 128 + fn(x, y); return f; };
const A = frame(tex);

test('a real zoom of the whole picture is measured', () => {
  const B = frame((x, y) => tex((x - W / 2) / 1.02 + W / 2, (y - H / 2) / 1.02 + H / 2));   // zoomed in 2%
  const m = cameraMotion(smallGray(A, W, H), smallGray(B, W, H));
  assert.ok(m && Math.abs(m.s - 1.02) < 0.006, `scale ${m?.s}`);
});

test('a pan is not a zoom', () => {
  const B = frame((x, y) => tex(x + 4, y - 2));
  const m = cameraMotion(smallGray(A, W, H), smallGray(B, W, H));
  assert.ok(m && Math.abs(m.s - 1) < 0.004, `scale ${m?.s}`);
});

test('water moving apart (left half one way, right half the other) is not taken for a zoom', () => {
  const B = frame((x, y) => x < W / 2 ? tex(x + 4, y) : tex(x - 4, y));   // looks like a zoom-out to a whole-picture fit
  const m = cameraMotion(smallGray(A, W, H), smallGray(B, W, H));
  assert.ok(!m || m.s === 1 || Math.abs(m.s - 1) < 0.002, `scale ${m?.s} must not be a zoom`);
});
