// Run log form: colons typed for you in the Time box, plus a live pace (or mph for rides) preview.
(function () {
  // "2430" -> "24:30", "12010" -> "1:20:10". Up to 2 digits stay as typed (= minutes).
  // Matches club.parse_clock on the server, so it also works if this script doesn't run.
  function withColons(raw) {
    const d = raw.replace(/\D/g, '').replace(/^0+(?=\d{3})/, '').slice(0, 6);
    if (d.length <= 2) return d;
    if (d.length <= 4) return d.slice(0, -2) + ':' + d.slice(-2);
    return d.slice(0, -4) + ':' + d.slice(-4, -2) + ':' + d.slice(-2);
  }

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

  // Runs and walks show pace (min/mi); rides show speed (mph).
  const dist = document.getElementById('distance'), time = document.getElementById('time'), out = document.getElementById('run-pace');
  const label = document.getElementById('run-pace-label'), unit = document.getElementById('run-pace-unit');
  if (dist && time && out) {
    const upd = () => {
      const d = parseFloat(dist.value), t = parse(time.value);
      const picked = document.querySelector('input[name=activity]:checked');
      const bike = picked && picked.value === 'bike';
      if (label) label.textContent = bike ? 'Speed' : 'Pace';
      if (unit) unit.textContent = bike ? ' mph' : ' /mi';
      if (!(d > 0 && t > 0)) { out.textContent = bike ? '––' : '–:––'; return; }
      out.textContent = bike ? (d / (t / 3600)).toFixed(1) : clock(t / d);
    };
    dist.addEventListener('input', upd);
    time.addEventListener('input', () => {
      const formatted = withColons(time.value);
      if (formatted !== time.value) time.value = formatted;
      upd();
    });
    document.querySelectorAll('input[name=activity]').forEach((r) => r.addEventListener('change', upd));
    upd();
  }
})();
