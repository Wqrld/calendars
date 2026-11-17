{{/*
Expand the name of the chart.
*/}}
{{- define "calendars.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "calendars.fullname" -}}
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
Create chart name and version as used by the chart label.
*/}}
{{- define "calendars.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
calendars.labels
*/}}
{{- define "calendars.labels" -}}
helm.sh/chart: {{ include "calendars.chart" . }}
{{ include "calendars.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "calendars.selectorLabels" -}}
app.kubernetes.io/name: {{ include "calendars.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
transform dictionary of environment variables
Usage : {{ include "calendars.env.transformDict" .Values.envVars }}

Example:
envVars:
  # Using simple strings as env vars
  ENV_VAR_NAME: "envVar value"
  # Using a value from a configMap
  ENV_VAR_FROM_CM:
    configMapKeyRef:
      name: cm-name
      key: "key_in_cm"
  # Using a value from a secret
  ENV_VAR_FROM_SECRET:
    secretKeyRef:
      name: secret-name
      key: "key_in_secret"
*/}}
{{- define "calendars.env.transformDict" -}}
{{- range $key, $value := . }}
- name: {{ $key | quote }}
{{- if $value | kindIs "map" }}
  valueFrom: {{ $value | toYaml | nindent 4 }}
{{- else }}
  value: {{ $value | quote }}
{{- end }}
{{- end }}
{{- end }}


{{/*
calendars env vars
*/}}
{{- define "calendars.common.env" -}}
{{- $topLevelScope := index . 0 -}}
{{- $workerScope := index . 1 -}}
{{- include "calendars.env.transformDict" $workerScope.envVars -}}
{{- end }}

{{/*
calendars backend django env vars - combines common backend.envVars with backend.django.envVars
*/}}
{{- define "calendars.backend.django.env" -}}
{{- $topLevelScope := index . 0 -}}
{{- $workerScope := index . 1 -}}
{{- include "calendars.env.transformDict" $workerScope.envVars -}}
{{- include "calendars.env.transformDict" (($workerScope.django | default dict).envVars | default dict) -}}
{{- end }}

{{/*
calendars worker env vars - combines common backend.envVars with backend.worker.envVars
*/}}
{{- define "calendars.backend.worker.env" -}}
{{- $topLevelScope := index . 0 -}}
{{- $workerScope := index . 1 -}}
{{- include "calendars.env.transformDict" $workerScope.envVars -}}
{{- include "calendars.env.transformDict" ($workerScope.worker.envVars | default dict) -}}
{{- end }}

{{/*
Common labels

Requires array with top level scope and component name
*/}}
{{- define "calendars.common.labels" -}}
{{- $topLevelScope := index . 0 -}}
{{- $component := index . 1 -}}
{{- include "calendars.labels" $topLevelScope }}
app.kubernetes.io/component: {{ $component }}
{{- end }}

{{/*
Common selector labels

Requires array with top level scope and component name
*/}}
{{- define "calendars.common.selectorLabels" -}}
{{- $topLevelScope := index . 0 -}}
{{- $component := index . 1 -}}
{{- include "calendars.selectorLabels" $topLevelScope }}
app.kubernetes.io/component: {{ $component }}
{{- end }}

{{- define "calendars.probes.abstract" -}}
{{- if .exec -}}
exec:
{{- toYaml .exec | nindent 2 }}
{{- else if .tcpSocket -}}
tcpSocket:
{{- toYaml .tcpSocket | nindent 2 }}
{{- else -}}
httpGet:
  path: {{ .path }}
  port: {{ .targetPort }}
{{- end }}
initialDelaySeconds: {{ .initialDelaySeconds | eq nil | ternary 0 .initialDelaySeconds }}
timeoutSeconds: {{ .timeoutSeconds | eq nil | ternary 1 .timeoutSeconds }}
{{- end }}

{{/*
Full name for the backend

Requires top level scope
*/}}
{{- define "calendars.backend.fullname" -}}
{{ include "calendars.fullname" . }}-backend
{{- end }}

{{/*
Full name for the frontend

Requires top level scope
*/}}
{{- define "calendars.frontend.fullname" -}}
{{ include "calendars.fullname" . }}-frontend
{{- end }}

{{/*
Full name for the CalDAV server

Requires top level scope
*/}}
{{- define "calendars.caldav.fullname" -}}
{{ include "calendars.fullname" . }}-caldav
{{- end }}

{{/*
Full name for the Worker

Requires top level scope
*/}}


{{- define "calendars.backend.worker.fullname" -}}
{{ include "calendars.fullname" . }}-worker
{{- end }}

{{/*
Usage : {{ include "calendars.secret.dockerconfigjson.name" (dict "fullname" (include "calendars.fullname" .) "imageCredentials" .Values.path.to.the.image1) }}
*/}}
{{- define "calendars.secret.dockerconfigjson.name" }}
{{- if (default (dict) .imageCredentials).name }}{{ .imageCredentials.name }}{{ else }}{{ .fullname | trunc 63 | trimSuffix "-" }}-dockerconfig{{ end -}}
{{- end }}

{{/*
Usage : {{ include "calendars.secret.dockerconfigjson" (dict "fullname" (include "calendars.fullname" .) "imageCredentials" .Values.path.to.the.image1) }}
*/}}
{{- define "calendars.secret.dockerconfigjson" }}
{{- if .imageCredentials -}}
apiVersion: v1
kind: Secret
metadata:
  name: {{ template "calendars.secret.dockerconfigjson.name" (dict "fullname" .fullname "imageCredentials" .imageCredentials) }}
  annotations:
    "helm.sh/hook": pre-install,pre-upgrade
    "helm.sh/hook-weight": "-5"
    "helm.sh/hook-delete-policy": before-hook-creation
type: kubernetes.io/dockerconfigjson
data:
  .dockerconfigjson: {{ template "calendars.secret.dockerconfigjson.data" .imageCredentials }}
{{- end -}}
{{- end }}
