{{/*
Names and helpers of the SceneGEMS chart. One SceneGEMS cluster per namespace, so the objects have fixed names
(the roles of release.json name them: cluster/release/roles.py CONTROL_NODE_DEPLOYMENTS, CONTROL_NODE_STATEFUL_SETS,
WORKER_NODE_DEPLOYMENT, CONTROL_NODE_API_SERVICE).
*/}}

{{/* Labels every object of the chart carries. */}}
{{- define "scenegems.labels" -}}
app.kubernetes.io/part-of: scenegems
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/instance: {{ .Release.Name }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{/*
An image of the chart: the value when it is given (repository:tag or registry/repository@sha256:...), used as it is,
else <repository>:<imageTag>. Called with (list $ <value> <repository>).
*/}}
{{- define "scenegems.image" -}}
{{- $root := index . 0 -}}
{{- $value := index . 1 -}}
{{- $repository := index . 2 -}}
{{- if $value -}}
{{- $value -}}
{{- else -}}
{{- printf "%s:%s" $repository $root.Values.imageTag -}}
{{- end -}}
{{- end -}}

{{/* The node selector of a workload pinned to a Kubernetes node; nothing when the node is empty. */}}
{{- define "scenegems.nodeSelector" -}}
{{- if . }}
nodeSelector:
  kubernetes.io/hostname: {{ . | quote }}
{{- end }}
{{- end -}}

{{/* The ConfigMap that holds release.json (the chart's own copy, which the release bundle puts into the chart). */}}
{{- define "scenegems.releaseConfigMap" -}}
release-manifest
{{- end -}}

{{/* Where release.json is mounted in the control node and in every daemon (SCENEGEMS_RELEASE_MANIFEST). */}}
{{- define "scenegems.releaseManifestPath" -}}
/etc/scenegems/release.json
{{- end -}}

{{/*
An entry of workerNodes merged over workerNodeDefaults, key by key and not deeper: a slots, labels or components
value of the entry replaces the default as a whole. Called with (list $ <entry>); returns the merged entry as YAML.
*/}}
{{- define "scenegems.workerNode" -}}
{{- $root := index . 0 -}}
{{- $entry := index . 1 -}}
{{- $merged := dict -}}
{{- range $key, $default := $root.Values.workerNodeDefaults -}}
{{- if hasKey $entry $key -}}
{{- $_ := set $merged $key (get $entry $key) -}}
{{- else -}}
{{- $_ := set $merged $key $default -}}
{{- end -}}
{{- end -}}
{{- toYaml $merged -}}
{{- end -}}

{{/*
The checks a values schema cannot make: worker node names that are unique, and release.json in the chart. A values
file that fails one is refused before anything is installed.
*/}}
{{- define "scenegems.checks" -}}
{{- $names := dict -}}
{{- range .Values.workerNodes -}}
{{- if hasKey $names .name -}}
{{- fail (printf "workerNodes: the name %s is given twice; a worker node's name is its id on the control node" .name) -}}
{{- end -}}
{{- $_ := set $names .name true -}}
{{- end -}}
{{- if not (.Files.Get "release.json") -}}
{{- fail "the chart holds no release.json: install it from a release bundle (./build.sh --release <folder>), whose chart folder carries a copy" -}}
{{- end -}}
{{- end -}}
