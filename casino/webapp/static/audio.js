"use strict";
/* Звук и музыка на Web Audio (синтез, без файлов). window.Snd */
(function () {
  let ctx = null, master = null, musicGain = null, sfxGain = null;
  let musicOn = false, musicTimer = null, started = false;  // музыка по умолчанию выключена

  function init() {
    if (ctx) return;
    const AC = window.AudioContext || window.webkitAudioContext;
    ctx = new AC();
    master = ctx.createGain(); master.gain.value = 0.9; master.connect(ctx.destination);
    sfxGain = ctx.createGain(); sfxGain.gain.value = 0.9; sfxGain.connect(master);
    musicGain = ctx.createGain(); musicGain.gain.value = 0.18; musicGain.connect(master);
  }
  function unlock() {
    try {
      init();
      if (ctx.state === "suspended") ctx.resume();
      if (!started) { started = true; if (musicOn) playBg(); }
    } catch (e) {}
  }

  function tone(freq, t0, dur, type, gain, target) {
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.type = type || "square"; o.frequency.setValueAtTime(freq, t0);
    g.gain.setValueAtTime(0.0001, t0);
    g.gain.exponentialRampToValueAtTime(gain || 0.3, t0 + 0.01);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    o.connect(g); g.connect(target || sfxGain); o.start(t0); o.stop(t0 + dur + 0.02);
    return o;
  }
  function noise(t0, dur, gain, freq, q) {
    const n = ctx.sampleRate * dur, buf = ctx.createBuffer(1, n, ctx.sampleRate), d = buf.getChannelData(0);
    for (let i = 0; i < n; i++) d[i] = Math.random() * 2 - 1;
    const src = ctx.createBufferSource(); src.buffer = buf;
    const f = ctx.createBiquadFilter(); f.type = "bandpass"; f.frequency.value = freq || 1200; f.Q.value = q || 1;
    const g = ctx.createGain(); g.gain.setValueAtTime(gain || 0.2, t0);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    src.connect(f); f.connect(g); g.connect(sfxGain); src.start(t0); src.stop(t0 + dur);
  }

  const Snd = {
    unlock,
    spin() { if (!ctx) return; const t = ctx.currentTime; noise(t, 0.5, 0.12, 800, 0.7); tone(180, t, 0.4, "sawtooth", 0.08); },
    reelStop() { if (!ctx) return; const t = ctx.currentTime; tone(320, t, 0.08, "square", 0.25); noise(t, 0.05, 0.15, 2500, 2); },
    click() { if (!ctx) return; tone(700, ctx.currentTime, 0.05, "square", 0.18); },
    cascade() { if (!ctx) return; const t = ctx.currentTime; tone(500, t, 0.12, "triangle", 0.2); noise(t, 0.12, 0.1, 1500, 1); },
    multUp(level) { if (!ctx) return; const t = ctx.currentTime; const base = 400 + (level || 0) * 80; tone(base, t, 0.1, "square", 0.22); tone(base * 1.5, t + 0.06, 0.12, "square", 0.2); },
    win(level) {
      if (!ctx) return; const t = ctx.currentTime;
      const notes = [523, 659, 784, 1047, 1319]; const k = Math.min(level || 1, 5);
      for (let i = 0; i < k + 1; i++) tone(notes[i % notes.length], t + i * 0.07, 0.18, "square", 0.22);
    },
    bigwin() {
      if (!ctx) return; const t = ctx.currentTime;
      const seq = [523, 659, 784, 1047, 784, 1047, 1319, 1568];
      seq.forEach((f, i) => {
        tone(f, t + i * 0.11, 0.26, "square", 0.26);
        tone(f / 2, t + i * 0.11, 0.26, "triangle", 0.12);
      });
      const end = t + seq.length * 0.11;            // финальный аккорд + блеск
      [784, 1047, 1319, 1568].forEach((f) => tone(f, end, 0.7, "triangle", 0.18));
      for (let i = 0; i < 5; i++) tone(2000 + i * 300, end + 0.1 + i * 0.05, 0.12, "sine", 0.1);
    },
    bonus() {
      if (!ctx) return; const t = ctx.currentTime;
      const seq = [392, 523, 659, 784, 1047];
      seq.forEach((f, i) => tone(f, t + i * 0.12, 0.3, "sawtooth", 0.2));
    },
    lose() { if (!ctx) return; const t = ctx.currentTime; tone(200, t, 0.2, "sawtooth", 0.15); tone(150, t + 0.12, 0.25, "sawtooth", 0.13); },
    toggleMusic() {
      musicOn = !musicOn;
      if (musicOn) playBg(); else stopBg();
      return musicOn;
    },
    musicEnabled() { return musicOn; },
    setTrack() { /* одна песня на всех экранах — переключать нечего */ },
    baa() { try { const a = new Audio("/static/sfx/baa.mp3?v=19"); a.volume = 0.85; a.play().catch(function () {}); } catch (e) {} },
    hoofStart() { if (!ctx || hoofTimer) return; hoofStep = 0; hoofTimer = setInterval(hoofTick, 120); },
    hoofStop() { if (hoofTimer) { clearInterval(hoofTimer); hoofTimer = null; } },
  };

  // --- Единая фоновая музыка: песня «Рамин-баран» на всех экранах ---
  let bgAudio = null;
  const BG_SRC = "/static/music/ramin.mp3?v=19";
  function playBg() {
    if (!bgAudio) { bgAudio = new Audio(); bgAudio.loop = true; bgAudio.volume = 0.5; }
    if (bgAudio.src.indexOf(BG_SRC) < 0) bgAudio.src = BG_SRC;
    bgAudio.play().catch(function () {});
  }
  function stopBg() { if (bgAudio) { try { bgAudio.pause(); } catch (e) {} } }

  // --- Топот копыт (синтез): галоп, пока баран бежит ---
  let hoofTimer = null, hoofStep = 0;
  const HOOF = [1, 1, 0, 1, 0, 0];
  function hoofTick() {
    try {
      if (!ctx || ctx.state !== "running") return;
      if (HOOF[hoofStep % HOOF.length]) {
        const t = ctx.currentTime;
        tone(90, t, 0.06, "sine", 0.16); noise(t, 0.045, 0.1, 280, 1.2);
      }
      hoofStep++;
    } catch (e) {}
  }

  window.Snd = Snd;
})();
