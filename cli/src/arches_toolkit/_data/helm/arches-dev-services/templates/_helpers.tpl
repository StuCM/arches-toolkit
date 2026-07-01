{{/*
Resource names track the release name directly: the deploy command names
the release `<project>-services`, so services land as
`<project>-services-db` etc. — the endpoints it wires into the app chart.
*/}}
{{- define "devservices.fullname" -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "devservices.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}
