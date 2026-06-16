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
      if (!started) { started = true; if (musicOn) startMusic(); }
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
      const seq = [523, 659, 784, 1047, 784, 1047, 1319];
      seq.forEach((f, i) => { tone(f, t + i * 0.1, 0.25, "square", 0.25); tone(f / 2, t + i * 0.1, 0.25, "triangle", 0.12); });
    },
    bonus() {
      if (!ctx) return; const t = ctx.currentTime;
      const seq = [392, 523, 659, 784, 1047];
      seq.forEach((f, i) => tone(f, t + i * 0.12, 0.3, "sawtooth", 0.2));
    },
    lose() { if (!ctx) return; const t = ctx.currentTime; tone(200, t, 0.2, "sawtooth", 0.15); tone(150, t + 0.12, 0.25, "sawtooth", 0.13); },
    toggleMusic() {
      musicOn = !musicOn;
      if (musicOn) { if (started) startMusic(); } else stopMusic();
      return musicOn;
    },
    musicEnabled() { return musicOn; },
  };

  // Простой зацикленный мотив в стиле вестерна.
  const MELODY = [330, 0, 392, 440, 0, 392, 330, 0, 294, 0, 330, 392, 0, 440, 392, 0];
  const BASS = [110, 110, 165, 165, 147, 147, 110, 110];
  let step = 0;
  function startMusic() {
    stopMusic();
    const beat = 0.28;
    musicTimer = setInterval(() => {
      try {
        if (!ctx || ctx.state !== "running") return;
        const t = ctx.currentTime + 0.02;
        const n = MELODY[step % MELODY.length];
        if (n) tone(n, t, beat * 0.9, "triangle", 0.16, musicGain);
        const b = BASS[Math.floor(step / 2) % BASS.length];
        if (step % 2 === 0) tone(b, t, beat * 1.6, "sawtooth", 0.1, musicGain);
        step++;
      } catch (e) { stopMusic(); }
    }, beat * 1000);
  }
  function stopMusic() { if (musicTimer) { clearInterval(musicTimer); musicTimer = null; } }

  window.Snd = Snd;
})();
