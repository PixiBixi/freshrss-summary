{{/*
Expand the name of the chart.
*/}}
{{- define "freshrss-summary.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this
(by the DNS naming spec). If the release name contains the chart name it will be
used as is.
*/}}
{{- define "freshrss-summary.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart label value (chart name + version, no "+" allowed in label values).
*/}}
{{- define "freshrss-summary.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels — applied to every resource.
*/}}
{{- define "freshrss-summary.labels" -}}
helm.sh/chart: {{ include "freshrss-summary.chart" . }}
{{ include "freshrss-summary.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels — used in matchLabels and Service selector.
Must be stable across upgrades; do NOT include version here.
*/}}
{{- define "freshrss-summary.selectorLabels" -}}
app.kubernetes.io/name: {{ include "freshrss-summary.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
ServiceAccount name.
*/}}
{{- define "freshrss-summary.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "freshrss-summary.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Secret name — either the user-provided existing secret or the chart-managed one.
*/}}
{{- define "freshrss-summary.secretName" -}}
{{- if .Values.secret.existingSecret }}
{{- .Values.secret.existingSecret }}
{{- else }}
{{- include "freshrss-summary.fullname" . }}
{{- end }}
{{- end }}

{{/*
PVC name — either the user-provided existing claim or the chart-managed one.
*/}}
{{- define "freshrss-summary.pvcName" -}}
{{- if .Values.persistence.existingClaim }}
{{- .Values.persistence.existingClaim }}
{{- else }}
{{- include "freshrss-summary.fullname" . }}
{{- end }}
{{- end }}
