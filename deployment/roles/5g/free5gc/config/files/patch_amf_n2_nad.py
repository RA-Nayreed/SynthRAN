#!/usr/bin/env python3
import sys

repo = sys.argv[1]
path = f"{repo}/charts/free5gc/charts/free5gc-amf/templates/amf-n2-nad.yaml"

with open(path, encoding="utf-8") as handle:
    content = handle.read()

old = '          "type": {{ .Values.global.n2network.type | quote }},'
new = '''          "type": {{ .Values.global.n2network.type | quote }},
{{- if eq .Values.global.n2network.type "ovs" }}
          "bridge": {{ .Values.global.n2network.masterIf | quote }},
{{- end }}'''

if new in content:
    print("AMF N2 NAD patch already present")
    sys.exit(0)
if old not in content:
    print(f"ERROR: expected AMF N2 NAD pattern not found in {path}", file=sys.stderr)
    sys.exit(1)

with open(path, "w", encoding="utf-8") as handle:
    handle.write(content.replace(old, new, 1))

print("Patched amf-n2-nad.yaml")
