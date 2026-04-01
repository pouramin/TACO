
(function () {
  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
  function svgEl(name, attrs) {
    var node = document.createElementNS('http://www.w3.org/2000/svg', name);
    if (attrs) {
      Object.keys(attrs).forEach(function (key) { node.setAttribute(key, String(attrs[key])); });
    }
    return node;
  }
  function renderChart(root) {
    var dataNode = root.querySelector('.chart-data');
    var svg = root.querySelector('.chart-svg');
    var tooltip = root.querySelector('.chart-tooltip');
    if (!dataNode || !svg || !tooltip) return;
    var points;
    try { points = JSON.parse(dataNode.textContent || '[]'); } catch (err) { points = []; }
    if (!Array.isArray(points) || !points.length) return;
    points.sort(function (a, b) { return String(a.date).localeCompare(String(b.date)); });

    var width = 960, height = 430;
    var margin = { l: 72, r: 28, t: 14, b: 44 };
    var chartW = width - margin.l - margin.r;
    var chartH = height - margin.t - margin.b;
    var values = points.map(function (p) { return Number(p.value) || 0; });
    var minVal = Math.min.apply(null, values);
    var maxVal = Math.max.apply(null, values);
    if (Math.abs(maxVal - minVal) < 1e-9) maxVal = minVal + 1;
    var pad = Math.max(1, (maxVal - minVal) * 0.08);
    minVal = Math.max(0, minVal - pad * 0.35);
    maxVal = maxVal + pad;

    function sx(i) {
      if (points.length === 1) return margin.l + chartW / 2;
      return margin.l + (i / (points.length - 1)) * chartW;
    }
    function sy(v) {
      return margin.t + (1 - (v - minVal) / (maxVal - minVal)) * chartH;
    }

    svg.innerHTML = '';
    svg.setAttribute('viewBox', '0 0 ' + width + ' ' + height);
    svg.setAttribute('preserveAspectRatio', 'none');

    for (var t = 0; t <= 5; t++) {
      var val = minVal + (maxVal - minVal) * t / 5;
      var yy = sy(val);
      svg.appendChild(svgEl('line', { x1: margin.l, y1: yy, x2: width - margin.r, y2: yy, stroke: '#27314e', 'stroke-width': 1 }));
      var yLabel = svgEl('text', { x: margin.l - 10, y: yy + 4, 'text-anchor': 'end', fill: '#93a4c3', 'font-size': 12, 'font-family': 'Inter, Arial, sans-serif' });
      yLabel.textContent = (Math.round(val * 100) / 100).toFixed(0);
      svg.appendChild(yLabel);
    }

    Array.from(new Set([0, Math.floor((points.length - 1) / 2), points.length - 1])).forEach(function (idx) {
      var xx = sx(idx);
      var xLabel = svgEl('text', { x: xx, y: height - 14, 'text-anchor': 'middle', fill: '#93a4c3', 'font-size': 12, 'font-family': 'Inter, Arial, sans-serif' });
      xLabel.textContent = points[idx].date;
      svg.appendChild(xLabel);
    });

    var lineD = values.map(function (v, i) { return (i === 0 ? 'M' : 'L') + ' ' + sx(i).toFixed(2) + ' ' + sy(v).toFixed(2); }).join(' ');
    var areaD = 'M ' + sx(0).toFixed(2) + ' ' + sy(values[0]).toFixed(2) + ' ' + values.map(function (v, i) { return 'L ' + sx(i).toFixed(2) + ' ' + sy(v).toFixed(2); }).join(' ') + ' L ' + sx(points.length - 1).toFixed(2) + ' ' + (height - margin.b).toFixed(2) + ' L ' + sx(0).toFixed(2) + ' ' + (height - margin.b).toFixed(2) + ' Z';
    svg.appendChild(svgEl('path', { d: areaD, fill: 'rgba(105, 167, 255, 0.08)' }));
    svg.appendChild(svgEl('path', { d: lineD, fill: 'none', stroke: '#69a7ff', 'stroke-width': 4, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }));

    var hoverLine = svgEl('line', { x1: margin.l, y1: margin.t, x2: margin.l, y2: height - margin.b, stroke: '#7fb1ff', 'stroke-width': 1, 'stroke-dasharray': '4 4', opacity: 0 });
    var hoverDot = svgEl('circle', { cx: margin.l, cy: margin.t, r: 5.5, fill: '#69a7ff', stroke: '#f4f7fb', 'stroke-width': 2, opacity: 0 });
    svg.appendChild(hoverLine);
    svg.appendChild(hoverDot);

    var lastIndex = points.length - 1;
    var latestDot = svgEl('circle', { cx: sx(lastIndex), cy: sy(values[lastIndex]), r: 6, fill: '#69a7ff' });
    var latestLabel = svgEl('text', { x: sx(lastIndex) - 8, y: sy(values[lastIndex]) - 12, 'text-anchor': 'end', fill: '#f5f7fb', 'font-size': 12, 'font-weight': 700, 'font-family': 'Inter, Arial, sans-serif' });
    latestLabel.textContent = values[lastIndex].toFixed(2);
    svg.appendChild(latestDot);
    svg.appendChild(latestLabel);

    var overlay = svgEl('rect', { x: margin.l, y: margin.t, width: chartW, height: chartH, fill: 'transparent', style: 'cursor: crosshair;' });
    svg.appendChild(overlay);

    function update(clientX, clientY) {
      var bounds = svg.getBoundingClientRect();
      var relX = ((clientX - bounds.left) / bounds.width) * width;
      var x = clamp(relX, margin.l, width - margin.r);
      var ratio = chartW === 0 ? 0 : (x - margin.l) / chartW;
      var idx = clamp(Math.round(ratio * (points.length - 1)), 0, points.length - 1);
      var px = sx(idx);
      var py = sy(values[idx]);
      hoverLine.setAttribute('x1', px); hoverLine.setAttribute('x2', px); hoverLine.setAttribute('opacity', 1);
      hoverDot.setAttribute('cx', px); hoverDot.setAttribute('cy', py); hoverDot.setAttribute('opacity', 1);
      tooltip.hidden = false;
      tooltip.innerHTML = '<strong>' + points[idx].value.toFixed(2) + '</strong><span>' + points[idx].date + '</span>';
      var tipLeft = clamp((px / width) * bounds.width, 84, bounds.width - 84);
      var tipTop = (py / height) * bounds.height;
      tooltip.style.left = tipLeft + 'px';
      tooltip.style.top = tipTop + 'px';
    }
    function hide() {
      hoverLine.setAttribute('opacity', 0);
      hoverDot.setAttribute('opacity', 0);
      tooltip.hidden = true;
    }

    overlay.addEventListener('mousemove', function (e) { update(e.clientX, e.clientY); });
    overlay.addEventListener('mouseenter', function (e) { update(e.clientX, e.clientY); });
    overlay.addEventListener('mouseleave', hide);
    overlay.addEventListener('touchstart', function (e) { if (e.touches && e.touches[0]) update(e.touches[0].clientX, e.touches[0].clientY); }, { passive: true });
    overlay.addEventListener('touchmove', function (e) { if (e.touches && e.touches[0]) update(e.touches[0].clientX, e.touches[0].clientY); }, { passive: true });
    overlay.addEventListener('touchend', hide, { passive: true });
  }

  function boot() { document.querySelectorAll('.js-line-chart').forEach(renderChart); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
})();
