{{/*
Shared definitions. The env/volumes/pod-spec helpers play the role of the
compose files' `x-arches` YAML anchor: web/worker/api/init differ only in
command and resources.
*/}}

{{- define "arches.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "arches.fullname" -}}
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

{{- define "arches.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "arches.labels" -}}
helm.sh/chart: {{ include "arches.chart" . }}
{{ include "arches.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "arches.selectorLabels" -}}
app.kubernetes.io/name: {{ include "arches.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "arches.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "arches.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/* ---- Derived project wiring (compose .env equivalents) ---- */}}

{{- define "arches.projectPackage" -}}
{{- required "project.package is required (the project's Python package name)" .Values.project.package }}
{{- end }}

{{- define "arches.djangoSettingsModule" -}}
{{- default (printf "%s.settings" (include "arches.projectPackage" .)) .Values.project.djangoSettingsModule }}
{{- end }}

{{- define "arches.wsgiApp" -}}
{{- default (printf "%s.wsgi:application" (include "arches.projectPackage" .)) .Values.project.wsgiApp }}
{{- end }}

{{- define "arches.celeryApp" -}}
{{- default (include "arches.projectPackage" .) .Values.project.celeryApp }}
{{- end }}

{{- define "arches.image" -}}
{{- $repo := required "image.repository is required" .Values.image.repository -}}
{{- $tag := required "image.tag is required (staging: main-<bid>; prod: vX.Y.Z)" .Values.image.tag -}}
{{- printf "%s:%s" $repo $tag }}
{{- end }}

{{- define "arches.staticImage" -}}
{{- $repo := default (printf "%s-static" .Values.image.repository) .Values.staticImage.repository -}}
{{- $tag := default .Values.image.tag .Values.staticImage.tag -}}
{{- printf "%s:%s" $repo $tag }}
{{- end }}

{{- define "arches.cantaloupeEndpoint" -}}
{{- if .Values.cantaloupe.httpEndpoint -}}
{{- .Values.cantaloupe.httpEndpoint -}}
{{- else if .Values.cantaloupe.enabled -}}
{{- printf "http://%s-cantaloupe:8182/" (include "arches.fullname" .) -}}
{{- end -}}
{{- end }}

{{/*
Structural env for every Arches container (web/worker/api/init and the
frontend-configuration initContainer). Matches compose.yaml's environment
block name-for-name — that file is the canonical contract.
*/}}
{{- define "arches.env" -}}
- name: DJANGO_SETTINGS_MODULE
  value: {{ include "arches.djangoSettingsModule" . | quote }}
- name: PROJECT_NAME
  value: {{ include "arches.projectPackage" . | quote }}
- name: PROJECT_PACKAGE
  value: {{ include "arches.projectPackage" . | quote }}
- name: WSGI_APP
  value: {{ include "arches.wsgiApp" . | quote }}
- name: CELERY_APP
  value: {{ include "arches.celeryApp" . | quote }}
- name: PYTHONWARNINGS
  value: "ignore::SyntaxWarning"
- name: ARCHES_FRONTEND_CONFIGURATION_DIR
  value: {{ .Values.frontendConfiguration.dir | quote }}
- name: ARCHES_UPLOADED_FILES_DIR
  value: /var/arches/uploadedfiles
- name: PGHOST
  value: {{ required "postgres.host is required" .Values.postgres.host | quote }}
- name: PGPORT
  value: {{ .Values.postgres.port | quote }}
- name: PGUSER
  value: {{ .Values.postgres.user | quote }}
- name: PGDBNAME
  value: {{ .Values.postgres.database | quote }}
- name: PGPASSWORD
  valueFrom:
    secretKeyRef:
      {{- if .Values.postgres.existingSecret }}
      name: {{ .Values.postgres.existingSecret }}
      key: {{ .Values.postgres.existingSecretKey }}
      {{- else }}
      name: {{ include "arches.fullname" . }}-env
      key: pg-password
      {{- end }}
- name: ESSCHEME
  value: {{ .Values.elasticsearch.scheme | quote }}
- name: ESHOST
  value: {{ required "elasticsearch.host is required" .Values.elasticsearch.host | quote }}
- name: ESPORT
  value: {{ .Values.elasticsearch.port | quote }}
- name: RABBITMQ_URL
  valueFrom:
    secretKeyRef:
      {{- if .Values.rabbitmq.existingSecret }}
      name: {{ .Values.rabbitmq.existingSecret }}
      key: {{ .Values.rabbitmq.existingSecretKey }}
      {{- else }}
      name: {{ include "arches.fullname" . }}-env
      key: rabbitmq-url
      {{- end }}
{{- with (include "arches.cantaloupeEndpoint" .) }}
- name: CANTALOUPE_HTTP_ENDPOINT
  value: {{ . | quote }}
{{- end }}
{{- end }}

{{/* envFrom: plain ConfigMap + secret env. */}}
{{- define "arches.envFrom" -}}
- configMapRef:
    name: {{ include "arches.fullname" . }}-env
{{- if .Values.existingSecretEnv }}
- secretRef:
    name: {{ .Values.existingSecretEnv }}
{{- else if .Values.secretEnv }}
- secretRef:
    name: {{ include "arches.fullname" . }}-env
{{- end }}
{{- end }}

{{/*
Volumes for Arches pods. Everything writable is a mount: the containers
run with readOnlyRootFilesystem. static_root has no volume by design —
assets are baked at build time (docs/k8s-deployment.md, init split).
*/}}
{{- define "arches.volumes" -}}
- name: tmp
  emptyDir: {}
- name: logs
  emptyDir: {}
{{- if .Values.frontendConfiguration.generateAtBoot }}
- name: frontend-configuration
  emptyDir: {}
{{- end }}
{{- if .Values.uploads.persistence.enabled }}
- name: uploadedfiles
  persistentVolumeClaim:
    claimName: {{ default (printf "%s-uploadedfiles" (include "arches.fullname" .)) .Values.uploads.persistence.existingClaim }}
{{- else }}
- name: uploadedfiles
  emptyDir: {}
{{- end }}
{{- end }}

{{- define "arches.volumeMounts" -}}
- name: tmp
  mountPath: /tmp
- name: logs
  mountPath: /var/arches/logs
{{- if .Values.frontendConfiguration.generateAtBoot }}
- name: frontend-configuration
  mountPath: {{ .Values.frontendConfiguration.dir }}
  readOnly: true
{{- end }}
- name: uploadedfiles
  mountPath: /var/arches/uploadedfiles
{{- end }}

{{/*
Per-pod initContainer: regenerate frontend_configuration into the pod's
emptyDir (single writer per pod; main containers mount it read-only).
Fallback until the prod image bakes it — see image-contract gap 4.
*/}}
{{- define "arches.frontendConfigInitContainer" -}}
{{- if .Values.frontendConfiguration.generateAtBoot }}
- name: frontend-configuration
  image: {{ include "arches.image" . }}
  imagePullPolicy: {{ .Values.image.pullPolicy }}
  securityContext:
    {{- toYaml .Values.containerSecurityContext | nindent 4 }}
  env:
    {{- include "arches.env" . | nindent 4 }}
  envFrom:
    {{- include "arches.envFrom" . | nindent 4 }}
  command:
    - python
    - -c
    - |
      import django
      django.setup()
      from arches.app.utils.frontend_configuration_utils.generate_frontend_configuration import generate_frontend_configuration
      generate_frontend_configuration()
      print("frontend_configuration regenerated")
  volumeMounts:
    - name: tmp
      mountPath: /tmp
    - name: logs
      mountPath: /var/arches/logs
    - name: frontend-configuration
      mountPath: {{ .Values.frontendConfiguration.dir }}
  resources:
    requests:
      cpu: 100m
      memory: 512Mi
    limits:
      memory: 1Gi
{{- end }}
{{- end }}
