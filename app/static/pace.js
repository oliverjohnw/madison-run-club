// Live hints: "That's a 26:24 5K" under goal-pace inputs, and the pace preview on the run log form.
(function () {
  function parse(t) {
    t = (t || '').trim();
    if (!t) return null;
    const parts = t.split(':').map(Number);
    if (parts.some(isNaN) || parts.length > 3) return null;
    if (parts.length === 1) return parts[0] * 60;
    return parts.reduce((acc, p) => acc * 60 + p, 0);
  }
  function clock(s) {
    s = Math.round(s);
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
    return (h ? h + ':' + String(m).padStart(2, '0') : m) + ':' + String(sec).padStart(2, '0');
  }

  const pace = document.getElementById('pace'), paceOut = document.getElementById('pace-out');
  if (pace && paceOut) {
    const upd = () => {
      const p = parse(pace.value);
      paceOut.textContent = p && p > 180 ? "That's a " + clock(p * 3.107) + ' 5K.' : '';
    };
    pace.addEventListener('input', upd);
    upd();
  }

  const dist = document.getElementById('distance'), time = document.getElementById('time'), out = document.getElementById('run-pace');
  if (dist && time && out) {
    const upd = () => {
      const d = parseFloat(dist.value), t = parse(time.value);
      out.textContent = d > 0 && t > 0 ? clock(t / d) : '–:––';
    };
    dist.addEventListener('input', upd);
    time.addEventListener('input', upd);
    upd();
  }
})();
