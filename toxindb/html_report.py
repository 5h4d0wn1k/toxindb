"""Interactive HTML report generation."""
from __future__ import annotations

from typing import List
from .heuristics import Alert
from datetime import datetime, timezone
import json


def render_html_report(alerts: List[Alert]) -> str:
    alerts_json = json.dumps([a.to_dict() for a in alerts])
    ts = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    html = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>toxindb Report</title>
<style>
body { font-family: system-ui, -apple-system, sans-serif; margin: 40px; background: #f5f5f5; }
.container { max-width: 1200px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
h1 { color: #333; }
.alert { border-left: 4px solid #e74c3c; padding: 15px; margin: 10px 0; background: #fef9f9; }
.alert.warning { border-left-color: #f39c12; background: #fffef5; }
.alert.note { border-left-color: #3498db; background: #f5fbff; }
.badge { padding: 4px 8px; border-radius: 4px; font-size: 12px; background: #e74c3c; color: white; }
.badge.warning { background: #f39c12; }
.badge.note { background: #3498db; }
</style>
</head>
<body>
<div class="container">
<h1>toxindb Analysis Report</h1>
<p>Generated: """ + ts + """</p>
<p>Total Alerts: """ + str(len(alerts)) + """</p>
<div id="alerts"></div>
<pre id="data" style="display:none">""" + alerts_json + """</pre>
</div>
<script>
const alerts = JSON.parse(document.getElementById('data').textContent);
const container = document.getElementById('alerts');
alerts.forEach(function(a) {
  const div = document.createElement('div');
  div.className = 'alert ' + a.severity;
  var html = '<span class="badge ' + a.severity + '">' + a.heuristic_id + '</span> <strong>' + a.heuristic_name + '</strong> (sev: ' + a.severity + ')<br/>';
  html += '<small>' + a.detail + '</small><br/>';
  if (a.query_id) html += 'Query: ' + a.query_id + '<br/>';
  if (a.doc_ids && a.doc_ids.length) html += 'Docs: ' + a.doc_ids.slice(0,10).join(', ');
  div.innerHTML = html;
  container.appendChild(div);
});
</script>
</body>
</html>"""
    return html
